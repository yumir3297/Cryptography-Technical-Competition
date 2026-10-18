import type { ObservationEvent, OperationRow, OperationSnapshot } from './types'

// A shared key is optional: the gateway is bound to loopback by default, and an
// operator who exposes it sets one.  It rides on every read, including the
// stream, because ``EventSource`` cannot carry a header.
const KEY = import.meta.env.VITE_VIEWER_KEY

function withKey(url: string): string {
  if (!KEY) return url
  return url + (url.includes('?') ? '&' : '?') + 'key=' + encodeURIComponent(KEY)
}

/** The SSE URL for the push channel, resuming from ``after``. */
export function streamUrl(after: number): string {
  return withKey('/api/observe/stream?after=' + after)
}

export async function fetchEvents(after: number, limit = 500):
    Promise<{ events: ObservationEvent[]; last: number }> {
  const reply = await fetch(withKey(`/api/observe/events?after=${after}&limit=${limit}`))
  if (!reply.ok) throw new Error('events refused: ' + reply.status)
  return reply.json()
}

export async function fetchOperations(profile?: string): Promise<OperationRow[]> {
  const query = profile ? '?profile=' + encodeURIComponent(profile) : ''
  const reply = await fetch(withKey('/api/observe/operations' + query))
  if (!reply.ok) throw new Error('operations refused: ' + reply.status)
  return (await reply.json()).operations
}

export async function fetchOperation(oid: string): Promise<OperationSnapshot> {
  const reply = await fetch(withKey('/api/observe/operations/' + encodeURIComponent(oid)))
  if (!reply.ok) throw new Error('operation refused: ' + reply.status)
  return reply.json()
}
