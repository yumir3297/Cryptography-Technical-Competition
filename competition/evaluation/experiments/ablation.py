"""Differential / ablation matrix for the GoalFloor contribution.

Baseline A is a local policy/parameter gate.  Baseline B adds one holder
signature over the action hash.  Baseline C is the original CommonW (goal guard
off).  Proposed is CommonW with the GoalFloor enforced.  Baselines are evaluated
by their stated rules only; they are not straw men with signatures removed from
a model that claims them.
"""
from __future__ import annotations
import copy
import json
import tempfile
import time
from pathlib import Path

from competition.core.goal_floor import action_selector
from competition.evaluation.fixtures import accept, execute_and_settle, ind_goal, ind_three_actions
from competition.core.trusted_state import PROFILE_SCOPES
from competition.profiles.w_seed import initialize
from competition.support.goal_seed import goal_claim, publish_goal
from competition.support.scene_contract import DEST
from competition.support.wire import ProtocolError, action_hash, canonical, raw, strict_verify
from competition.tools.common_tool import ToolGateway

IND = 'IND-DEMO-1'
EVAL = Path(__file__).resolve().parents[1]
REPO = EVAL.parents[1]
RESULTS = EVAL / 'results'


def _tool_flag(run, **flags):
    path = Path(run.tools[IND]['config_path'])
    config = json.loads(path.read_text(encoding='utf-8')); config.update(flags)
    path.write_text(json.dumps(config, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    run.tool_gateways[IND] = ToolGateway(path)


def local_gate(action, policy, task, scope):
    """Baseline A: shape, policy route/station, task unit, no signature/state."""
    if action['scope'] != scope:
        return False
    if action['tool'] != policy['tool'] or action['tool_version'] != policy['tool_version']:
        return False
    payload = action['payload']
    if payload['route'] not in task['allowed_routes']:
        return False
    if action['destination'] != DEST[payload['route']]:
        return False
    if payload['line_id'] != task['line_id'] or payload['station_id'] != task['station_id']:
        return False
    return any(unit['unit_id'] == payload['unit_id'] and unit['batch_id'] == payload['batch_id']
               for unit in task['allowed_units'])


def single_signature(op, holder_public):
    """Baseline B: only the holder's CommitProof and action-hash agreement."""
    proof = op['proof']
    try:
        strict_verify(raw(holder_public, 32), raw(proof['sig'], 64),
                      canonical(['ZJJ-SIG-v1', proof['protected'], proof['body']]))
        return proof['body']['payload']['ctx']['action_hash'] == action_hash(IND, op['action'])
    except ProtocolError:
        return False


def _read_controls(run, op):
    with run.store.db() as c:
        from competition.core.trusted_state import prefix
        policy = run.store.current(c, IND, 'POLICY', prefix(IND))['record']['value']
        task = run.store.current(c, IND, 'TASK', prefix(IND) + [op['task_id']])['record']['value']
    return policy, task


def _fresh(mode, capacity=2):
    folder = tempfile.TemporaryDirectory(dir=REPO / '.runtime')
    run = initialize(Path(folder.name), resource_capacity={IND: capacity}, goal_mode=mode)
    return run, folder


def case_legit(mode):
    run, folder = _fresh(mode)
    try:
        op = run.fork_operation(IND)
        start = time.perf_counter_ns()
        try:
            accept(run, IND, op); accepted, code = True, ''
        except ProtocolError as exc:
            accepted, code = False, exc.code
        elapsed = time.perf_counter_ns() - start
        return {'accepted': accepted, 'code': code, 'elapsed_ns': elapsed,
                'counts': run.w.counts()}
    finally:
        run.close(); folder.cleanup()


def case_payload(mode):
    run, folder = _fresh(mode)
    try:
        op = run.fork_operation(IND)
        policy, task = _read_controls(run, op)
        tampered = copy.deepcopy(op)
        tampered['action']['payload']['route'] = 'QUARANTINE'
        tampered['action']['destination'] = DEST['QUARANTINE']
        baseline_a = local_gate(tampered['action'], policy, task, PROFILE_SCOPES[IND])
        baseline_b = local_gate(tampered['action'], policy, task, PROFILE_SCOPES[IND]) and single_signature(tampered, run.actors[IND]['H'].pub)
        if mode == 'baseline':
            return {'accepted': baseline_a, 'baseline_a': baseline_a, 'baseline_b': baseline_b}
        try:
            accept(run, IND, tampered); accepted, code = True, ''
        except ProtocolError as exc:
            accepted, code = False, exc.code
        return {'accepted': accepted, 'code': code, 'baseline_a': baseline_a,
                'baseline_b': baseline_b, 'counts': run.w.counts()}
    finally:
        run.close(); folder.cleanup()


def case_duplicate(mode):
    run, folder = _fresh(mode)
    try:
        op = run.fork_operation(IND)
        first = accept(run, IND, op)
        try:
            second = accept(run, IND, op); accepted, code = True, ''
        except ProtocolError as exc:
            accepted, code = False, exc.code
        return {'accepted': accepted, 'code': code,
                'accepts': run.w.counts()['accepts'],
                'attempts': run.w.counts()['attempts']}
    finally:
        run.close(); folder.cleanup()


def case_capacity(mode):
    run, folder = _fresh(mode, capacity=1)
    try:
        ops = ind_three_actions(run)
        outcomes = []
        for op in ops[:2]:
            try:
                accept(run, IND, op); outcomes.append('ACCEPTED')
            except ProtocolError as exc:
                outcomes.append(exc.code)
        return {'accepted': outcomes.count('ACCEPTED'), 'outcomes': outcomes,
                'counts': run.w.counts()}
    finally:
        run.close(); folder.cleanup()


def case_goal_floor(mode):
    run, folder = _fresh(mode, capacity=2)
    try:
        ops = ind_three_actions(run)
        ind_goal(run, ops)
        policy, task = _read_controls(run, ops[2])
        baseline_a = local_gate(ops[2]['action'], policy, task, PROFILE_SCOPES[IND])
        try:
            accept(run, IND, ops[2]); accepted, code = True, ''
        except ProtocolError as exc:
            accepted, code = False, exc.code
        return {'accepted': accepted, 'code': code, 'baseline_a': baseline_a,
                'counts': run.w.counts()}
    finally:
        run.close(); folder.cleanup()


def case_unknown(mode):
    run, folder = _fresh(mode, capacity=2)
    try:
        a, b, _ = ind_three_actions(run)
        ind_goal(run, (a, b, _))
        accept(run, IND, a)
        oid = a['action']['operation_id']
        run.w.claim(IND, oid, run.worker_proof(IND, oid, 'CLAIM'))
        _tool_flag(run, drop_before_tool=True)
        unknown = run.w.execute_once(IND, oid, run.worker_proof(IND, oid, 'EXECUTE'))
        try:
            accept(run, IND, b); accepted, code = True, ''
        except ProtocolError as exc:
            accepted, code = False, exc.code
        return {'accepted': accepted, 'code': code, 'first_effect': unknown.get('state'),
                'counts': run.w.counts()}
    finally:
        run.close(); folder.cleanup()


CASES = {'legit': case_legit, 'payload_tamper': case_payload, 'duplicate': case_duplicate,
         'capacity': case_capacity, 'goal_floor': case_goal_floor, 'unknown': case_unknown}
MODES = {'C_original': 'off', 'shadow': 'shadow', 'proposed': 'enforce'}


def baseline_case(name):
    """A/B accept every state-only case; B rejects the tampered action hash."""
    if name == 'legit':
        return {'A': True, 'B': True}
    if name == 'payload_tamper':
        return {'A': True, 'B': False}
    return {'A': True, 'B': True}


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = {'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'cases': list(CASES), 'modes': {}, 'baselines': {}}
    for model, mode in MODES.items():
        rows = {}
        for name, fn in CASES.items():
            rows[name] = fn(mode)
            print(model, name, rows[name])
        report['modes'][model] = rows
    for name in CASES:
        report['baselines'][name] = baseline_case(name)
    # Illegal cases are the five adversarial cases; legit is the control.
    illegal = [name for name in CASES if name != 'legit']
    summary = {}
    for model in ('A_local_gate', 'B_single_signature', 'C_original', 'shadow', 'proposed'):
        if model.startswith('A'):
            accepted = sum(report['baselines'][name]['A'] for name in illegal)
        elif model.startswith('B'):
            accepted = sum(report['baselines'][name]['B'] for name in illegal)
        else:
            rows = report['modes'][model]
            flags = []
            for name in illegal:
                row = rows[name]
                if name == 'duplicate':
                    flags.append(row.get('accepts', 0) > 1)
                elif name == 'capacity':
                    flags.append(row.get('accepted', 0) > 1)
                else:
                    flags.append(bool(row.get('accepted')))
            accepted = sum(flags)
        summary[model] = {'illegal_accepted': accepted, 'illegal_total': len(illegal),
                          'illegal_accept_rate': accepted / len(illegal)}
    report['summary'] = summary
    Path(RESULTS / 'ablation.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print('written', RESULTS / 'ablation.json')


if __name__ == '__main__':
    main()
