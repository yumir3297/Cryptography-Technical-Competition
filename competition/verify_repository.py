"""Check the competition repository's current scope, imports and document links."""
import argparse
import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETIRED = ('research', 'research_archives', 'research_evidence', 'verification', 'docs')
# Directories that are not this repository's own content: a build artifact, a
# vendored dependency tree or a byte cache.  They are read by neither the code
# walk nor the document walk -- a package's own README is not a document of this
# repository, and its links are not this repository's to keep good.
SKIPPED = ('evidence', '__pycache__', 'node_modules')


def check():
    assert all(not (ROOT / name).exists() for name in RETIRED), 'Research roots must be outside the Git worktree'
    links = 0
    code = list((ROOT / 'competition').rglob('*.py')) + list((ROOT / 'system_dev').rglob('*.py'))
    code = [p for p in code if not any(x in p.relative_to(ROOT).parts for x in SKIPPED)]
    for path in code:
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            assert not any(n.split('.')[0] in RETIRED for n in names), (path, names)
            for name in names:
                if name.startswith('competition.'):
                    target = ROOT.joinpath(*name.split('.'))
                    assert target.with_suffix('.py').is_file() or target.is_dir(), (path, name)
    docs = list(ROOT.glob('*.md')) + list((ROOT / 'competition').rglob('*.md')) + list((ROOT / 'system_dev').rglob('*.md'))
    docs = [p for p in docs if not any(x in p.relative_to(ROOT).parts for x in SKIPPED)]
    for path in docs:
        text = re.sub(r'```[\s\S]*?```', '', path.read_text(encoding='utf-8-sig'))
        for href in re.findall(r'\[[^\]]+\]\(([^)]+)\)', text):
            href = href.strip('<>')
            if '://' in href or href.startswith('#'):
                continue
            target = (path.parent / href.split('#', 1)[0]).resolve()
            assert target.is_relative_to(ROOT) and target.exists(), (str(path.relative_to(ROOT)), href)
            links += 1
    checked_evidence = 0
    for folder in ('w-slice-20261011-final', 'w-same-oid-20261011'):
        base = ROOT / 'competition/evidence' / folder
        manifest = json.loads((base / 'manifest.json').read_text(encoding='utf-8'))
        for row in manifest['files']:
            content = (base / row['path']).read_bytes()
            assert hashlib.sha256(content).hexdigest() == row['sha256'], row['path']
            checked_evidence += 1
    workflows = list((ROOT / '.github/workflows').glob('*'))
    assert len(workflows) == 1 and workflows[0].name == 'competition-security-baseline.yml'
    subprocess.run(['git', 'diff', '--check'], cwd=ROOT, check=True)
    return {'kind': 'competition_repository_scope_check', 'passed': True,
            'python_files': len(code), 'current_documents': len(docs), 'checked_links': links,
            'original_W_evidence_files_unchanged': checked_evidence,
            'research_roots_absent': list(RETIRED), 'workflow_count': len(workflows),
            'scope': 'Current filesystem, imports, references and original artifact bytes; no universal protocol safety assertion.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = check()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
