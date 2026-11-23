"""Summarize the three-profile evidence packages."""
import json
import time
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
EVIDENCE = EVAL / 'evidence' / '20261123'
RESULTS = EVAL / 'results'


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    rows = {}
    for profile in ('IND-DEMO-1', 'PAY-1', 'MED-DEMO-1'):
        package = json.loads((EVIDENCE / (profile + '-package.json')).read_text(encoding='utf-8'))
        audit = json.loads((EVIDENCE / (profile + '-audit.json')).read_text(encoding='utf-8'))
        rows[profile] = {
            'audit_status': audit['status'],
            'checks': len(audit['checks']),
            'ledger_id': package['tool_certificate']['claim']['record']['value']['ledger_id'],
            'reviews': [r['body']['payload']['purpose'] for r in package['frozen']['op']['reviews']],
            'outcome': package['settlement']['outcome'],
            'effect_id': package['settlement']['effect_id'],
            'goal_witness': package['commit']['value'].get('goal') is not None,
        }
    report = {'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'profiles': rows, 'all_pass': all(r['audit_status'] == 'PASS' for r in rows.values())}
    (RESULTS / 'cross-scenario.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
