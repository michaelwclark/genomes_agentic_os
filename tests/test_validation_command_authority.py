"""Shared matcher rejects selectors and unpinned launcher equivalence."""
from pathlib import Path
import pytest
from genomes_agentic_os.validation_command_authority import execution_argv, matches_command, _isolated_diagnostic

FROZEN = ".venv/bin/python -m pytest tests/ -q --cov=genomes_agentic_os --cov-branch"


def _task(tmp_path):
    return {"worktree": {"path": str(tmp_path / "worktree")},
            "work_item": str(tmp_path / "packet")}


def _actual(task):
    p = Path(task["work_item"]) / "artifacts/v4"
    return ["env", "REVIEW_POLICY_FINGERPRINT=" + "f" * 64,
            str(Path(task["worktree"]["path"]) / ".venv/bin/python"),
            "-m", "pytest", "tests/", "-q", "--cov=genomes_agentic_os", "--cov-branch",
            "--basetemp=" + str(p / "tmp/tests"),
            "-o", "cache_dir=" + str(p / "pytest-cache"),
            "--cov-report=json:" + str(p / "coverage.json")]


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
    prefix = [str(Path(task["worktree"]["path"]) / ".venv/bin/python"), "-m", "pytest", "tests/", "-q",
              "--cov=genomes_agentic_os", "--cov-branch"]
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


@pytest.mark.parametrize("assignment", [
    "PYTHONPATH=/alternate/package", "PYTEST_PLUGINS=alternate.plugin",
    "PYTEST_ADDOPTS=-k one", "PATH=/alternate/bin", "NODE_OPTIONS=--require alternate",
    "LD_PRELOAD=/alternate/code", "npm_config_ignore_scripts=true",
    "COVERAGE_RCFILE=/alternate/coverage.ini",
])
@pytest.mark.parametrize("transport", ["env_prefix", "runner_override"])
def test_execution_affecting_environment_is_rejected_in_both_receipt_transports(tmp_path, assignment, transport):
    task = _task(tmp_path)
    command = {"command": _actual(task)}
    if transport == "env_prefix":
        command["command"].insert(2, assignment)
    else:
        key, value = assignment.split("=", 1)
        command["environment_overrides"] = {key: value}
    assert execution_argv(command, task) == ([], {})


def test_safe_environment_controls_are_bound_to_the_owned_artifacts(tmp_path):
    task = _task(tmp_path)
    artifact = Path(task["work_item"]) / "artifacts/owned"
    command = {"command": _actual(task), "environment_overrides": {
        "PYTEST_ADDOPTS": "", "PYTHONDONTWRITEBYTECODE": "1",
        "COVERAGE_FILE": str(artifact / "coverage-data"),
        "NPM_CONFIG_CACHE": str(artifact / "npm-cache"),
    }}
    argv, environment = execution_argv(command, task)
    assert matches_command(FROZEN, argv, task, {})
    assert environment["REVIEW_POLICY_FINGERPRINT"] == "f" * 64
    command["environment_overrides"]["COVERAGE_FILE"] = "/another/item/coverage-data"
    assert execution_argv(command, task) == ([], {})


@pytest.mark.parametrize("override", [None, [], {"PYTEST_ADDOPTS": False},
    {"PYTHONDONTWRITEBYTECODE": "0"}, {"REVIEW_POLICY_FINGERPRINT": "e" * 64}])
def test_malformed_or_contradictory_environment_never_establishes_authority(tmp_path, override):
    command = {"command": _actual(_task(tmp_path)), "environment_overrides": override}
    assert execution_argv(command, _task(tmp_path)) == ([], {})


def test_env_clear_option_is_not_frozen_execution(tmp_path):
    vector = _actual(_task(tmp_path)); vector.insert(1, "-i")
    assert execution_argv({"command": vector}, _task(tmp_path)) == ([], {})


@pytest.mark.parametrize("extra_floor", ["0", "79", "80", "100", "nan"])
def test_an_appended_coverage_floor_cannot_override_the_frozen_threshold(tmp_path, extra_floor):
    task = _task(tmp_path)
    configured = FROZEN + " --cov=app --cov-fail-under=80"
    actual = [str(Path(task["worktree"]["path"]) / ".venv/bin/python"),
              "-m", "pytest", "tests/", "-q", "--cov=genomes_agentic_os", "--cov-branch",
              "--cov=app", "--cov-fail-under=80"]
    assert matches_command(configured, actual, task, {})
    assert not matches_command(configured, actual + ["--cov-fail-under=" + extra_floor], task, {})


@pytest.mark.parametrize("extra", [["--cov=alternate_package"], ["--cov="], ["--cov-branch"],
    ["--cov-config=alternate.ini"], ["--cov-config", "alternate.ini"], ["--no-cov"],
    ["--cov-reset"], ["--cov-append"]])
def test_coverage_denominator_and_configuration_cannot_be_annotated(tmp_path, extra):
    task = _task(tmp_path)
    actual, _ = execution_argv({"command": _actual(task)})
    assert matches_command(FROZEN, actual, task, {})
    assert not matches_command(FROZEN, actual + extra, task, {})


@pytest.mark.parametrize("code", [
    "import sys; sys.path.insert(0, '.')", "import importlib; importlib.import_module('pytest')",
    "exec('import pytest')", "__import__('pytest')", "import os; os.system('true')",
    "import sys; sys=__import__('os')", "print=eval; print('import pytest')",
    "import os as other; print(other)", "open('pytest.pyc', 'rb')", "import site",
    "print('text', file=open('override', 'w'))", "os.environ['PYTHONPATH']='.'",
])
def test_isolated_diagnostic_cannot_reload_worktree_or_dependency_code(code):
    assert not _isolated_diagnostic(code)


def test_isolated_diagnostic_keeps_bounded_environment_diagnostics():
    assert _isolated_diagnostic("import os,sys; missing=not os.environ.get('FIXTURE_ENDPOINT'); "
                               "print('missing' if missing else 'configured'); sys.exit(17 if missing else 0)")


@pytest.mark.parametrize("location", ["worktree", "packet"])
def test_a_declared_or_self_named_pytest_executable_without_native_qualification_stays_untrusted(tmp_path, location):
    from genomes_agentic_os.validation_command_authority import runtime_provenance_check
    task = _task(tmp_path)
    root = Path(task["worktree"]["path"] if location == "worktree" else task["work_item"])
    executable = root / "artifacts/python/bin/python"
    selected = {"schema": "development-selected-profile/v2", "validation": {
        "command_executables": {FROZEN: {"executable": str(executable), "authority": "selected_profile"}}}}
    argv = [str(executable), "-m", "pytest", "tests/", "-q", "--cov=genomes_agentic_os", "--cov-branch"]
    assert matches_command(FROZEN, argv, task, selected)
    with pytest.raises(ValueError, match="independently declared dependency provenance"):
        runtime_provenance_check(FROZEN, argv, task, selected)


def _app_authority(tmp_path, command="npx --no-install eslint --version"):
    """Only local package-provenance units; native admission is tested separately."""
    from test_validation_node_provenance import _app_guard_context
    _, _, worktree, _, contract = _app_guard_context(tmp_path)
    task = {"worktree": {"path": str(worktree)}, "work_item": str(tmp_path / "packet")}
    selected = {"validation": {"commands": ["npm ci", command], "node_tool_contract": contract}}
    return task, selected, worktree


@pytest.mark.parametrize("command", ["npm ci", "npx --no-install eslint --version",
    "npx --no-install prettier --version", "npx --no-install tsc --noEmit"])
def test_explicit_app_node_authority_requires_frozen_locally_bound_tools(tmp_path, command):
    import shlex
    from genomes_agentic_os.validation_command_authority import runtime_provenance_check
    task, selected, worktree = _app_authority(tmp_path, command)
    assert not (worktree / "node_modules/.bin/playwright").exists()
    assert runtime_provenance_check(command, shlex.split(command), task, selected) is None


@pytest.mark.parametrize("command", ["npx eslint --version", "npx --no-install unknown --version",
    "npx --package=eslint --no-install eslint --version", "npx --prefix /outside --no-install eslint",
    "npx --no-install eslint --package=unqualified", "npx --no-install eslint --prefix=/outside",
    "npx --no-install eslint -p unqualified", "npx --yes eslint --version", "npm exec -- eslint --version",
    "npm ci --ignore-scripts", "node arbitrary.js"])
def test_even_frozen_app_commands_cannot_install_or_select_unknown_execution(tmp_path, command):
    import shlex
    from genomes_agentic_os.validation_command_authority import runtime_provenance_check
    task, selected, _ = _app_authority(tmp_path, command)
    with pytest.raises(ValueError):
        runtime_provenance_check(command, shlex.split(command), task, selected)


@pytest.mark.parametrize("mutation", ["unfrozen", "argv", "missing-required", "wrong-owner", "unknown-selector", "null"])
def test_app_node_authority_cannot_infer_or_broaden_the_selected_contract(tmp_path, mutation):
    import json
    import shlex
    from genomes_agentic_os.validation_command_authority import runtime_provenance_check
    command = "npx --no-install eslint --version"
    task, selected, worktree = _app_authority(tmp_path, command)
    actual = shlex.split(command)
    if mutation == "unfrozen":
        selected["validation"]["commands"].remove(command)
    elif mutation == "argv":
        actual.append("--quiet")
    elif mutation == "missing-required":
        (worktree / "node_modules/.bin/prettier").unlink()
    elif mutation == "wrong-owner":
        path = worktree / "node_modules/eslint/package.json"
        metadata = json.loads(path.read_text()); metadata["name"] = "other"
        path.write_text(json.dumps(metadata))
    elif mutation == "unknown-selector":
        selected["validation"]["node_tool_contract"]["profile"] = "skip_missing"
    else:
        selected["validation"]["node_tool_contract"] = None
    with pytest.raises((ValueError, OSError)):
        runtime_provenance_check(command, actual, task, selected)


@pytest.mark.parametrize("command", ["npm ci", "npx tsc --noEmit", "npx playwright test --list"])
def test_generic_node_authority_keeps_its_original_exact_whitelist(tmp_path, command):
    import shlex
    from genomes_agentic_os.validation_command_authority import runtime_provenance_check
    assert runtime_provenance_check(command, shlex.split(command), _task(tmp_path), {"validation": {}}) is None


def test_app_tools_do_not_implicitly_extend_generic_node_authority(tmp_path):
    from genomes_agentic_os.validation_command_authority import runtime_provenance_check
    with pytest.raises(ValueError):
        runtime_provenance_check("npx --no-install eslint --version",
            ["npx", "--no-install", "eslint", "--version"], _task(tmp_path), {"validation": {}})
