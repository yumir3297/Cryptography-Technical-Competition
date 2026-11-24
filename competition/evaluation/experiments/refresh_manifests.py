"""Refresh evidence manifest file hashes after a re-audit."""
import hashlib
import json
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    for folder in (EVAL / 'evidence' / '20261123', EVAL / 'evidence' / 'incident-20261123'):
        path = folder / 'manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['files'] = {p.name: sha(p) for p in sorted(folder.glob('*.json'))
                             if p.name != 'manifest.json'}
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True),
                        encoding='utf-8')
        print(folder.name, manifest['git_sha'], len(manifest['files']))


if __name__ == '__main__':
    main()
