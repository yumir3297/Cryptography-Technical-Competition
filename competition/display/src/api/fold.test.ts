import { describe, expect, it } from 'vitest'

import { cursorOf, foldEvents, lanesOf } from './fold'
import type { ObservationEvent } from './types'

function event(seq: number, kind: string, lanes: string[] = []): ObservationEvent {
  return {
    seq, kind, stage: null, source: 'CORE', profile: 'PAY-1', operation_id: 'op',
    lanes, trusted_time: null, refs: {}, status_label: null, detail: {},
    view_kind: 'OBSERVATION_PROJECTION', original_envelope: false, signed: false,
    not_evidence: true,
  }
}

describe('foldEvents', () => {
  it('sorts by seq and keeps one row per seq', () => {
    const merged = foldEvents([event(3, 'C'), event(1, 'A')],
                              [event(2, 'B'), event(3, 'C-again')])
    expect(merged.map((row) => row.seq)).toEqual([1, 2, 3])
    expect(merged[2].kind).toBe('C-again')
  })

  it('caps to the newest events, so a long run does not grow without bound', () => {
    const many = Array.from({ length: 10 }, (_, index) => event(index + 1, 'K'))
    expect(foldEvents([], many, 4).map((row) => row.seq)).toEqual([7, 8, 9, 10])
  })

  it('leaves what it holds alone when the page is empty', () => {
    const held = [event(1, 'A')]
    expect(foldEvents(held, [])).toBe(held)
  })

  it('reports the cursor, and the lanes in first-seen order', () => {
    const merged = foldEvents([], [event(1, 'A', ['W', 'worker']), event(2, 'B', ['W', 'X'])])
    expect(cursorOf(merged)).toBe(2)
    expect(lanesOf(merged)).toEqual(['W', 'worker', 'X'])
  })
})
