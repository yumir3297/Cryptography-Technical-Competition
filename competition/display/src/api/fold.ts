import type { ObservationEvent } from './types'

/** How many steps a display keeps; older events fall off the head. */
export const HISTORY_CAP = 2000

/**
 * Merge incoming events into the ones already held, keyed by ``seq``.
 *
 * ``seq`` is the entry's own subscription cursor, so the order the page happens
 * to receive events in does not matter: the fold sorts by it and keeps one row
 * per seq.  That is what makes a replayed stream, a resumed stream and a polled
 * page all agree on the same timeline.
 */
export function foldEvents(held: ObservationEvent[], incoming: ObservationEvent[],
                           cap = HISTORY_CAP): ObservationEvent[] {
  if (incoming.length === 0) return held
  const bySeq = new Map<number, ObservationEvent>()
  for (const event of held) bySeq.set(event.seq, event)
  for (const event of incoming) bySeq.set(event.seq, event)
  const merged = [...bySeq.values()].sort((a, b) => a.seq - b.seq)
  return merged.length > cap ? merged.slice(merged.length - cap) : merged
}

/** The highest seq held, or 0 -- the cursor a poll asks to continue from. */
export function cursorOf(events: ObservationEvent[]): number {
  return events.length ? events[events.length - 1].seq : 0
}

/** The lane labels that have appeared, in the order they first appeared. */
export function lanesOf(events: ObservationEvent[]): string[] {
  const seen: string[] = []
  for (const event of events) {
    for (const lane of event.lanes) {
      if (!seen.includes(lane)) seen.push(lane)
    }
  }
  return seen
}

/** Whether an event carries a lane, for putting it in that lane's row. */
export function inLane(event: ObservationEvent, lane: string): boolean {
  return event.lanes.includes(lane)
}
