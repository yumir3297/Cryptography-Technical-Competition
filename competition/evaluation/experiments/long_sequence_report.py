"""Summarize E1 and audit the captured counterexample packages."""
from __future__ import annotations
import json
import time
from pathlib import Path

from competition.evaluation.verify import verify_package

EVAL = Path(__file__).resolve().parents[1]
RESULTS = EVAL / 'results'
COUNTER = EVAL / 'counterexamples'


def main():
    data = json.loads((RESULTS / 'long-sequence.json').read_text(encoding='utf-8'))
    real = data['real']
    rows = []
    for pair in real:
        proposed = pair['proposed']['trace']
        heads = [int(row['after']['goal']['headroom']) for row in proposed
                 if row.get('after') and row['after'].get('goal')]
        rows.append({'name': pair['spec']['name'], 'capacity': pair['spec']['capacity'],
                     'required': pair['spec']['required'],
                     'optional': pair['spec']['optional'],
                     'multi_goal': pair['spec']['multi_goal'],
                     'unknown_at': pair['spec']['unknown_at'],
                     'off_accepted': pair['off']['counters']['accepted'],
                     'proposed_accepted': pair['proposed']['counters']['accepted'],
                     'violations': len(pair['violations']),
                     'first_violation_position': pair['first_violation_position'],
                     'min_headroom': min(heads) if heads else None,
                     'mismatch_off': pair['off']['counters']['mismatch'],
                     'mismatch_proposed': pair['proposed']['counters']['mismatch']})
    audits = []
    for path in sorted(COUNTER.glob('*.json')):
        item = json.loads(path.read_text(encoding='utf-8'))
        result = verify_package(item['off_package'], item['off_anchor'])
        audits.append({'file': path.name, 'status': result['status'],
                       'passed': result['passed'], 'failed': result['failed'],
                       'position': item['position'],
                       'proposed_code': item['proposed_rejection']['proposed_code']})
    summary = {
        'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'real_sequences': len(real), 'model_sequences': data['model_sequences'],
        'total_real_actions': sum(len(p['off']['trace']) for p in real),
        'off_accepted': sum(p['off']['counters']['accepted'] for p in real),
        'proposed_accepted': sum(p['proposed']['counters']['accepted'] for p in real),
        'unknown': sum(p['off']['counters']['unknown'] + p['proposed']['counters']['unknown']
                       for p in real),
        'violations': data['total_violations'],
        'mismatch_zero': data['all_real_mismatch_zero'],
        'min_headroom': min((r['min_headroom'] for r in rows if r['min_headroom'] is not None),
                            default=None),
        'rows': rows, 'counterexample_audits': audits,
        'all_counterexamples_audit_pass': all(a['status'] == 'PASS' for a in audits),
        'counterexample_audit_note': ('The captured packages are from goal_mode=off; the offline '
                                     'GoalFloor check correctly fails with GOAL_WITNESS_MISSING. '
                                     'That is the counterexample: off accepts an action that the '
                                     'enforced mode rejects, but off has no GoalFloor witness.'),
    }
    (RESULTS / 'long-sequence-summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'rows'}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
