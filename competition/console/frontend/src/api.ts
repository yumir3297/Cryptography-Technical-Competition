/**
 * The console's own calls, and nothing else.
 *
 * A refusal keeps the rule that produced it: the console, the entry and the
 * endpoints all answer ``{"deny": <rule>}``, and this carries that name up so the
 * page can show which rule said no rather than "something went wrong".
 */
import type {
  ConsoleStatus,
  Operations,
  Pending,
  Scenarios,
  Side,
  SubmitReply,
} from './types'

const BASE = '/console'

export class DenyError extends Error {
  constructor(readonly code: string) {
    super(code)
  }
}

/** One call's own account of itself, so the caller can record what it waited for. */
export interface CallTrace {
  trace?: string
  /** Set by ``call`` once the reply has arrived: what the browser waited. */
  ms?: number
  status?: number
  ok?: boolean
}

async function call<T>(path: string, init?: RequestInit, trace?: CallTrace, within = 0)
  : Promise<T> {
  const started = performance.now()
  const headers = new Headers(init?.headers)
  if (trace?.trace) headers.set('x-zjj-trace', trace.trace)
  let reply: Response
  try {
    // Reads get a deadline so one dead service cannot leave the page loading
    // for ever.  Steps are deliberately unbounded: a chain can wait minutes
    // on a person, and the page has its own "waiting" state for that.
    const signal = within > 0 && typeof AbortSignal !== 'undefined'
      && 'timeout' in AbortSignal ? AbortSignal.timeout(within) : undefined
    reply = await fetch(BASE + path, { ...init, headers, ...(signal ? { signal } : {}) })
  } catch {
    if (trace) Object.assign(trace, { ms: performance.now() - started, ok: false })
    throw new DenyError('CONSOLE_UNREACHABLE')
  }
  let body: unknown = null
  try {
    body = await reply.json()
  } catch {
    if (trace) Object.assign(trace, { ms: performance.now() - started, ok: false,
                                      status: reply.status })
    throw new DenyError('CONSOLE_ANSWER')
  }
  if (trace) {
    Object.assign(trace, { ms: performance.now() - started, ok: reply.ok,
                           status: reply.status })
  }
  if (!reply.ok) {
    const deny = (body as { deny?: unknown } | null)?.deny
    throw new DenyError(typeof deny === 'string' ? deny : 'CONSOLE_DENY')
  }
  return body as T
}

function post(payload: Record<string, unknown>): RequestInit {
  return {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  }
}

export const consoleApi = {
  status: (trace?: CallTrace) =>
    call<ConsoleStatus>('/api/status', undefined, trace, 10000),

  scenarios: (trace?: CallTrace) =>
    call<Scenarios>('/api/scenarios', undefined, trace, 10000),

  pending: (profile: string, trace?: CallTrace) =>
    call<Pending>('/api/pending?profile=' + encodeURIComponent(profile), undefined, trace, 10000),

  operations: (limit = 50, trace?: CallTrace) =>
    call<Operations>('/api/operations?limit=' + limit, undefined, trace, 10000),

  decide: (profile: string, role: string, id: string, approve: boolean, trace?: CallTrace) =>
    call<{ taken: boolean }>(
      '/api/decide',
      post({ profile, role, id, approve }),
      trace,
      20000,
    ),

  package: (trace?: CallTrace) => call<unknown>('/api/package', undefined, trace, 20000),

  submit: (profile: string, intent?: Record<string, unknown>, trace?: CallTrace) =>
    call<SubmitReply>(
      '/api/submit',
      post(intent && Object.keys(intent).length ? { profile, intent } : { profile }),
      trace,
    ),

  step: (side: Side, operationId: string, step: string, trace?: CallTrace) =>
    call<Record<string, unknown>>(
      '/api/step',
      post({ side, operation_id: operationId, step }),
      trace,
    ),

  /** The page's own events.  Sent on a timer; a failure is not the page's problem. */
  trace: (page: string, events: unknown[]) =>
    call<{ taken: boolean }>('/api/trace', post({ page, events }), undefined, 5000),
}
