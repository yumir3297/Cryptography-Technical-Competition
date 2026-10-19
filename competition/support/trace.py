"""Timing spans for one signing step, written as JSON lines.

A page cannot see inside a request, and a line that only says "the step took four
seconds" does not say which of the step's three moves took them: the entry call
that asks for a challenge, the endpoint call that signs it, or the entry call that
hands the proof back.  So a request carries a trace id -- the page sends one on
``x-zjj-trace`` and the console generates one when it does not -- and everything
done while serving it records a span against that id.

Nothing here decides anything.  Spans are written after the fact, a failure to
write one is swallowed, and code outside a traced request records nothing: the
same module is imported by the CLI, the callers and the trusted side, where there
is no page and no file to write to.  Tracing must never change what the flow does,
which is why every entry point here is a no-op when there is nothing to trace.
"""
import contextvars
import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# One trace line carries a request, its spans and the page's own events; this is
# only a guard against a file that nobody rotates by hand.
MAX_FILE = 8 << 20
# What one trace id may look like.  It arrives in a header off a network, so it is
# kept to the characters a header already allows and nothing else.
ID_CHARS = frozenset('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.')
MAX_ID = 48

# The request currently being served, on this thread or in this task.  A span
# outside a request finds nothing and records nothing.
_current = contextvars.ContextVar('zjj_trace_request', default=None)


def clean_id(value, fallback=''):
    """A trace id that is safe to write, or the fallback when nothing is left."""
    if type(value) is not str:
        return fallback
    cleaned = ''.join(ch for ch in value[:MAX_ID] if ch in ID_CHARS)
    return cleaned or fallback


def _stamp():
    now = time.time()
    return {'ts': datetime.fromtimestamp(now, timezone.utc).isoformat(timespec='milliseconds'),
            'at': round(now * 1000)}


def _ms(started):
    return round((time.perf_counter() - started) * 1000, 3)


class TraceLog:
    """One append-only file of trace lines, rotated by size.

    The path is the console's own callers directory unless a deployment says
    otherwise: ``ZJJ_TRACE_LOG`` names a file, and an empty value turns tracing
    off.  ``ZJJ_TRACE=0`` turns it off as well, for a run that does not want the
    writes at all.
    """

    def __init__(self, path, *, limit=MAX_FILE, enabled=True):
        self.path = None if path is None else Path(path)
        self.limit = limit
        self.enabled = bool(enabled and self.path is not None)
        self._lock = threading.Lock()
        if self.enabled:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                self.enabled = False

    @classmethod
    def for_folder(cls, folder):
        """The trace file a console keeps beside its callers, unless told where."""
        if os.environ.get('ZJJ_TRACE', '1') == '0':
            return cls(None, enabled=False)
        named = os.environ.get('ZJJ_TRACE_LOG')
        if named == '':
            return cls(None, enabled=False)
        return cls(Path(named) if named else Path(folder) / 'trace' / 'console.jsonl')

    def write(self, record):
        """One line, or nothing.  A trace that cannot be written is not an error."""
        if not self.enabled:
            return
        try:
            line = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return
        with self._lock:
            try:
                if self.path.exists() and self.path.stat().st_size > self.limit:
                    self.path.replace(Path(str(self.path) + '.1'))
                with self.path.open('a', encoding='utf-8') as handle:
                    handle.write(line + '\n')
            except OSError:
                # The flow is what matters; a full disk must not take it down.
                pass


@contextmanager
def request_trace(log, trace_id, route, method):
    """Serve one request under one trace id, and write its line when it ends.

    The yielded record is mutable so the caller can add the status, the query or
    an error before the line is written.  The context is reset before the write,
    so a span recorded by the writer itself could not land in this record.
    """
    record = {'source': 'console', 'id': trace_id, 'route': route, 'method': method,
              'spans': [], **_stamp()}
    token = _current.set(record)
    started = time.perf_counter()
    try:
        yield record
    finally:
        record['ms'] = _ms(started)
        # Spans finish inside out, so the order they were appended in is not the
        # order they began.  A reader wants the request's moves in the order they
        # started, which is what ``_start`` is kept for.
        record['spans'].sort(key=lambda span: span.get('_start', 0))
        for span in record['spans']:
            span.pop('_start', None)
        _current.reset(token)
        log.write(record)


@contextmanager
def span(name, **fields):
    """Time one move inside the traced request, or do nothing outside one.

    The yielded dict is the span itself: a caller that only learns the answer
    after the move -- an HTTP status, a ticket count -- adds it there and it is
    written with the span.  Spans are kept flat, and the line is written in the
    order they began: a request's three moves read as the three moves.
    """
    record = _current.get()
    if record is None:
        yield {}
        return
    entry = {'name': name, **fields}
    started = time.perf_counter()
    entry['_start'] = started
    try:
        yield entry
    finally:
        entry['ms'] = _ms(started)
        record['spans'].append(entry)


def write_event(log, page, event):
    """One event the page measured, written beside the console's own spans.

    The page sends its clock (``at`` wall time, ``t`` since load) so a click and
    the request it caused can be read in one order even though they were measured
    on two machines' worth of clocks.
    """
    record = {'source': 'ui', 'page': page, **_stamp()}
    record.update(event)
    log.write(record)
