"""Safety tests for the Docker/OrbStack reclaim planner.

The interesting cases are all about *not* deleting things. Each test below
corresponds to a way a naive implementation destroys real state.
"""

from __future__ import annotations

import json

import pytest

from genomes_agentic_os.docker_reclaim import (
    BUILTIN_NETWORKS,
    DEFAULT_SCOPES,
    Decision,
    DockerClient,
    ReclaimPlan,
    Resource,
    apply_plan,
    build_plan,
    classify,
    default_worktree_roots,
    discover_worktree_dirs,
    normalise,
    write_receipt,
)


def net(name, attached=0):
    return Resource("network", name, attached_containers=attached)


def vol(name, attached=0):
    return Resource("volume", name, attached_containers=attached)


def decide(resources, live=None, protected=()):
    return {d.resource.name: d for d in classify(resources, live or {}, protected)}


class TestSafetyPredicates:
    def test_stopped_worktree_volume_is_never_deleted(self):
        """The data-loss case: stack stopped, worktree still checked out.

        Docker calls this volume dangling. Deleting it destroys a dev database
        for work that has not merged.
        """
        live = {"072226flywl1906documentationvalidationepic": "072226-flywl-1906-documentation-validation-epic"}
        resources = [vol("072226-flywl-1906-documentation-validation-epic_local_postgres_data", attached=0)]

        decision = decide(resources, live)[resources[0].name]

        assert decision.action == "keep"
        assert decision.reason == "owning worktree still on disk"
        assert decision.owner == "072226-flywl-1906-documentation-validation-epic"

    def test_orphan_volume_from_deleted_worktree_is_reclaimed(self):
        resources = [vol("071826-flywl-1209-pytest_local_postgres_data", attached=0)]

        decision = decide(resources, {"072226flywl1906": "072226-flywl-1906"})[resources[0].name]

        assert decision.action == "reclaim"

    def test_attached_resource_is_kept_even_without_a_worktree(self):
        """Belt and braces: the two predicates are independent on purpose."""
        resources = [net("los-infra_network", attached=17), vol("conf_postgres_data", attached=1)]

        decisions = decide(resources, {})

        assert all(d.action == "keep" for d in decisions.values())
        assert decisions["los-infra_network"].reason == "in use by a container"

    @pytest.mark.parametrize("name", sorted(BUILTIN_NETWORKS))
    def test_builtin_networks_are_never_touched(self, name):
        decision = decide([net(name, attached=0)], {})[name]

        assert decision.action == "keep"
        assert decision.reason == "docker builtin network"

    def test_explicit_protection_wins_over_reclaimable(self):
        decision = decide([vol("precious_data")], {}, protected={"precious_data"})["precious_data"]

        assert decision.action == "keep"
        assert decision.reason == "explicitly protected"

    def test_truncated_compose_name_still_matches_its_worktree(self):
        """Compose truncates long project names; a truncated name must still match."""
        full = "072926-git-github-com-thesummitgrp-los-app-los-django-flywl-3250-sso-managed-us"
        live = {normalise(full): full}

        decision = decide([net("los-072926-git-github-com-thesummitgrp-los-a_default")], live)
        only = next(iter(decision.values()))

        assert only.action == "keep"
        assert only.owner == full

    def test_case_and_separator_differences_do_not_defeat_matching(self):
        live = {normalise("061126-FLYWL-973-remove-epc-oc-question"): "061126-FLYWL-973-remove-epc-oc-question"}

        decision = decide([vol("061126-flywl-973-remove-epc-oc-question_listmonk_data")], live)

        assert next(iter(decision.values())).action == "keep"


class TestWorktreeDiscovery:
    def test_discovers_directories_and_skips_files_and_hidden(self, tmp_path):
        root = tmp_path / "worktrees"
        root.mkdir()
        (root / "072126-rct").mkdir()
        (root / "FLYWL-99-Thing").mkdir()
        (root / ".DS_Store").touch()
        (root / "index.yml").touch()
        (root / ".hidden").mkdir()

        tokens = discover_worktree_dirs([root])

        assert tokens == {"072126rct": "072126-rct", "flywl99thing": "FLYWL-99-Thing"}

    def test_missing_root_is_skipped_not_fatal(self, tmp_path):
        assert discover_worktree_dirs([tmp_path / "nope"]) == {}

    def test_default_roots_cover_os_and_plain_project_checkouts(self, tmp_path):
        os_root = tmp_path / "agentic_os"
        managed = os_root / "domains" / "los" / "02-projects" / "app" / "worktrees"
        managed.mkdir(parents=True)
        projects = tmp_path / "projects"
        (projects / "kanga" / "worktrees").mkdir(parents=True)

        roots = default_worktree_roots(os_root, projects)

        assert managed in roots
        assert projects / "kanga" / "worktrees" in roots

    def test_no_worktree_roots_means_nothing_is_protected_by_name(self, tmp_path):
        """Guards against a silent bug where discovery breaking looks like success."""
        tokens = discover_worktree_dirs([tmp_path / "missing"])
        decision = decide([vol("some-project_data")], tokens)["some-project_data"]

        # Still reclaimable -- but only because it is also unattached.
        assert decision.action == "reclaim"


class FakeDocker(DockerClient):
    def __init__(self, networks=(), volumes=(), refuse=()):
        super().__init__(binary="fake-docker")
        self._networks = list(networks)
        self._volumes = list(volumes)
        self._refuse = set(refuse)
        self.removed: list[str] = []

    def available(self):
        return True

    def networks(self):
        return list(self._networks)

    def volumes(self):
        return list(self._volumes)

    def remove(self, resource):
        if resource.name in self._refuse:
            return False, "volume is in use"
        self.removed.append(resource.name)
        return True, "removed"


class TestPlanAndApply:
    def test_plan_separates_reclaimable_from_kept(self):
        client = FakeDocker(
            networks=[net("bridge"), net("los-infra_network", attached=17), net("dead-wt_default")],
            volumes=[vol("dead-wt_data"), vol("live-wt_data")],
        )
        live = {"livewt": "live-wt"}

        plan = build_plan(client, live)

        assert {d.resource.name for d in plan.reclaimable} == {"dead-wt_default", "dead-wt_data"}
        assert {d.resource.name for d in plan.kept} == {"bridge", "los-infra_network", "live-wt_data"}

    def test_scopes_limit_what_is_collected(self):
        client = FakeDocker(networks=[net("dead_default")], volumes=[vol("dead_data")])

        assert {d.resource.kind for d in build_plan(client, {}, scopes=("networks",)).decisions} == {"network"}
        assert {d.resource.kind for d in build_plan(client, {}, scopes=("volumes",)).decisions} == {"volume"}

    def test_images_and_cache_are_not_default_scopes(self):
        assert DEFAULT_SCOPES == ("networks", "volumes")

    def test_apply_removes_only_reclaimable(self):
        client = FakeDocker(
            networks=[net("los-infra_network", attached=17), net("dead_default")],
            volumes=[vol("live_data"), vol("dead_data")],
        )
        plan = apply_plan(client, build_plan(client, {"live": "live"}))

        assert sorted(client.removed) == ["dead_data", "dead_default"]
        assert plan.applied is True

    def test_removal_refused_downgrades_to_keep_and_records_error(self):
        """A resource that became busy mid-run must not be reported as deleted."""
        client = FakeDocker(volumes=[vol("busy_data")], refuse={"busy_data"})

        plan = apply_plan(client, build_plan(client, {}, scopes=("volumes",)))

        assert client.removed == []
        assert plan.reclaimable == []
        assert "volume is in use" in plan.errors[0]
        assert plan.kept[0].reason.startswith("removal refused")


class TestReceipt:
    def test_report_mode_receipt_shape(self):
        plan = ReclaimPlan(scopes=DEFAULT_SCOPES, live_tokens={"a": "a"})
        plan.decisions = [
            Decision(net("dead_default"), "reclaim", "no owning worktree on disk and unused"),
            Decision(net("los-infra_network", 17), "keep", "in use by a container"),
        ]

        receipt = plan.as_receipt("2026-07-30T08:00:00Z")

        assert receipt["api_version"] == "host-health-docker-reclaim/v1"
        assert receipt["mode"] == "report"
        assert receipt["summary"] == {
            "reclaimable": 1,
            "kept": 1,
            "reclaimable_by_kind": {"network": 1},
        }
        assert receipt["protected_worktrees"] == 1

    def test_receipt_records_owner_for_kept_resources(self):
        plan = ReclaimPlan()
        plan.decisions = [Decision(vol("wt_data"), "keep", "owning worktree still on disk", "wt")]

        assert plan.as_receipt("2026-07-30T08:00:00Z")["decisions"][0]["owner_worktree"] == "wt"

    def test_write_receipt_is_valid_json_on_disk(self, tmp_path):
        plan = ReclaimPlan()
        plan.decisions = [Decision(net("dead_default"), "reclaim", "unused")]
        receipt = plan.as_receipt("2026-07-30T08:00:00Z")

        path = write_receipt(tmp_path, receipt)

        assert path.parent == tmp_path / "harness" / "shared_factory" / "06-runs-and-logs" / "docker-reclaim"
        assert json.loads(path.read_text())["decisions"][0]["name"] == "dead_default"

    def test_apply_and_report_receipts_do_not_collide(self, tmp_path):
        plan = ReclaimPlan()
        report = write_receipt(tmp_path, plan.as_receipt("2026-07-30T08:00:00Z"))
        plan.applied = True
        applied = write_receipt(tmp_path, plan.as_receipt("2026-07-30T08:00:00Z"))

        assert report != applied
