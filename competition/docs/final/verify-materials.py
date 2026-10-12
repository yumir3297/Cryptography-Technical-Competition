"""Check current delivery text, copies, references, evidence and source identity."""
import hashlib
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'competition/docs/final'
LOCAL = ROOT.parent / 'docs/competition-final-20261010'
NAMES = {
    'competition-protocol.md': '14_比赛版协议说明.md',
    'query-audit-scope.md': '15_查询与审计比赛口径.md',
    'industrial-handoff.md': '16_工业场景协议开发交接.md',
    'payment-handoff.md': '17_付款场景协议开发交接.md',
    'medical-handoff.md': '18_医疗场景协议开发交接.md',
    'claims-evidence.md': '19_声明与实际证据对应清单.md',
    'finalization-record.md': '20_协议收尾交付记录.md',
    'r2-application-mapping.md': '21_原R2与比赛应用对照.md',
    'developer-scope-notes.md': '22_比赛范围开发注释.md',
    'protocol-review.md': '23_协议复检记录.md',
    'interface-reference.md': '24_当前内部接口与返回值对照.md',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mirror_text(source):
    def rewrite(match):
        href = match[2]
        if '://' in href or href.startswith('#'):
            return match[0]
        target = (source.parent / href.split('#', 1)[0]).resolve()
        if target.parent == BASE and target.name in NAMES:
            target = LOCAL / NAMES[target.name]
        link = os.path.relpath(target, LOCAL).replace('\\', '/')
        if '#' in href:
            link += '#' + href.split('#', 1)[1]
        return '[' + match[1] + '](' + link + ')'
    return re.sub(r'\[([^\]]+)\]\(([^)]+)\)', rewrite, source.read_text(encoding='utf-8'))


def check(report_path=None):
    import sys
    sys.path.insert(0, str(ROOT))
    from competition.verify_repository import check as repository_check
    result = repository_check()
    pairs = []
    for name, local_name in NAMES.items():
        source, local = BASE / name, LOCAL / local_name
        if local.exists():
            assert local.read_text(encoding='utf-8') == mirror_text(source), local_name
            pairs.append(local_name)
    result['checked_local_copies'] = len(pairs)
    target = Path(report_path) if report_path else ROOT / '.runtime/current-material-check.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path)
    check(parser.parse_args().report)
