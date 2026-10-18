/**
 * The console's own calls, and nothing else.
 *
 * A refusal keeps the rule that produced it: the console, the entry and the
 * endpoints all answer ``{"deny": <rule>}``, and this carries that name up so the
 * page can show which rule said no rather than "something went wrong".
 */
import type { ConsoleStatus, Pending, Scenarios, Side, SubmitReply } from './types'

const BASE = '/console'

export class DenyError extends Error {
  constructor(readonly code: string) {
    super(code)
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let reply: Response
  try {
    reply = await fetch(BASE + path, init)
  } catch {
    throw new DenyError('CONSOLE_UNREACHABLE')
  }
  let body: unknown = null
  try {
    body = await reply.json()
  } catch {
    throw new DenyError('CONSOLE_ANSWER')
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
  status: () => call<ConsoleStatus>('/api/status'),

  scenarios: () => call<Scenarios>('/api/scenarios'),

  pending: () => call<Pending>('/api/pending'),

  decide: (profile: string, role: string, id: string, approve: boolean) =>
    call<{ taken: boolean }>(
      '/api/decide',
      post({ profile, role, id, approve }),
    ),

  package: () => call<unknown>('/api/package'),

  submit: (profile: string, intent?: Record<string, unknown>) =>
    call<SubmitReply>(
      '/api/submit',
      post(intent && Object.keys(intent).length ? { profile, intent } : { profile }),
    ),

  step: (side: Side, operationId: string, step: string) =>
    call<Record<string, unknown>>(
      '/api/step',
      post({ side, operation_id: operationId, step }),
    ),
}
