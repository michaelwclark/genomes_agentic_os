from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
import yaml

import genomes_agentic_os.cli.auto_dev as auto_dev_cli
import genomes_agentic_os.development_delivery as delivery
from genomes_agentic_os.cli import main
from genomes_agentic_os.development_delivery import TaskState
from genomes_agentic_os.lifecycle import create_project_work_item
from genomes_agentic_os.scaffold import create_project, register_project_worktree
from genomes_agentic_os.state import work_items as canonical_work_items
from genomes_agentic_os.state.db import connect as connect_state
from genomes_agentic_os.state.db import default_db_path
from genomes_agentic_os.work_lifecycle import promote_project_work_item


def _git(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return completed.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    remote = tmp_path / "remote.git"
    _git("init", "--bare", str(remote))
    repo = tmp_path / "repo"
    _git("init", "-b", "main", str(repo))
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", "base", cwd=repo)
    _git("remote", "add", "origin", str(remote), cwd=repo)
    _git("push", "-u", "origin", "main", cwd=repo)
    return repo, _git("rev-parse", "HEAD", cwd=repo)


def _project(root: Path, repo: Path) -> Path:
    create_project(root, "acme", "app", repo=str(repo))
    project = root / "domains" / "acme" / "02-projects" / "app"
    profile = {
        "version": 1,
        "enabled": True,
        "tracker": {"primary": "linear"},
        "repository": {"root": str(repo), "base_branch": "main"},
        "worktrees": {
            "directory": "worktrees",
            "branch_template": "feature/{ticket}-{slug}",
        },
        "work_items": {"active_status": "building"},
        "runtime": {"ownership": "not_managed", "provider": "none", "identity": "not-managed"},
        "validation": {
            "commands": ["python3 -m pytest tests -q"],
            "test_policy": "risk_based_triangle",
            "ci_fallback_on_environment_failure": True,
        },
        "review": {
            "authorship": {"ours": ["github:test-operator"]},
            "opposing_harness": {"required": True},
        },
        "merge": {"policy": "never_auto"},
        "recovery": {
            "max_attempts": 3,
            "lease_minutes": 30,
            "stale_after_minutes": 45,
        },
    }
    (project / "config" / "development.yml").write_text(
        yaml.safe_dump(profile, sort_keys=False), encoding="utf-8"
    )
    return project


def _fake_worktree(monkeypatch: pytest.MonkeyPatch, ticket: str, base_sha: str) -> None:
    slug = ticket.lower()
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": slug,
            "path": f"/tmp/{slug}",
            "branch": f"feature/{slug}",
            "base_sha": base_sha,
        },
    )


def test_canonical_work_state_tracks_delivery_and_never_regresses_or_clears_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    _fake_worktree(monkeypatch, "CC-56", base_sha)
    run = delivery.start_development_run(
        root, "acme", "app", ["CC-56"], run_id="canonical-progress", apply=True
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"]))
    canonical_work_id = str(task.read()["canonical_work_id"])

    connection = connect_state(default_db_path(root))
    try:
        assert canonical_work_items.get(connection, canonical_work_id)["state"] == "building"
    finally:
        connection.close()

    for state_name in ("planned", "implementing", "local_validation"):
        task.transition(
            state_name,
            receipt=f"proof:{state_name}",
            idempotency_key=f"cc-56:{state_name}",
        )
    connection = connect_state(default_db_path(root))
    try:
        progressed = canonical_work_items.get(connection, canonical_work_id)
        assert progressed["state"] == "validating"
        canonical_work_items.update(
            connection,
            canonical_work_id,
            state="blocked",
            attention="active",
            blocked_reason="QA environment hold",
            receipt_ref="qa:hold",
            verified=True,
        )
    finally:
        connection.close()

    profile_path = project / "config" / "development.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["tracker"]["primary"] = "jira"
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-56"],
        run_id="canonical-progress",
        requested_stage="qa",
        goal="qa",
        provision_worktree=False,
        selected_work_item=Path(task.read()["work_item"]),
        existing_state_only=True,
        apply=True,
    )
    connection = connect_state(default_db_path(root))
    try:
        preserved = canonical_work_items.get(connection, canonical_work_id)
        assert preserved["state"] == "blocked"
        assert preserved["blocked_reason"] == "QA environment hold"
        assert preserved["source_system"] == "linear"
        assert preserved["source_key"] == "CC-56"
    finally:
        connection.close()


def test_start_reuses_canonical_source_identity_and_existing_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    created = create_project_work_item(
        root,
        "acme",
        "app",
        title="Legacy source item",
        summary="Existing packet created by another intake route.",
        status="building",
        work_id="legacy_cc_57",
        item_format="packet",
    )
    packet = next(
        path
        for path in created.created
        if path.is_dir() and path.parent == project / "work-items" / "02-active"
    )
    canonical_work_id = "custom:legacy:cc-57"
    connection = connect_state(default_db_path(root))
    try:
        canonical_work_items.upsert(
            connection,
            item_id=canonical_work_id,
            title="Legacy source item",
            state="ready",
            attention="active",
            domain="acme",
            project="app",
            source_system="linear",
            source_key="CC-57",
            source_url="https://tracker.example/browse/CC-57",
            packet_path=str(packet),
            context_summary="Existing source-bound canonical work item.",
            verified=True,
        )
    finally:
        connection.close()

    _fake_worktree(monkeypatch, "CC-57", base_sha)

    run = delivery.start_development_run(
        root, "acme", "app", ["CC-57"], run_id="source-identity", apply=True
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"])).read()
    assert task["canonical_work_id"] == canonical_work_id
    assert Path(task["work_item"]) == packet
    assert len(list((project / "work-items" / "02-active").iterdir())) == 1

    connection = connect_state(default_db_path(root))
    try:
        matching = [
            row
            for row in canonical_work_items.query(
                connection, domain="acme", project="app", limit=100
            )
            if row.get("source_key") == "CC-57"
        ]
        assert [row["id"] for row in matching] == [canonical_work_id]
        assert matching[0]["source_system"] == "linear"
        assert matching[0]["source_url"] == "https://tracker.example/browse/CC-57"
        assert Path(matching[0]["packet_path"]) == packet
    finally:
        connection.close()


def test_adopt_existing_packet_preserves_canonical_source_and_avoids_duplicate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    created = create_project_work_item(
        root,
        "acme",
        "app",
        title="Legacy filesystem item",
        summary="Pre-vNext packet without Auto-Dev state.",
        status="building",
        work_id="CC-ADOPT",
        item_format="packet",
    )
    packet = next(
        path
        for path in created.created
        if path.is_dir() and path.parent == project / "work-items" / "02-active"
    )
    worktree = project / "worktrees" / "legacy-adopt"
    _git("worktree", "add", "-b", "feature/cc-adopt", str(worktree), "main", cwd=repo)
    register_project_worktree(
        root, "acme", "app", "legacy-adopt", path=worktree
    )
    canonical_work_id = "legacy:filesystem:cc-adopt"
    connection = connect_state(default_db_path(root))
    try:
        canonical_work_items.upsert(
            connection,
            item_id=canonical_work_id,
            title="Legacy filesystem item",
            state="building",
            attention="active",
            domain="acme",
            project="app",
            source_system="filesystem",
            source_key="CC-ADOPT",
            packet_path=str(packet),
            worktree_path=str(worktree),
            branch="feature/cc-adopt",
            context_summary="Existing pre-vNext packet.",
            verified=True,
        )
    finally:
        connection.close()

    assert main(
        [
            "auto-dev",
            "adopt",
            "acme",
            "app",
            "CC-ADOPT",
            "--state",
            str(packet),
            "--run-id",
            "adopt-existing",
            "--title",
            "Legacy filesystem item",
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 0
    capsys.readouterr()
    projection = json.loads((packet / "autodev.json").read_text(encoding="utf-8"))
    task_path = Path(projection["delivery"]["task_state_ref"])
    task = TaskState(task_path).read()
    assert projection["canonical_work_id"] == canonical_work_id
    assert projection["source"]["system"] == "filesystem"
    assert task["canonical_work_id"] == canonical_work_id
    assert Path(task["work_item"]) == packet
    assert task["state"] == "worktree_ready"
    assert Path(task["worktree"]["path"]) == worktree
    assert task["runtime"] == {
        "ownership": "not_managed",
        "provider": "none",
        "identity": "not-managed",
    }
    assert len(list((project / "work-items" / "02-active").iterdir())) == 1


def test_adopt_worktree_mismatch_fails_before_any_state_mutation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    created = create_project_work_item(
        root,
        "acme",
        "app",
        title="Legacy mismatch item",
        summary="Pre-vNext packet whose registered branch must be repaired.",
        status="building",
        work_id="CC-ADOPT-MISMATCH",
        item_format="packet",
    )
    packet = next(
        path
        for path in created.created
        if path.is_dir() and path.parent == project / "work-items" / "02-active"
    )
    worktree = project / "worktrees" / "legacy-adopt-mismatch"
    _git(
        "worktree",
        "add",
        "-b",
        "feature/cc-adopt-mismatch",
        str(worktree),
        "main",
        cwd=repo,
    )
    register_project_worktree(
        root, "acme", "app", "legacy-adopt-mismatch", path=worktree
    )
    canonical_work_id = "legacy:filesystem:cc-adopt-mismatch"
    connection = connect_state(default_db_path(root))
    try:
        canonical_work_items.upsert(
            connection,
            item_id=canonical_work_id,
            title="Legacy mismatch item",
            state="building",
            attention="active",
            domain="acme",
            project="app",
            source_system="filesystem",
            source_key="CC-ADOPT-MISMATCH",
            packet_path=str(packet),
            worktree_path=str(worktree),
            branch="feature/not-the-registered-branch",
            context_summary="Existing pre-vNext packet.",
            verified=True,
        )
        before = canonical_work_items.get(connection, canonical_work_id)
    finally:
        connection.close()

    assert main(
        [
            "auto-dev",
            "adopt",
            "acme",
            "app",
            "CC-ADOPT-MISMATCH",
            "--state",
            str(packet),
            "--run-id",
            "adopt-mismatch",
            "--title",
            "Legacy mismatch item",
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 2
    captured = capsys.readouterr()
    assert "branch does not match canonical registration" in captured.err
    assert not (packet / "autodev.json").exists()
    assert not (packet / "artifacts" / "development-delivery" / "run.json").exists()
    assert not (project / "state" / "development-runs" / "adopt-mismatch").exists()
    connection = connect_state(default_db_path(root))
    try:
        assert canonical_work_items.get(connection, canonical_work_id) == before
    finally:
        connection.close()
    assert len(list((project / "work-items" / "02-active").iterdir())) == 1


def test_health_crash_resume_relinks_finished_packet_without_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    _fake_worktree(monkeypatch, "CC-58", base_sha)
    run = delivery.start_development_run(
        root, "acme", "app", ["CC-58"], run_id="health-crash-resume", apply=True
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"]))
    for state_name in delivery.FORWARD_STATES[
        delivery.FORWARD_STATES.index("worktree_ready") + 1 :
    ]:
        task.transition(
            state_name,
            receipt=f"proof:{state_name}",
            idempotency_key=f"cc-58:{state_name}",
        )
    active_packet = Path(task.read()["work_item"])
    promoted = promote_project_work_item(
        root,
        "acme",
        "app",
        active_packet.name,
        state="finished",
        note="Simulate a crash immediately after the packet move.",
    )
    finished_packet = Path(promoted["path"])
    canonical_work_id = str(task.read()["canonical_work_id"])
    connection = connect_state(default_db_path(root))
    try:
        canonical_work_items.update(
            connection,
            canonical_work_id,
            state="finished",
            attention="closed",
            packet_path=str(finished_packet),
            clear_worktree=True,
            receipt_ref=str(finished_packet / "autodev.json"),
            verified=True,
        )
    finally:
        connection.close()
    packets_before = sorted(
        str(path.resolve())
        for lane in ("02-active", "03-complete")
        for path in (project / "work-items" / lane).iterdir()
    )
    assert Path(task.read()["work_item"]) == active_packet
    assert not active_packet.exists()

    def verify_relinked_health(
        state_file: str | Path, *, apply: bool = False
    ) -> dict[str, object]:
        assert apply is True
        assert Path(state_file).expanduser().resolve() == finished_packet / "autodev.json"
        relinked = task.read()
        assert Path(relinked["work_item"]) == finished_packet
        assert Path(relinked["autodev_path"]) == finished_packet / "autodev.json"
        return {"preflight": {"packet_path": str(finished_packet)}}

    monkeypatch.setattr(auto_dev_cli, "prepare_auto_dev_health", verify_relinked_health)
    assert main(
        [
            "auto-dev",
            "health",
            "--state",
            str(finished_packet / "autodev.json"),
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["preflight"]["packet_path"] == str(
        finished_packet
    )
    packets_after = sorted(
        str(path.resolve())
        for lane in ("02-active", "03-complete")
        for path in (project / "work-items" / lane).iterdir()
    )
    assert packets_after == packets_before
    assert not (project / "work-items" / "02-active" / finished_packet.name).exists()
    connection = connect_state(default_db_path(root))
    try:
        canonical = canonical_work_items.get(connection, canonical_work_id)
        assert canonical["state"] == "finished"
        assert Path(canonical["packet_path"]) == finished_packet
        matching = [
            row
            for row in canonical_work_items.query(
                connection, domain="acme", project="app", limit=100
            )
            if row.get("source_key") == "CC-58"
        ]
        assert [row["id"] for row in matching] == [canonical_work_id]
    finally:
        connection.close()
