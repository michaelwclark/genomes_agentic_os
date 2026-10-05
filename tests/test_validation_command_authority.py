"""Shared matcher rejects selectors and unpinned launcher equivalence."""
from pathlib import Path
import pytest
from genomes_agentic_os.validation_command_authority import execution_argv, matches_command

FROZEN = ".venv/bin/python -m pytest tests/ -q"


def _task(tmp_path):
    return {"worktree": {"path": str(tmp_path / "worktree")},
            "work_item": str(tmp_path / "packet")}


def _actual(task):
    p = Path(task["work_item"]) / "artifacts/v4"
    return ["env", "REVIEW_POLICY_FINGERPRINT=" + "f" * 64,
            str(Path(task["worktree"]["path"]) / ".venv/bin/python"),
            "-m", "pytest", "tests/", "-q", "--basetemp=" + str(p / "tmp/tests"),
            "-o", "cache_dir=" + str(p / "pytest-cache"),
            "--cov=genomes_agentic_os", "--cov-branch", "--cov-report=json:" + str(p / "coverage.json")]


def test_actual_age233_v4_annotated_vector_matches_without_receipt_changes(tmp_path):
    task = _task(tmp_path)
    command = {"command": _actual(task)}
    before = list(command["command"])
    actual, env = execution_argv(command)
    assert env["REVIEW_POLICY_FINGERPRINT"] == "f" * 64
    assert matches_command(FROZEN, actual, task, {"validation": {}})
    assert command["command"] == before


@pytest.mark.parametrize("extra", [
    ["-k", "small"], ["-m", "unit"], ["tests/test_one.py"], ["--ignore=tests"],
    ["--deselect=test_name"], ["--lf"], ["-o", "addopts=-k small"],
    ["-o", "python_files=none"], ["--override-ini=cache_dir=/tmp"],
    ["-o"], ["-o", "cache_dir=/private/other-lane"],
    ["--basetemp=/private/other-lane"], ["--cov-report=json:/private/other-lane/report.json"],
    ["--cov=../../other"], ["--cov-report=unknown"], ["--cov-fail-under=nan"],
    ["-o", "cache_dir=relative-cache"],
])
def test_only_contained_nonselecting_annotations_are_admitted(tmp_path, extra):
    task = _task(tmp_path)
    actual, _ = execution_argv({"command": _actual(task)})
    assert not matches_command(FROZEN, actual + extra, task, {"validation": {}})


@pytest.mark.parametrize("executable", ["python", "/usr/bin/python3",
    "/another/worktree/.venv/bin/python"])
def test_no_system_version_or_cross_worktree_interpreter_inference(tmp_path, executable):
    task = _task(tmp_path)
    actual, _ = execution_argv({"command": _actual(task)})
    actual[0] = executable
    assert not matches_command(FROZEN, actual, task, {"validation": {}})


def test_explicit_v2_executable_authority_is_preserved(tmp_path):
    task = _task(tmp_path)
    actual, _ = execution_argv({"command": _actual(task)})
    mapped = Path(task["work_item"]) / "artifacts/test-runtime314/bin/python"
    actual[0] = str(mapped)
    selected = {"schema": "development-selected-profile/v2", "validation": {
        "command_executables": {FROZEN: {"executable": "{work_item}/artifacts/test-runtime314/bin/python",
                                      "authority": "selected_profile"}}}}
    assert matches_command(FROZEN, actual, task, selected)
    selected["schema"] = "development-selected-profile/v1"
    assert not matches_command(FROZEN, actual, task, selected)
    selected["schema"] = "development-selected-profile/v2"
    selected["validation"]["command_executables"][FROZEN]["authority"] = "inferred_version"
    assert not matches_command(FROZEN, actual, task, selected)
    selected["validation"]["command_executables"][FROZEN] = {
        "executable": "/usr/bin/python3", "authority": "selected_profile"}
    actual[0] = "/usr/bin/python3"
    assert not matches_command(FROZEN, actual, task, selected)


def test_symlink_output_escape_and_root_replacement_are_rejected(tmp_path):
    task = _task(tmp_path)
    packet = Path(task["work_item"]); packet.mkdir()
    outside = tmp_path / "other-lane"; outside.mkdir()
    (packet / "escaped").symlink_to(outside, target_is_directory=True)
    prefix = [str(Path(task["worktree"]["path"]) / ".venv/bin/python"), "-m", "pytest", "tests/", "-q"]
    assert not matches_command(FROZEN, prefix + ["-o", "cache_dir=" + str(packet / "escaped/cache")], task, {})
    assert not matches_command(FROZEN, prefix + ["--basetemp=" + str(packet)], task, {})
    assert not matches_command(FROZEN, prefix + ["-o", "cache_dir=" + task["worktree"]["path"] + "/cache"], task, {})


def test_explicit_env_binding_rejects_duplicate_fingerprint_or_hidden_pytest_options(tmp_path):
    task = _task(tmp_path)
    vector = _actual(task)
    vector.insert(2, "REVIEW_POLICY_FINGERPRINT=" + "e" * 64)
    assert execution_argv({"command": vector}) == ([], {})
    vector = _actual(task); vector.insert(2, "PYTEST_ADDOPTS=-k small")
    assert execution_argv({"command": vector}) == ([], {})


def test_annotations_do_not_apply_to_arbitrary_commands(tmp_path):
    task = _task(tmp_path)
    assert not matches_command("python -c pass", ["python", "-c", "pass", "--cov=app"], task, {})
