/**
 * The page's own side of the trace.
 *
 * The console writes what the server did with a request; this writes what the
 * person waited for.  Three things make a step feel slow, and only one of them is
 * on the server: the browser's own call, the entry's three moves, and the page's
 * three-second poll that may be queued in front of the call.  So every action
 * gets one id, that id travels as ``x-zjj-trace``, and every event here carries
 * it -- a click, each fetch, and when the action finally finished.
 *
 * Nothing here can block a step.  Events are buffered and sent on a timer with
 * ``fetch(..., {keepalive: true})``; a failed send is dropped.  The page keeps
 * working when the trace endpoint is not there.
 */
import { consoleApi } from './api'

const PAGE = Math.random().toString(36).slice(2, 10)
/** One buffer is one request; a page that is clicked quickly does not send a
 *  request per event. */
const MAX_BUFFER = 32
/** How long an event may sit here before it is sent. */
const FLUSH_MS = 1000
/** A poll slower than this is worth a line; a fast one is just the page being
 *  alive and would drown the trace in noise. */
const SLOW_POLL_MS = 250

interface TraceEvent {
  kind: string
  trace?: string
  ms?: number
  ok?: boolean
  [key: string]: unknown
}

let buffer: TraceEvent[] = []
let timer: number | undefined

/** Wall time, which is what the console's own lines carry, plus the page's own
 *  monotonic clock for durations. */
function stamp(): { at: string; t: number } {
  return { at: new Date().toISOString(), t: Math.round(performance.now()) }
}

/** One trace id per action, in the same shape the console accepts. */
export function newTrace(): string {
  return (
    Date.now().toString(36) +
    '-' +
    Math.random().toString(36).slice(2, 10)
  )
}

/** Send what is buffered, if anything.  Never throws and never waits. */
export function flush(): void {
  if (timer !== undefined) {
    window.clearTimeout(timer)
    timer = undefined
  }
  if (!buffer.length) return
  const events = buffer
  buffer = []
  void consoleApi.trace(PAGE, events).catch(() => undefined)
}

/** Record one event.  ``slowOnly`` is how a poll says "only if I was slow". */
export function note(event: TraceEvent, slowOnly = false): void {
  if (slowOnly && (event.ms ?? 0) < SLOW_POLL_MS) return
  buffer.push({ ...stamp(), ...event })
  if (buffer.length >= MAX_BUFFER) {
    flush()
    return
  }
  if (timer === undefined) {
    timer = window.setTimeout(flush, FLUSH_MS)
  }
}

/** Keep the last events when the page is closed or reloaded. */
export function installFlushHooks(): void {
  window.addEventListener('pagehide', flush)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush()
  })
}
