"""Summarize generated evidence audits into one result file."""
import hashlib
import json
import time
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
EVIDENCE = EVAL / 'evidence' / '20261123'
RESULTS = EVAL / 'results'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((EVIDENCE / 'manifest.json').read_text(encoding='utf-8'))
    packages = {}
    for name, info in manifest['packages'].items():
        prefix = 'ind-goal' if name == 'IND-DEMO-1-goal' else name
        audit = json.loads((EVIDENCE / (prefix + '-audit.json')).read_text(encoding='utf-8'))
        packages[name] = {'status': audit['status'], 'passed': audit['passed'],
                          'failed': audit['failed'], 'skipped': audit.get('skipped', 0),
                          'package_sha256': info['sha256'],
                          'checks': [c['check'] for c in audit['checks']]}
    report = {'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'git_sha': manifest['git_sha'], 'anchor_sha256': {
                  'anchor-three-profiles.json': sha(EVIDENCE / 'anchor-three-profiles.json'),
                  'anchor-goal.json': sha(EVIDENCE / 'anchor-goal.json')},
              'packages': packages,
              'all_pass': all(v['status'] == 'PASS' for v in packages.values())}
    (RESULTS / 'evidence-audit.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
