"""Re-run the offline verifier against the already generated evidence packages."""
import json
from pathlib import Path

from competition.evaluation.verify import verify_package

EVAL = Path(__file__).resolve().parents[1]


def reaudit(folder, pairs):
    for package_name, anchor_name, audit_name in pairs:
        package = json.loads((folder / package_name).read_text(encoding='utf-8'))
        anchor = json.loads((folder / anchor_name).read_text(encoding='utf-8'))
        result = verify_package(package, anchor)
        (folder / audit_name).write_text(
            json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True), encoding='utf-8')
        print(folder.name, package_name, result['status'], result['passed'], result['failed'])


def main():
    three = EVAL / 'evidence' / '20261123'
    reaudit(three, [
        ('IND-DEMO-1-package.json', 'anchor-three-profiles.json', 'IND-DEMO-1-audit.json'),
        ('PAY-1-package.json', 'anchor-three-profiles.json', 'PAY-1-audit.json'),
        ('MED-DEMO-1-package.json', 'anchor-three-profiles.json', 'MED-DEMO-1-audit.json'),
        ('ind-goal-package.json', 'anchor-goal.json', 'ind-goal-audit.json'),
    ])
    incident = EVAL / 'evidence' / 'incident-20261123'
    reaudit(incident, [('incident-package.json', 'anchor-incident.json', 'incident-audit.json')])


if __name__ == '__main__':
    main()
