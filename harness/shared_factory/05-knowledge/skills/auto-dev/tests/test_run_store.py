from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "harness" / "skills" / "auto-dev" / "scripts" / "auto_dev_state.py"
sys.path.insert(0, str(ROOT / "harness" / "skills" / "auto-dev" / "scripts"))

import auto_dev_state
import run_store


def claim_args(run_dir: Path, owner: str, key: str) -> argparse.Namespace:
    return argparse.Namespace(
        run_dir=run_dir,
        owner_run_id=owner,
        heartbeat_ttl_seconds=900,
        distributed_token=f"test:{owner}",
        actor="test",
        receipt="test claim",
        idempotency_key=key,
    )


def transition_args(run_dir: Path, to: str, key: str) -> argparse.Namespace:
    return argparse.Namespace(
        run_dir=run_dir,
        to=to,
        from_state=None,
        actor="test",
        reason=f"test to {to}",
        receipt=f"test:{to}",
        idempotency_key=key,
        ref=None,
    )


class RunStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="run-store-test-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.db_path = self.tmp / "agentic_os.db"
        previous = os.environ.get(run_store.DB_ENV_VAR)

        def restore() -> None:
            if previous is None:
                os.environ.pop(run_store.DB_ENV_VAR, None)
            else:
                os.environ[run_store.DB_ENV_VAR] = previous

        self.addCleanup(restore)
        os.environ[run_store.DB_ENV_VAR] = str(self.db_path)

    def store(self) -> run_store.SqliteRunStore:
        return run_store.create_run_store()

    def test_ac_m1_concurrent_claims_grant_exactly_one(self) -> None:
        barrier = threading.Barrier(2)
        results: dict[str, run_store.ClaimResult] = {}

        def contender(run_id: str) -> None:
            store = run_store.create_run_store()
            barrier.wait()
            results[run_id] = store.claim(
                "wi/concurrent", run_id, f"owner-{run_id}", "host", 1234, 900,
                project="fixture_project", work_item_path="/tmp/wi-concurrent",
            )

        threads = [threading.Thread(target=contender, args=(f"run-{i}",)) for i in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        granted = [r for r in results.values() if r.granted]
        denied = [r for r in results.values() if not r.granted]
        self.assertEqual(len(granted), 1)
        self.assertEqual(len(denied), 1)
        self.assertEqual(denied[0].reason, "held_by_other")

    def test_ac_m2_expired_lease_is_claimable(self) -> None:
        store = self.store()
        first = store.claim("wi/expiry", "run-a", "owner-a", "host", 1, -5, project="p", work_item_path="/tmp/x")
        self.assertTrue(first.granted)
        second = store.claim("wi/expiry", "run-b", "owner-b", "host", 2, 900, project="p", work_item_path="/tmp/x")
        self.assertTrue(second.granted)
        self.assertEqual(store.get("wi/expiry").run_id, "run-b")

    def test_ac_m2_terminal_release_frees_the_row(self) -> None:
        store = self.store()
        self.assertTrue(store.claim("wi/release", "run-a", "owner-a", "host", 1, 900, project="p", work_item_path="/tmp/x").granted)
        blocked = store.claim("wi/release", "run-b", "owner-b", "host", 2, 900, project="p", work_item_path="/tmp/x")
        self.assertFalse(blocked.granted)
        store.upsert_state("run-a", "blocked", True, run_store.utc_now(), refs={})
        store.release("run-a")
        row = store.get("wi/release")
        self.assertIsNone(row.lease_owner)
        self.assertIsNone(row.lease_expires_at)
        reclaimed = store.claim("wi/release", "run-b", "owner-b", "host", 2, 900, project="p", work_item_path="/tmp/x")
        self.assertTrue(reclaimed.granted)

    def test_renew_extends_only_held_leases(self) -> None:
        store = self.store()
        store.claim("wi/renew", "run-a", "owner-a", "host", 1, 900, project="p", work_item_path="/tmp/x")
        self.assertTrue(store.renew("run-a", 1800))
        store.release("run-a")
        self.assertFalse(store.renew("run-a", 1800))

    def test_ac_m4_duplicate_idempotency_key_is_noop(self) -> None:
        store = self.store()
        store.claim("wi/steps", "run-a", "owner-a", "host", 1, 900, project="p", work_item_path="/tmp/x")
        ts = run_store.utc_now()
        self.assertTrue(store.record_step("run-a", 1, "discovered", "claimed", "claim:wi/steps", ts, "r1"))
        self.assertFalse(store.record_step("run-a", 2, "discovered", "claimed", "claim:wi/steps", ts, "r2"))
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
            count = conn.execute("SELECT COUNT(*) FROM step_events WHERE run_id = 'run-a'").fetchone()[0]
        self.assertEqual(count, 1)

    def test_ac_m5_list_in_flight_returns_non_terminal_only(self) -> None:
        store = self.store()
        store.claim("wi/open-1", "run-1", "o1", "host", 1, 900, project="proj_a", work_item_path="/tmp/1")
        store.claim("wi/open-2", "run-2", "o2", "host", 2, 900, project="proj_b", work_item_path="/tmp/2")
        store.claim("wi/done", "run-3", "o3", "host", 3, 900, project="proj_a", work_item_path="/tmp/3")
        store.upsert_state("run-3", "merged", True, run_store.utc_now(), refs={})
        in_flight = {row.work_item_id for row in store.list_in_flight()}
        self.assertEqual(in_flight, {"wi/open-1", "wi/open-2"})
        proj_a = [row.work_item_id for row in store.list_in_flight("proj_a")]
        self.assertEqual(proj_a, ["wi/open-1"])


class RunStoreWiringTests(unittest.TestCase):
    """auto_dev_state.py integration: flag-guarded dual-write around authoritative files."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="run-store-wiring-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.run_dir = self.tmp / "artifacts" / "auto-dev"
        self.db_path = self.tmp / "agentic_os.db"
        self.previous_db = os.environ.get(run_store.DB_ENV_VAR)
        self.previous_flag = os.environ.get(auto_dev_state.RUNSTORE_ENV_VAR)

        def restore() -> None:
            for key, value in (
                (run_store.DB_ENV_VAR, self.previous_db),
                (auto_dev_state.RUNSTORE_ENV_VAR, self.previous_flag),
            ):
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.addCleanup(restore)
        os.environ[run_store.DB_ENV_VAR] = str(self.db_path)

    def init_run(self, name: str = "wiring") -> None:
        init_args = auto_dev_state.fixture_init_args(self.run_dir, {"name": name})
        with contextlib.redirect_stdout(io.StringIO()):
            auto_dev_state.command_init(init_args)

    def quiet(self, func, namespace) -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            return func(namespace)

    def test_dual_write_and_list_in_flight_cli(self) -> None:
        os.environ[auto_dev_state.RUNSTORE_ENV_VAR] = "sqlite"
        self.init_run()
        self.assertEqual(self.quiet(auto_dev_state.command_claim, claim_args(self.run_dir, "owner-1", "claim:wiring")), 0)
        self.assertEqual(self.quiet(auto_dev_state.command_transition, transition_args(self.run_dir, "context_loaded", "k1")), 0)
        store = run_store.create_run_store()
        row = store.get("fixture/wiring")
        self.assertEqual(row.current_state, "context_loaded")
        self.assertFalse(row.terminal)
        self.assertEqual(row.lease_owner, "owner-1")
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "list-in-flight"],
            text=True,
            capture_output=True,
            check=True,
            env=os.environ.copy(),
        )
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual([r["work_item_id"] for r in payload["rows"]], ["fixture/wiring"])
        self.assertEqual(
            self.quiet(auto_dev_state.command_release, argparse.Namespace(run_dir=self.run_dir, reason="test done")),
            0,
        )
        self.assertIsNone(store.get("fixture/wiring").lease_owner)
        # file layer stayed authoritative and unchanged in shape
        state = auto_dev_state.load_state(self.run_dir)
        self.assertEqual(state["current_state"], "context_loaded")
        self.assertIsNone(state["claim"])

    def test_db_verdict_wins_when_lease_held_elsewhere(self) -> None:
        os.environ[auto_dev_state.RUNSTORE_ENV_VAR] = "sqlite"
        self.init_run()
        store = run_store.create_run_store()
        # another host/run already holds the DB lease for this work item
        self.assertTrue(
            store.claim("fixture/wiring", "other-run", "other-owner", "otherhost", 42, 900,
                        project="fixture_project", work_item_path="/elsewhere").granted
        )
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = auto_dev_state.command_claim(claim_args(self.run_dir, "owner-1", "claim:held"))
        self.assertEqual(code, 2)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["reason"], "held_by_other")
        # the local file claim was NOT taken
        self.assertIsNone(auto_dev_state.load_state(self.run_dir)["claim"])

    def test_ac_m6_flag_off_produces_no_db_and_keeps_file_flow(self) -> None:
        os.environ[auto_dev_state.RUNSTORE_ENV_VAR] = "off"
        self.init_run(name="flag_off")
        self.assertEqual(self.quiet(auto_dev_state.command_claim, claim_args(self.run_dir, "owner-1", "claim:off")), 0)
        self.assertEqual(self.quiet(auto_dev_state.command_transition, transition_args(self.run_dir, "context_loaded", "k-off")), 0)
        self.assertEqual(
            self.quiet(auto_dev_state.command_release, argparse.Namespace(run_dir=self.run_dir, reason="off done")),
            0,
        )
        self.assertFalse(self.db_path.exists())
        state = auto_dev_state.load_state(self.run_dir)
        self.assertEqual(state["current_state"], "context_loaded")
        self.assertIsNone(state["claim"])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = auto_dev_state.command_list_in_flight(argparse.Namespace(project=None))
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(buffer.getvalue())["reason"], "runstore_disabled")
        self.assertFalse(self.db_path.exists())


if __name__ == "__main__":
    unittest.main()
