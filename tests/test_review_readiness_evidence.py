from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from genomes_agentic_os import development_delivery as delivery
from genomes_agentic_os import review_readiness_evidence as proof
from genomes_agentic_os.cli import main
from genomes_agentic_os.cli.develop import handle_readiness_proof
from test_development_delivery import _project, _repository, _stage_receipt

HEAD = 'a' * 40
BASE = 'b' * 40
NOW = datetime(2026, 10, 5, 20, 0, tzinfo=timezone.utc)
COMMAND = '.venv/bin/python -m pytest tests/ -q'
CHECKS = [{'context': 'Python suite and packaging', 'app_id': 15368}, {'context': 'secret-scan', 'app_id': 15368}]


def contract():
    return {'schema': 'github-required-check-contract/v1', 'provider': 'github',
            'repository': 'acme/app', 'base_branch': 'main', 'checks': deepcopy(CHECKS),
            'drift_policy': 'block_until_context_refresh',
            'source': {'url': 'https://api.github.com/repos/acme/app/branches/main/protection',
                       'captured_at': NOW.isoformat(), 'rules_complete': True, 'active_rules': [], 'route':'composio:GITHUB_GET_BRANCH_PROTECTION',
                       'required_checks': deepcopy(CHECKS), 'readback_sha256': 'c' * 64}}


@pytest.fixture(scope='module')
def generated_policy(tmp_path_factory):
    root = tmp_path_factory.mktemp('real-policy') / 'os'
    repo, _ = _repository(root.parent)
    project = _project(root, repo)
    path = project / 'config/development.yml'
    profile = yaml.safe_load(path.read_text())
    profile['validation'].update(commands=[COMMAND], required_checks=[r['context'] for r in CHECKS], ci_contract=contract())
    profile['review']['copilot'] = {'required': True}
    path.write_text(yaml.safe_dump(profile))
    value = delivery.resolve_development_policies(root, 'acme', 'app', include_body=True)
    return value, path


@pytest.fixture
def context(tmp_path, generated_policy):
    snapshot, source = generated_policy
    snapshot = deepcopy(snapshot)
    packet = tmp_path / 'packet'
    packet.mkdir()
    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    pinned = packet / 'policy.json'
    pinned.write_text(json.dumps(snapshot))
    state = packet / 'state.json'
    task = {'schema':'development-task/v1','canonical_work_id':'acme:app:CC-PROOF','run_id':'offline-proof','work_item': str(packet), 'policy_receipt': str(pinned), 'policy_fingerprint': snapshot['fingerprint'],
            'repository': {'id': 'github:acme/app'}, 'worktree': {'path': str(worktree), 'base_sha': BASE, 'branch': 'feature/CC-PROOF'}, 'receipts': []}
    state.write_text(json.dumps(task))
    (packet / 'autodev.json').write_text(json.dumps({'schema':'auto-dev-work-item/v1','canonical_work_id':'acme:app:CC-PROOF','delivery': {'canonical_work_id':'acme:app:CC-PROOF','run_id':'offline-proof','work_item':str(packet),'task_state_ref': str(state),
           'policy_receipt': str(pinned), 'policy_fingerprint': snapshot['fingerprint']}}))
    return SimpleNamespace(packet=packet, task=task, selected=snapshot['selected_profile'], policy=snapshot['fingerprint'],
                           state=state, pinned=pinned, snapshot=snapshot, source=source, worktree=worktree)


def ref(context, name, value):
    path = context.packet / (name + '.json')
    path.write_text(json.dumps(value))
    return {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def stage(context, *, terminal_changes=None, command_changes=None, stage_changes=None, argv=None):
    identity = {'head': HEAD, 'clean': 'true', 'repository': 'git@github.com:acme/app.git', 'branch': context.task['worktree']['branch']}
    terminal = {'schema': 'agentic-os-long-running-terminal/v1', 'id': 'full-gate', 'status': 'success', 'exit_code': 0,
                'finished_at': NOW.isoformat(), 'git_identity_pre': deepcopy(identity), 'git_identity_post': deepcopy(identity),
                'post_run_invariants_ok': True, 'expected_git_identity': {'worktree': str(context.worktree)}}
    terminal.update(terminal_changes or {})
    command = {'id': 'full-gate', 'work_dir': str(context.worktree), 'expected_git_identity': {'worktree':str(context.worktree)},
               'command': ['env', '-i', 'REVIEW_POLICY_FINGERPRINT='+context.policy, *(argv or [str(context.worktree / '.venv/bin/python'), '-m', 'pytest', 'tests/', '-q',
                                   '--cov=genomes_agentic_os', '--cov-branch', '--basetemp=/task/pytest'])]}
    command.update(command_changes or {})
    row = {'command': COMMAND, 'terminal': ref(context, 'terminal', terminal), 'command_receipt': ref(context, 'command', command)}
    value = {'schema': 'development-stage-evidence/v1', 'state': 'local_validation', 'status': 'passed',
             'verified_at': NOW.isoformat(), 'evidence': {'head_sha': HEAD, 'policy_fingerprint': context.policy, 'validation_runs': [row]}}
    value.update(stage_changes or {})
    context.task['receipts'] = [{'state': 'local_validation', **ref(context, 'stage', value)}]
    context.state.write_text(json.dumps(context.task))
    return value


def provider():
    subject = {'head_sha': HEAD, 'base_sha': BASE, 'base_branch': 'main', 'state': 'OPEN'}
    return {'schema': 'github-review-gate-readback/v1', 'captured_at': NOW.isoformat(), 'repository': 'acme/app', 'pr_number': 42,
            'before': deepcopy(subject), 'after': deepcopy(subject), 'rules_complete': True, 'active_rules': [],
            'required_checks': deepcopy(CHECKS), 'checks_complete': True,
            'checks': [{'name': r['context'], 'app_id': r['app_id'], 'head_sha': HEAD, 'status': 'completed', 'conclusion': 'success'} for r in CHECKS],
            'reviews_complete': True, 'threads_complete': True, 'threads': [],
            'reviews': [{'login': 'copilot-pull-request-reviewer[bot]', 'head_sha': HEAD, 'state': 'COMMENTED', 'submitted_at': NOW.isoformat()}]}


def project_gates(context, live=None):
    return proof.gate_projection(context.selected, live if live is not None else provider(), HEAD, BASE, 'acme/app', 42, context.policy, NOW)


def test_real_policy_capture_freezes_contract_and_explicit_review(context):
    selected = delivery._validate_effective_policy_snapshot(context.snapshot, require_selected_profile=True)
    assert selected['schema'] == 'development-selected-profile/v2'
    assert selected['review']['copilot']['required'] is True
    assert selected['validation']['ci_contract']['checks'] == CHECKS
    assert selected['repository'] == {'id': 'github:acme/app', 'base_branch': 'main'}
    assert selected['provenance']['source_sha256'] == hashlib.sha256(context.source.read_bytes()).hexdigest()
    before = context.pinned.read_bytes()
    mutable = yaml.safe_load(context.source.read_text())
    mutable['review']['copilot']['required'] = False
    assert proof._context(context.state, HEAD, context.policy)[2]['review']['copilot']['required'] is True
    assert context.pinned.read_bytes() == before


@pytest.mark.parametrize('field', ['review', 'repository', 'provenance', 'validation'])
def test_v2_integrity_rejects_changed_policy(context, field):
    context.snapshot['selected_profile'][field] = {}
    with pytest.raises(delivery.DevelopmentDeliveryError):
        delivery._validate_effective_policy_snapshot(context.snapshot, require_selected_profile=True)


def test_legacy_selected_profile_remains_valid_immutable_and_unknown(context):
    selected = context.snapshot['selected_profile']
    legacy = {k: deepcopy(selected[k]) for k in ('repository_id', 'validation')}
    legacy['schema'] = 'development-selected-profile/v1'
    legacy['sha256'] = delivery._json_sha256(legacy)
    context.snapshot['selected_profile'] = legacy
    context.snapshot['fingerprint'] = delivery._effective_policy_snapshot_fingerprint(context.snapshot)
    before = json.dumps(context.snapshot, sort_keys=True)
    assert delivery._validate_effective_policy_snapshot(context.snapshot, require_selected_profile=True) == legacy
    ci, copilot = proof.gate_projection(legacy, provider(), HEAD, BASE, 'acme/app', 42, context.snapshot['fingerprint'], NOW)
    assert ci['status'] == copilot['status'] == 'unknown'
    assert json.dumps(context.snapshot, sort_keys=True) == before


def test_actual_full_gate_receipts_and_content_bound_emission(context):
    stage(context)
    result = proof.emit_readiness_evidence(context.state, head=HEAD, policy=context.policy, provider=provider(), now=NOW)
    assert all(result['readiness_evidence_verified'].values())
    envelope = json.loads(Path(result['envelope']).read_text())
    for key in ('validation', 'ci', 'copilot', 'provider'):
        assert proof._bound(context.packet, envelope[key])
    previous = {p: p.read_bytes() for p in (context.packet / 'artifacts/finishing-touches/proofs').glob('*')}
    live = provider(); live['reviews'] = []
    second = proof.emit_readiness_evidence(context.state, head=HEAD, policy=context.policy, provider=live, now=NOW)
    assert second['copilot_status'] == 'unknown'
    assert all(p.read_bytes() == data for p, data in previous.items())


@pytest.mark.parametrize('mapping', [False, True])
def test_task_owned_python314_command_requires_pinned_mapping(context, mapping):
    actual = str(context.packet / 'artifacts/test-runtime314/bin/python')
    if mapping:
        context.selected['validation']['command_executables'] = {COMMAND: {'executable': '{work_item}/artifacts/test-runtime314/bin/python', 'authority': 'selected_profile'}}
    stage(context, argv=[actual, '-m', 'pytest', 'tests/', '-q', '--cov=genomes_agentic_os', '--cov-branch', '--basetemp=/task/pytest'])
    assert proof.validation_proof(context.packet, context.task, context.selected, HEAD, context.policy, NOW)['status'] == ('passed' if mapping else 'unknown')


@pytest.mark.parametrize('change', [
    {'exit_code': 2, 'status': 'failure'}, {'exit_code': 0, 'status': 'failure'}, {'exit_code': True},
    {'status': 'running'}, {'schema': 'other'}, {'finished_at': 'bad'}, {'finished_at': (NOW + timedelta(seconds=1)).isoformat()},
    {'post_run_invariants_ok': False}, {'git_identity_pre': {'head': BASE, 'clean': 'true', 'repository': 'github:acme/app'}},
    {'git_identity_post': {'head': HEAD, 'clean': 'false', 'repository': 'github:acme/app'}},
    {'git_identity_post': {'head': HEAD, 'clean': 'true', 'repository': 'github:other/app'}}, {'id': 'different'},
])
def test_validation_terminal_failure_stale_or_missing(context, change):
    stage(context, terminal_changes=change)
    result = proof.validation_proof(context.packet, context.task, context.selected, HEAD, context.policy, NOW)
    assert result['status'] == ('failed' if change == {'exit_code': 2, 'status': 'failure'} else 'unknown')


@pytest.mark.parametrize('change', [{'work_dir': '/other'}, {'command': ['python', '-m', 'pytest', 'tests/', '-q']},
     {'command': [COMMAND]}, {'command':['env','REVIEW_POLICY_FINGERPRINT='+'f'*64,'python','-m','pytest','tests/','-q']}, {'command': None}])
def test_validation_wrong_command_or_policy(context, change):
    stage(context, command_changes=change)
    assert proof.validation_proof(context.packet, context.task, context.selected, HEAD, context.policy, NOW)['status'] == 'unknown'


@pytest.mark.parametrize('extra', [['-k', 'focused'], ['tests/test_small.py'], ['--ignore=tests/unit'], ['--maxfail=1']])
def test_focused_or_shortened_tests_cannot_pass_full_gate(context, extra):
    stage(context, argv=[str(context.worktree / '.venv/bin/python'), '-m', 'pytest', 'tests/', '-q', *extra])
    assert proof.validation_proof(context.packet, context.task, context.selected, HEAD, context.policy, NOW)['status'] == 'unknown'


@pytest.mark.parametrize('change', [{'status': 'deferred_to_ci'}, {'status': 'verified'}, {'state': 'implementing'},
    {'evidence': {'head_sha': BASE}}, {'evidence': []}, {'verified_at': 'invalid'}, {'schema': 'other'}])
def test_stage_absence_or_stale_binding_does_not_pass(context, change):
    stage(context, stage_changes=change)
    assert proof.validation_proof(context.packet, context.task, context.selected, HEAD, context.policy, NOW)['status'] == 'unknown'


def test_required_command_absent_or_immutable_refs_changed(context):
    assert proof.validation_proof(context.packet, context.task, context.selected, HEAD, context.policy, NOW)['status'] == 'unknown'
    stage(context)
    context.selected['validation']['commands'].append('other gate')
    assert proof.validation_proof(context.packet, context.task, context.selected, HEAD, context.policy, NOW)['status'] == 'unknown'
    (context.packet / 'terminal.json').write_text('{}')
    assert proof.validation_proof(context.packet, context.task, context.selected, HEAD, context.policy, NOW)['status'] == 'unknown'
    context.selected['validation']['commands'] = []
    assert proof.validation_proof(context.packet, context.task, context.selected, HEAD, context.policy, NOW)['status'] == 'unknown'


@pytest.mark.parametrize('field,value', [('repository', 'other/app'), ('pr_number', 9), ('schema', 'other'),
    ('captured_at', (NOW - timedelta(seconds=301)).isoformat()), ('captured_at', (NOW + timedelta(seconds=1)).isoformat()),
    ('required_checks', []), ('required_checks', CHECKS[:1]), ('required_checks', CHECKS + [{'context': 'new required gate', 'app_id': 15368}]),
    ('checks_complete', False), ('rules_complete', False), ('active_rules', [{'type': 'required_status_checks'}]), ('checks', []),
])
def test_provider_subject_and_required_contract_drift(context, field, value):
    live = provider(); live[field] = value
    assert project_gates(context, live)[0]['status'] == 'unknown'


@pytest.mark.parametrize('where,field,value', [('after','base_sha',HEAD), ('after','head_sha',BASE), ('after','base_branch','dev'),
     ('after','state','CLOSED'), ('before','base_sha',HEAD), ('before','head_sha',BASE)])
def test_capture_brackets_both_revisions(context, where, field, value):
    live = provider(); live[where][field] = value
    assert project_gates(context, live)[0]['status'] == 'unknown'


@pytest.mark.parametrize('field,value', [('repository','other/app'), ('base_branch','dev'), ('provider','other'), ('schema','other'),
    ('drift_policy','ignore'), ('source',{}), ('checks',[]), ('checks',[{'context':'Python suite and packaging','app_id':7}])])
def test_contract_authority_provenance_and_target(context, field, value):
    context.selected['validation']['ci_contract'][field] = value
    assert project_gates(context)[0]['status'] == 'unknown'


@pytest.mark.parametrize('field,value', [('url','https://example.com'), ('captured_at','bad'), ('rules_complete',False),
     ('readback_sha256','bad'), ('required_checks',CHECKS[:1]), ('active_rules',[{}])])
def test_contract_source_evidence(context, field, value):
    context.selected['validation']['ci_contract']['source'][field] = value
    assert project_gates(context)[0]['status'] == 'unknown'


@pytest.mark.parametrize('field,value,expected', [('app_id',7,'unknown'), ('head_sha',BASE,'unknown'),
     ('conclusion','failure','failed'), ('conclusion','cancelled','failed'), ('conclusion','skipped','pending'),
     ('conclusion',None,'pending'), ('status','in_progress','pending')])
def test_exact_required_check_results(context, field, value, expected):
    live = provider(); live['checks'][0][field] = value
    assert project_gates(context, live)[0]['status'] == expected


@pytest.mark.parametrize('field,value', [('reviews',[]), ('reviews_complete',False), ('threads_complete',False), ('threads',[{}])])
def test_zero_threads_cannot_invent_review_delivery(context, field, value):
    live = provider(); live[field] = value
    assert project_gates(context, live)[1]['status'] == 'unknown'


@pytest.mark.parametrize('field,value', [('login','person'), ('head_sha',BASE), ('state','PENDING'), ('submitted_at',None), ('submitted_at','bad')])
def test_delivered_review_is_exact_current_head(context, field, value):
    live = provider(); live['reviews'][0][field] = value
    assert project_gates(context, live)[1]['status'] == 'unknown'


@pytest.mark.parametrize('resolved,outdated,expected', [(False,False,'unresolved'), (True,False,'resolved'), (False,True,'resolved')])
def test_complete_threads_resolution(context, resolved, outdated, expected):
    live = provider(); live['threads'] = [{'isResolved': resolved, 'isOutdated': outdated}]
    assert project_gates(context, live)[1]['status'] == expected


def test_changes_requested_and_explicit_pinned_exemption(context):
    live = provider(); live['reviews'][0]['state'] = 'CHANGES_REQUESTED'
    assert project_gates(context, live)[1]['status'] == 'unresolved'
    context.selected['review']['copilot']['required'] = False
    assert project_gates(context, live)[1]['status'] == 'not_applicable'
    context.selected['review']['copilot'] = {}
    assert project_gates(context, live)[1]['status'] == 'unknown'
    context.selected['review'] = []
    assert project_gates(context, live)[1]['status'] == 'unknown'


def github_fetch(*, extra_required=False, paginated=False, malformed=None):
    calls = []
    def fetch(args):
        calls.append(args)
        route = args[0]
        if route.endswith('/pulls/42'):
            return {'head': {'sha': HEAD}, 'base': {'sha': BASE, 'ref': 'main'}, 'state': 'open'}
        if route.endswith('/protection'):
            return {'required_status_checks': {'checks': CHECKS + ([{'context':'added','app_id':15368}] if extra_required else [])}}
        if '/rules/branches/' in route:
            return []
        if '/check-runs?' in route:
            return {'check_runs': [{'name':r['context'],'app':{'id':r['app_id']},'head_sha':HEAD,'status':'completed','conclusion':'success'} for r in CHECKS]}
        if '/statuses?' in route:
            return [{'context':'unrequired status','state':'success'}, {'context':'unrequired status','state':'failure'}]
        if '/reviews?' in route:
            rows = [{'user':{'login':'copilot-pull-request-reviewer[bot]'},'commit_id':HEAD,'state':'COMMENTED','submitted_at':NOW.isoformat()}]
            return rows * 100 if paginated and route.endswith('&page=1') else rows
        if route == 'graphql':
            if malformed == 'errors': return {'errors':[{}]}
            second = any(a.startswith('cursor=') for a in args)
            info = {'hasNextPage': paginated and not second, 'endCursor': 'next'}
            if malformed == 'cursor': info = {'hasNextPage':True,'endCursor':None}
            if malformed == 'repeat': info = {'hasNextPage':True,'endCursor':'same'}
            if malformed == 'shape': info = {'hasNextPage': 'yes'}
            return {'data': {'repository': {'pullRequest': {'reviewThreads': {'nodes': [], 'pageInfo': info}}}}}
        raise AssertionError(route)
    return fetch, calls


def test_collector_completes_all_review_and_thread_pages(context):
    fetch, calls = github_fetch(paginated=True)
    live = proof.collect_github_gate_readback('acme/app',42,str(context.worktree),fetch=fetch,now=NOW)
    assert len(live['reviews']) == 101 and live['threads_complete']
    assert live['checks'][-1]['app_id'] == -1
    assert sum(a[0]=='graphql' for a in calls) == 2
    assert live['before'] == live['after']
    assert project_gates(context,live)[0]['status'] == 'passed'


@pytest.mark.parametrize('malformed', ['errors','cursor','repeat','shape'])
def test_collector_refuses_incomplete_or_malformed_pages(context, malformed):
    fetch, _ = github_fetch(malformed=malformed)
    with pytest.raises(delivery.DevelopmentDeliveryError):
        proof.collect_github_gate_readback('acme/app',42,str(context.worktree),fetch=fetch,now=NOW)


def test_refresh_executes_again_on_cached_model_reuse_and_new_gate_blocks(context):
    stage(context)
    target = {'number':42,'headRefOid':HEAD,'baseRefOid':BASE}
    fetch, calls = github_fetch()
    first = proof.refresh_packet_readiness(context.packet,target,HEAD,context.policy,fetch=fetch,now=NOW)
    assert all(first['readiness_evidence_verified'].values())
    fetch2, calls2 = github_fetch(extra_required=True)
    reused = proof.refresh_packet_readiness(context.packet,target,HEAD,context.policy,fetch=fetch2,now=NOW)
    assert reused['pr_check_status'] == 'unknown'
    assert calls and calls2
    def failed(_): raise OSError('offline')
    unknown = proof.refresh_packet_readiness(context.packet,target,HEAD,context.policy,fetch=failed,now=NOW)
    assert unknown['pr_check_status'] == unknown['copilot_status'] == 'unknown'
    wrong = proof.refresh_packet_readiness(context.packet,{**target,'baseRefOid':HEAD},HEAD,context.policy,fetch=fetch,now=NOW)
    assert wrong['pr_check_status'] == 'unknown'


@pytest.mark.parametrize('reference', [{}, {'path':'outside','sha256':'bad'}, {'path':'../outside.json','sha256':'a'*64}])
def test_packet_refs_cannot_escape_or_omit_binding(context, reference):
    with pytest.raises(delivery.DevelopmentDeliveryError): proof._bound(context.packet, reference)


def test_context_and_cli_fail_closed(context, capsys):
    assert handle_readiness_proof(SimpleNamespace(state_file=str(context.state),head=HEAD,provider_readback=None,json=True)) == 1
    assert json.loads(capsys.readouterr().out)['validation_status'] == 'unknown'
    with pytest.raises(delivery.DevelopmentDeliveryError):
        handle_readiness_proof(SimpleNamespace(state_file=str(context.state),head=HEAD,provider_readback=str(context.source),json=True))
    with pytest.raises(delivery.DevelopmentDeliveryError): proof._context(context.state,'bad',context.policy)
    with pytest.raises(delivery.DevelopmentDeliveryError): proof._context(context.state,HEAD,'f'*64)
    context.task['repository']['id']='github:other/app';context.state.write_text(json.dumps(context.task))
    with pytest.raises(delivery.DevelopmentDeliveryError): proof._context(context.state,HEAD,context.policy)


def test_cli_registration_and_packet_provider_file(context,capsys):
    stage(context)
    readback=context.packet/'github.json';readback.write_text(json.dumps(provider()))
    # Command clock is live, so the old capture deliberately remains unknown.
    assert main(['develop','readiness-proof',str(context.state),'--head',HEAD,'--provider-readback',str(readback),'--json'])==1
    assert json.loads(capsys.readouterr().out)['pr_check_status']=='unknown'


@pytest.mark.parametrize('mapping', [
    {'executable':'{work_item}/artifacts/test-runtime314/bin/python','authority':'inferred'},
    {'executable':'relative/python','authority':'selected_profile'},
    {'executable':'{unknown}/python','authority':'selected_profile'},
    {'executable':'{work_item}/../../outside/python','authority':'selected_profile'},
])
def test_executable_mapping_cannot_infer_or_escape_authority(context, mapping):
    context.selected['validation']['command_executables']={COMMAND:mapping}
    assert not proof._matches_command(COMMAND,[str(context.packet/'artifacts/test-runtime314/bin/python'),'-m','pytest','tests/','-q'],context.task,context.selected)


def test_exact_command_without_instrumentation_and_malformed_run(context):
    stage(context,argv=[str(context.worktree/'.venv/bin/python'),'-m','pytest','tests/','-q'])
    assert proof.validation_proof(context.packet,context.task,context.selected,HEAD,context.policy,NOW)['status']=='passed'
    value=stage(context);value['evidence']['validation_runs']=[]
    context.task['receipts']=[{'state':'local_validation',**ref(context,'stage',value)}]
    assert proof.validation_proof(context.packet,context.task,context.selected,HEAD,context.policy,NOW)['status']=='unknown'
    assert not proof._matches_command('',[],context.task,context.selected)


def test_actual_full_gate_cache_annotation_emits_verified_validation(context):
    private = context.packet / 'artifacts/producer-contract-repair-v2/full-v4'
    argv = [str(context.worktree / '.venv/bin/python'), '-m', 'pytest', 'tests/', '-q',
            '--basetemp=' + str(private / 'tmp/tests'), '-o', 'cache_dir=' + str(private / 'pytest-cache'),
            '--cov=genomes_agentic_os', '--cov-branch', '--cov-report=json:' + str(private / 'coverage.json')]
    stage(context, argv=argv)
    result = proof.emit_readiness_evidence(context.state, head=HEAD, policy=context.policy, now=NOW)
    assert result['validation_status'] == 'passed'
    assert result['readiness_evidence_verified']['validation'] is True


@pytest.mark.parametrize('extras', [
    ['-o'], ['-o', 'addopts=-k focused'], ['-o', 'cache_dir='], ['-o', 'cache_dir=relative'],
    ['-o', 'cache_dir=/unrelated/task/cache'], ['-o', 'cache_dir={packet}/artifacts/../../escape'],
    ['-o', 'cache_dir={packet}/artifacts'], ['--override-ini=cache_dir={packet}/artifacts/cache'],
    ['-o', 'cache_dir={packet}/artifacts/cache', '-o', 'cache_dir={packet}/artifacts/second'],
    ['-o', 'cache_dir={packet}/artifacts/cache', '-k', 'focused'],
    ['-o', 'cache_dir={packet}/artifacts/cache', '-m', 'unit'],
    ['-o', 'cache_dir={packet}/artifacts/cache', 'tests/test_one.py'],
])
def test_cache_annotation_cannot_override_suite_or_escape_private_artifacts(context, extras):
    argv = [str(context.worktree / '.venv/bin/python'), '-m', 'pytest', 'tests/', '-q',
            *(item.format(packet=context.packet) for item in extras)]
    stage(context, argv=argv)
    assert proof.validation_proof(context.packet, context.task, context.selected, HEAD, context.policy, NOW)['status'] == 'unknown'


def test_cache_annotation_symlink_escape_is_refused(context):
    artifacts = context.packet / 'artifacts'
    artifacts.mkdir()
    (artifacts / 'outside').symlink_to(context.worktree, target_is_directory=True)
    argv = [str(context.worktree / '.venv/bin/python'), '-m', 'pytest', 'tests/', '-q',
            '-o', 'cache_dir=' + str(artifacts / 'outside/cache')]
    assert not proof._matches_command(COMMAND, argv, context.task, context.selected)


def test_pytest_annotations_cannot_extend_other_required_commands(context):
    configured = '.venv/bin/python -m unittest'
    actual = [str(context.worktree / '.venv/bin/python'), '-m', 'unittest', '--cov-branch']
    assert not proof._matches_command(configured, actual, context.task, context.selected)


def test_bound_size_object_and_collision_guards(context,monkeypatch):
    value=ref(context,'input',{})
    monkeypatch.setattr(proof,'MAX_BYTES',1)
    with pytest.raises(delivery.DevelopmentDeliveryError):proof._bound(context.packet,value)
    with pytest.raises(delivery.DevelopmentDeliveryError):proof._json(context.packet/'input.json')
    monkeypatch.setattr(proof,'MAX_BYTES',1024)
    (context.packet/'array.json').write_text('[]')
    with pytest.raises(delivery.DevelopmentDeliveryError):proof._json(context.packet/'array.json')
    leaf=proof._leaf(context.packet,'immutable',{'a':1})
    (context.packet/leaf['path']).write_text('changed')
    with pytest.raises(delivery.DevelopmentDeliveryError):proof._leaf(context.packet,'immutable',{'a':1})


def test_nonlist_checks_and_legacy_status_app_authority(context):
    live=provider();live['checks']=None
    assert project_gates(context,live)[0]['status']=='unknown'
    context.selected['validation']['ci_contract']['checks'][0]['app_id']=-1
    context.selected['validation']['ci_contract']['source']['required_checks'][0]['app_id']=-1
    live=provider();live['required_checks'][0]['app_id']=-1;live['checks'][0]['app_id']=-1
    assert project_gates(context,live)[0]['status']=='passed'


@pytest.mark.parametrize('rows',[None,[],[{}],[{'context':'x','app_id':True}],[{'context':'x','app_id':0}],[{'context':'x','app_id':-2}],CHECKS+CHECKS[:1]])
def test_required_contract_shape(rows):
    assert proof._check_rows(rows) is None


def test_collector_bounds_runtime_and_pages(context,monkeypatch):
    fetch,_=github_fetch()
    times=iter([0,121])
    monkeypatch.setattr(proof.time,'monotonic',lambda:next(times))
    with pytest.raises(delivery.DevelopmentDeliveryError,match='duration'):
        proof.collect_github_gate_readback('acme/app',42,str(context.worktree),fetch=fetch,now=NOW)
    monkeypatch.undo()
    monkeypatch.setattr(proof,'MAX_PAGES',1)
    fetch,_=github_fetch(paginated=True)
    with pytest.raises(delivery.DevelopmentDeliveryError,match='pagination exceeds'):
        proof.collect_github_gate_readback('acme/app',42,str(context.worktree),fetch=fetch,now=NOW)
    fetch,_=github_fetch()
    def malformed(args):return {} if '/rules/branches/' in args[0] else fetch(args)
    with pytest.raises(delivery.DevelopmentDeliveryError,match='shape'):
        proof.collect_github_gate_readback('acme/app',42,str(context.worktree),fetch=malformed,now=NOW)
    def threads_forever(args):
        if args[0]=='graphql':return {'data':{'repository':{'pullRequest':{'reviewThreads':{'nodes':[],'pageInfo':{'hasNextPage':True,'endCursor':'next'}}}}}}
        return fetch(args)
    with pytest.raises(delivery.DevelopmentDeliveryError,match='thread pagination exceeds'):
        proof.collect_github_gate_readback('acme/app',42,str(context.worktree),fetch=threads_forever,now=NOW)


@pytest.mark.parametrize('repo,number',[('bad',42),('acme/app',0),('acme/app',True)])
def test_collector_invalid_subject(context,repo,number):
    with pytest.raises(delivery.DevelopmentDeliveryError):proof.collect_github_gate_readback(repo,number,str(context.worktree),fetch=lambda _:None,now=NOW)


def test_default_existing_transport_is_bounded_and_no_model(context,monkeypatch):
    observed=[]
    def run(args,**kwargs):observed.append((args,kwargs));return SimpleNamespace(returncode=0,stdout='{"ok":true}')
    monkeypatch.setattr(proof.subprocess,'run',run)
    assert proof._github_json(['repos/acme/app'],str(context.worktree))=={'ok':True}
    assert observed[0][0]==['gh','api','repos/acme/app'] and observed[0][1]['timeout']==30
    monkeypatch.setattr(proof.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=1,stdout=''))
    with pytest.raises(delivery.DevelopmentDeliveryError):proof._github_json([],str(context.worktree))
    fetch,_=github_fetch()
    monkeypatch.setattr(proof,'_github_json',lambda args,wt:fetch(args))
    assert proof.collect_github_gate_readback('acme/app',42,str(context.worktree),now=NOW)['reviews_complete']


def test_implementation_stage_writer_uses_canonical_recorded_receipt(tmp_path,monkeypatch):
    repo,base=_repository(tmp_path)
    root=tmp_path/'os';_project(root,repo)
    worktree=tmp_path/'owned';worktree.mkdir()
    monkeypatch.setattr(delivery,'create_isolated_worktree',lambda **kw:{'name':'owned','path':str(worktree),'branch':'feature/CC-PROOF','base_sha':base})
    run=delivery.start_development_run(root,'acme','app',['CC-PROOF'],run_id='proof-writer',apply=True)
    state=Path(run['tasks'][0]['state_ref']);task=delivery.TaskState(state)
    delivery.run_development_stage(state,stage='readiness',receipts={'planned':_stage_receipt(tmp_path,'planned')},idempotency_prefix='ready')
    captured=[]
    monkeypatch.setattr(proof,'emit_readiness_evidence',lambda state_file,**kwargs:captured.append((state_file,kwargs)))
    delivery.run_development_stage(state,stage='implementation',receipts={
        'implementing':_stage_receipt(tmp_path,'implementing'),
        'local_validation':_stage_receipt(tmp_path,'local_validation',status='passed',evidence={'head_sha':HEAD,'policy_fingerprint':task.read()['policy_fingerprint'],'compileall':'passed','unit_tests':'passed'})},idempotency_prefix='implement')
    assert len(captured)==1 and captured[0][1]['head']==HEAD
    assert task.read()['state']=='local_validation'


def test_canonical_stage_emits_actual_proof_using_real_generated_policy(tmp_path,monkeypatch):
    repo,base=_repository(tmp_path);root=tmp_path/'os';_project(root,repo)
    worktree=tmp_path/'owned';worktree.mkdir()
    monkeypatch.setattr(delivery,'create_isolated_worktree',lambda **kw:{'name':'owned','path':str(worktree),'branch':'feature/CC-WRITER','base_sha':base})
    run=delivery.start_development_run(root,'acme','app',['CC-WRITER'],run_id='real-proof-writer',apply=True)
    state=Path(run['tasks'][0]['state_ref']);task=delivery.TaskState(state)
    delivery.run_development_stage(state,stage='readiness',receipts={'planned':_stage_receipt(tmp_path,'planned')},idempotency_prefix='ready')
    current=task.read();packet=Path(current['work_item']);ctx=SimpleNamespace(packet=packet)
    identity={'head':HEAD,'clean':'true','repository':'https://github.com/acme/app.git','branch':current['worktree']['branch']}
    terminal={'schema':'agentic-os-long-running-terminal/v1','id':'actual','status':'success','exit_code':0,
              'finished_at':NOW.isoformat(),'git_identity_pre':identity,'git_identity_post':identity,'post_run_invariants_ok':True,'expected_git_identity':{'worktree':str(worktree)}}
    command={'id':'actual','work_dir':str(worktree),'expected_git_identity':{'worktree':str(worktree)},'command':['env','REVIEW_POLICY_FINGERPRINT='+current['policy_fingerprint'],'PATH=/task/bin','python3','-m','pytest','tests','-q']}
    row={'command':'python3 -m pytest tests -q','terminal':ref(ctx,'terminal',terminal),'command_receipt':ref(ctx,'command',command)}
    evidence={'head_sha':HEAD,'policy_fingerprint':current['policy_fingerprint'],'compileall':'passed','unit_tests':'passed','validation_runs':[row]}
    delivery.run_development_stage(state,stage='implementation',receipts={
      'implementing':_stage_receipt(packet,'implementing'),
      'local_validation':_stage_receipt(packet,'local_validation',status='passed',evidence=evidence)},idempotency_prefix='implementation')
    envelope=json.loads((packet/'artifacts/finishing-touches/readiness-evidence.json').read_text())
    assert proof._bound(packet,envelope['validation'])['status']=='passed'
    assert proof._bound(packet,envelope['ci'])['status']=='unknown'
    assert proof._bound(packet,envelope['copilot'])['status']=='unknown'


def test_missing_execution_policy_binding_is_unknown(context):
    actual=[str(context.worktree/'.venv/bin/python'),'-m','pytest','tests/','-q']
    stage(context,command_changes={'command':actual})
    assert proof.validation_proof(context.packet,context.task,context.selected,HEAD,context.policy,NOW)['status']=='unknown'
    stage(context,command_changes={'command':actual,'environment_overrides':{'REVIEW_POLICY_FINGERPRINT':context.policy}})
    assert proof.validation_proof(context.packet,context.task,context.selected,HEAD,context.policy,NOW)['status']=='unknown'


@pytest.mark.parametrize('side', ['git_identity_pre','git_identity_post'])
@pytest.mark.parametrize('field,value', [('branch','feature/other'),('branch',''),('repository','api'),('repository','/tmp/repo/.git'),('repository','')])
def test_identity_must_match_actual_repository_and_registered_branch(context,side,field,value):
    identity={'head':HEAD,'clean':'true','branch':context.task['worktree']['branch'],'repository':'git@github.com:acme/app.git'}
    identity[field]=value
    stage(context,terminal_changes={side:identity})
    assert proof.validation_proof(context.packet,context.task,context.selected,HEAD,context.policy,NOW)['status']=='unknown'


@pytest.mark.parametrize('where', ['command','terminal'])
def test_registered_worktree_scope_requires_explicit_record(context,where):
    stage(context,**({'command_changes':{'expected_git_identity':{}}} if where=='command' else {'terminal_changes':{'expected_git_identity':{'worktree':'/other'}}}))
    assert proof.validation_proof(context.packet,context.task,context.selected,HEAD,context.policy,NOW)['status']=='unknown'


def test_repository_aliases_cannot_match_empty_normalization(context):
    context.selected['repository_id']='api'
    stage(context,terminal_changes={key:{'head':HEAD,'clean':'true','branch':context.task['worktree']['branch'],'repository':'/tmp/repo/.git'} for key in ['git_identity_pre','git_identity_post']})
    assert proof.validation_proof(context.packet,context.task,context.selected,HEAD,context.policy,NOW)['status']=='unknown'


@pytest.mark.parametrize('app_id',[15368.0,True,None,'15368',0,-2])
def test_observed_check_application_requires_typed_identity(context,app_id):
    live=provider();live['checks'][0]['app_id']=app_id
    assert project_gates(context,live)[0]['status']=='unknown'


@pytest.mark.parametrize('route',[None,'made_up'])
def test_contract_capture_route_is_explicit(context,route):
    context.selected['validation']['ci_contract']['source']['route']=route
    assert project_gates(context)[0]['status']=='unknown'


def test_missing_both_rule_arrays_cannot_prove_empty_rules(context):
    context.selected['validation']['ci_contract']['source'].pop('active_rules')
    live=provider();live.pop('active_rules')
    assert project_gates(context,live)[0]['status']=='unknown'


def test_collector_refuses_oversized_provider_pages(context):
    fetch,_=github_fetch()
    def oversized(args):return [{}]*101 if '/rules/branches/' in args[0] else fetch(args)
    with pytest.raises(delivery.DevelopmentDeliveryError,match='shape'):
        proof.collect_github_gate_readback('acme/app',42,str(context.worktree),fetch=oversized,now=NOW)
    def large_threads(args):
        data=fetch(args)
        if args[0]=='graphql':data['data']['repository']['pullRequest']['reviewThreads']['nodes']=[{}]*101
        return data
    with pytest.raises(delivery.DevelopmentDeliveryError,match='malformed'):
        proof.collect_github_gate_readback('acme/app',42,str(context.worktree),fetch=large_threads,now=NOW)


def test_pinned_task_owned_interpreter_launcher_may_use_standard_venv_symlink(context):
    launcher=context.packet/'artifacts/test-runtime314/bin/python';launcher.parent.mkdir(parents=True)
    outside=context.worktree.parent/'system-python';outside.write_text('offline fixture')
    launcher.symlink_to(outside)
    context.selected['validation']['command_executables']={COMMAND:{'executable':'{work_item}/artifacts/test-runtime314/bin/python','authority':'selected_profile'}}
    stage(context,argv=[str(launcher),'-m','pytest','tests/','-q'])
    assert proof.validation_proof(context.packet,context.task,context.selected,HEAD,context.policy,NOW)['status']=='passed'


@pytest.mark.parametrize('field,value',[('review',[]),('repository',{'id':'different','base_branch':'main'}),
    ('repository',{'id':'github:acme/app','base_branch':None}),('provenance',{}),
    ('provenance',{'source_ref':'','source_sha256':'a'*64,'selected_content_sha256':'b'*64})])
def test_rehashed_v2_malformed_gate_provenance_is_rejected(context,field,value):
    selected=context.snapshot['selected_profile'];selected[field]=value
    selected['sha256']=delivery._json_sha256({k:v for k,v in selected.items() if k!='sha256'})
    context.snapshot['fingerprint']=delivery._effective_policy_snapshot_fingerprint(context.snapshot)
    with pytest.raises(delivery.DevelopmentDeliveryError,match='gate authority provenance'):
        delivery._validate_effective_policy_snapshot(context.snapshot,require_selected_profile=True)


def test_explicit_profile_authority_without_file_still_hashes_frozen_content(context):
    profile={'repository':{'id':'github:acme/app','base_branch':'main'},'validation':{'commands':[COMMAND]},'review':{'copilot':{'required':False}}}
    selected=delivery._selected_profile_policy_authority(profile)
    assert selected['provenance']['source_sha256']==delivery._json_sha256(profile)
    assert selected['review']['copilot']['required'] is False


def test_same_policy_packet_pointer_cannot_capture_or_mutate_other_packet(context):
    stage(context)
    other=context.packet.parent/'other-packet';other.mkdir()
    a=other/'autodev.json'
    # A malicious caller packet points to a valid B task with the same policy.
    a.write_text((context.packet/'autodev.json').read_text())
    marker=context.packet/'artifacts/finishing-touches/readiness-evidence.json';marker.parent.mkdir(parents=True);marker.write_text('immutable predecessor')
    calls=[]
    def fetch(args):calls.append(args);raise AssertionError('provider must not run')
    with pytest.raises(delivery.DevelopmentDeliveryError,match='caller packet differs'):
        proof.refresh_packet_readiness(other,{'number':42,'headRefOid':HEAD,'baseRefOid':BASE},HEAD,context.policy,fetch=fetch,now=NOW)
    assert calls==[] and marker.read_text()=='immutable predecessor'
    assert not (other/'artifacts').exists()


@pytest.mark.parametrize('where,key,value',[('task','schema','other'),('manifest','schema','other'),
    ('manifest','canonical_work_id','acme:app:OTHER'),('delivery','canonical_work_id','acme:app:OTHER'),
    ('delivery','run_id','other-run'),('delivery','work_item','/other'),('task','autodev_path','/other/autodev.json')])
def test_canonical_work_identity_is_bound_before_emission(context,where,key,value):
    path=context.state if where=='task' else context.packet/'autodev.json'
    payload=json.loads(path.read_text())
    if where=='delivery':payload['delivery'][key]=value
    else:payload[key]=value
    path.write_text(json.dumps(payload))
    with pytest.raises(delivery.DevelopmentDeliveryError):proof._context(context.state,HEAD,context.policy)
    assert not (context.packet/'artifacts/finishing-touches/readiness-evidence.json').exists()


def test_pointer_swap_during_capture_cannot_redirect_emission(context):
    stage(context)
    other=context.packet.parent/'other-packet';other.mkdir()
    bstate=other/'state.json'
    btask=deepcopy(context.task);btask['work_item']=str(other)
    btask['canonical_work_id']='acme:app:OTHER';btask['receipts']=[]
    bstate.write_text(json.dumps(btask))
    bmanifest=json.loads((context.packet/'autodev.json').read_text())
    bmanifest['canonical_work_id']=btask['canonical_work_id']
    bmanifest['delivery'].update(canonical_work_id=btask['canonical_work_id'],work_item=str(other),task_state_ref=str(bstate))
    (other/'autodev.json').write_text(json.dumps(bmanifest))
    baseline={}
    for packet in (context.packet,other):
        marker=packet/'artifacts/finishing-touches/readiness-evidence.json';marker.parent.mkdir(parents=True);marker.write_text('preserved')
        baseline[marker]=marker.read_bytes()
    fetch,calls=github_fetch()
    switched=False
    def swap(args):
        nonlocal switched
        value=fetch(args)
        if not switched:
            # Redirect the originally read task path to another fully valid,
            # same-policy canonical packet while provider capture is in flight.
            context.state.write_text(json.dumps(btask))
            bmanifest['delivery']['task_state_ref']=str(context.state)
            (other/'autodev.json').write_text(json.dumps(bmanifest))
            switched=True
        return value
    with pytest.raises(delivery.DevelopmentDeliveryError,match='emission packet differs'):
        proof.refresh_packet_readiness(context.packet,{'number':42,'headRefOid':HEAD,'baseRefOid':BASE},HEAD,context.policy,fetch=swap,now=NOW)
    assert calls and all(marker.read_bytes()==data for marker,data in baseline.items())
    assert not (other/'artifacts/finishing-touches/proofs').exists()
    assert not (context.packet/'artifacts/finishing-touches/proofs').exists()
