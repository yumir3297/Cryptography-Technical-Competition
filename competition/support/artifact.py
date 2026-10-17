"""Neutral artifact helpers for competition run and verification entry points.

Kept independent of any vertical-slice entry module so the official CommonW
chain never has to import retired research code to write evidence.
"""
import hashlib
import json
import subprocess
from pathlib import Path

from competition.support.paths import ROOT
from competition.support.wire import canonical, raw, strict_verify


def write(path, value):
    Path(path).write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def build_identity():
    files = sorted([p for p in (ROOT / 'competition').rglob('*')
                    if p.suffix in ('.py', '.md') and 'evidence' not in p.parts]
                   + list((ROOT / 'system_dev/v26/contracts').glob('*.json'))
                   + [ROOT / 'requirements.txt'])
    rows = [{'path': p.relative_to(ROOT).as_posix(),
             'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]
    return {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'source_files': rows,
            'source_digest': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
            'dirty': subprocess.check_output(['git', 'status', '--short'], cwd=ROOT, text=True).splitlines()}


def signed_messages_valid(run, profile, op):
    """Independently re-verify every signed chain message against the real keys."""
    aliases = {'issue': 'H', 'permit': 'G', 'authorization': 'U',
               'challenge_request': 'H', 'challenge': 'X', 'proof': 'H'}
    for name, alias in aliases.items():
        message = op[name]
        strict_verify(run.actors[profile][alias].pub, raw(message['sig'], 64),
                      canonical(['ZJJ-SIG-v1', message['protected'], message['body']]))
    for message in op['reviews']:
        strict_verify(run.actors[profile]['V'].pub, raw(message['sig'], 64),
                      canonical(['ZJJ-SIG-v1', message['protected'], message['body']]))
    return True

