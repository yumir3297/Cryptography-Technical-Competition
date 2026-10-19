import { describe, expect, it } from 'vitest'

import { CHAIN, isFlowEvent, progressOf, stageOf } from './flow'
import type { ObservationEvent } from './types'

function event(kind: string, detail: Record<string, string> = {}): ObservationEvent {
  return {
    seq: 1, kind, stage: null, source: 'CORE', profile: 'PAY-1', operation_id: 'op',
    lanes: [], trusted_time: null, refs: {}, status_label: null, detail,
    view_kind: 'OBSERVATION_PROJECTION', original_envelope: false, signed: false,
    not_evidence: true,
  }
}

describe('stageOf', () => {
  it('lands the entry\'s own flow events on their nodes', () => {
    expect(stageOf(event('CANDIDATE_SUBMITTED'))).toBe(0)
    expect(stageOf(event('AUTHORIZED_GUARD'))).toBe(1)
  })

  it('lands a named step on that step\'s node, whichever half published it', () => {
    expect(stageOf(event('STEP_CHALLENGED', { step: 'claim' }))).toBe(4)
    expect(stageOf(event('STEP_PROVED', { step: 'settle' }))).toBe(6)
  })

  it('treats a read as no step of a flow', () => {
    // A projection is asked for repeatedly while an operation waits, so a read
    // must not carry the chain to the end.
    expect(stageOf(event('READ_PROJECTED'))).toBe(-1)
    expect(stageOf(event('STEP_CHALLENGED', { step: 'status' }))).toBe(-1)
    expect(stageOf(event('STEP_PROVED', { step: 'audit' }))).toBe(-1)
  })

  it('treats registration and bootstrap as no step of a flow', () => {
    for (const kind of ['W_BOOTSTRAP', 'CONTROL_PUBLISHED', 'COVERAGE_INITIALIZED']) {
      expect(stageOf(event(kind))).toBe(-1)
      expect(isFlowEvent(event(kind))).toBe(false)
    }
  })
})

describe('progressOf', () => {
  it('reports the furthest node reached, not the last event seen', () => {
    const progress = progressOf([
      event('CANDIDATE_SUBMITTED'),
      event('STEP_PROVED', { step: 'accept' }),
      event('CHALLENGE_ISSUED'),
      event('STEP_CHALLENGED', { step: 'prepare' }),
    ])
    expect(progress.index).toBe(3)
    expect(progress.step).toBe('prepare')
    expect(progress.failed).toBe(false)
  })

  it('marks a trusted contradiction or a cancel as failed', () => {
    expect(progressOf([event('CLAIMED'), event('HALTED')]).failed).toBe(true)
    expect(progressOf([event('CANCELED')]).failed).toBe(true)
  })

  it('stays at -1 when nothing but bootstrap has happened', () => {
    expect(progressOf([event('DEPRECATED' as string)]).index).toBe(-1)
    expect(progressOf([]).index).toBe(-1)
  })

  it('walks a whole run to the last node', () => {
    const run = ['CANDIDATE_SUBMITTED', 'CHAIN_ASSEMBLED', 'PREPARED', 'ACCEPT_COMMITTED',
                 'CLAIMED', 'EXEC_DISPATCHED', 'TOOL_RESPONDED', 'SETTLED']
    expect(progressOf(run.map((kind) => event(kind))).index).toBe(CHAIN.length - 1)
  })

  it('does not let the reads in between move the chain', () => {
    // What the agent gateway does while an accepted operation waits: poll the
    // status projection again and again.  The chain has to stay where the real
    // steps put it.
    const accepted = [event('CANDIDATE_SUBMITTED'), event('CHAIN_ASSEMBLED'),
                      event('PREPARED'), event('ACCEPT_COMMITTED')]
    const polled = [...accepted]
    for (let index = 0; index < 5; index += 1) {
      polled.push(event('CHALLENGE_ISSUED'), event('STEP_CHALLENGED', { step: 'status' }),
                  event('READ_PROJECTED'), event('STEP_PROVED', { step: 'status' }))
    }
    const progress = progressOf(polled)
    expect(progress.index).toBe(3)
    expect(progress.index).toBe(progressOf(accepted).index)
  })
})
