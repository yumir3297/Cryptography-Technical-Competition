"""One process credential and its public allowlist line.

Every agent-side process has its own Ed25519 key.  The private half stays in a
0600 file in that process's own directory; the only thing shared is the public
``callers.jsonl`` line the trusted entry reads.  This is the same arrangement
:mod:`competition.deploy.demo` uses for its two callers, factored so the gateway,
operator and executor can each enroll themselves without sharing a key directory.
"""
import json
import os
from pathlib import Path

from competition.caller import announce, key_file_name
from competition.support.wire import require


def callers_file(value):
    """Resolve ``ZJJ_CALLERS`` pointing at either a file or a directory."""
    path = Path(value)
    if path.suffix == '.jsonl':
        return path
    return path / 'callers.jsonl'


def _append_line(path, line):
    """Append one public allowlist line with one write.

    The trusted entry may read the list while a process is appending.  A single
    ``O_APPEND`` write of one short line is atomic on the local POSIX filesystem
    this deployment uses, so a reader never sees half a line.  A duplicate line
    is not appended; the caller key and its line are made idempotently.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(line, ensure_ascii=False, sort_keys=True)
    existing = path.read_text(encoding='utf-8') if path.exists() else ''
    if text + '\n' in existing:
        return path
    with path.open('a', encoding='utf-8') as stream:
        stream.write(text + '\n')
        stream.flush()
    return path


def enroll(key_directory, name, sides, callers):
    """Make this process's key if absent and publish its public line once.

    Refuses to replace an existing key; the same function on a restart reads the
    key back and re-derives the line from it, so the private half never travels
    and the public line cannot drift from the key.
    """
    require(type(sides) is list and sides, 'SESSION_SIDES')
    path = Path(key_directory)
    path.mkdir(parents=True, exist_ok=True)
    line = announce(path, name, sides)
    _append_line(callers_file(callers), line)
    return path / key_file_name(name), line


def key_path(key_directory, name):
    """The private key file one process owns, without creating anything."""
    return Path(key_directory) / key_file_name(name)
