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
    expect(stageOf(event('STEP_CHALLENGED', { step: 'audit' }))).toBe(7)
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
                 'CLAIMED', 'EXEC_DISPATCHED', 'TOOL_RESPONDED', 'SETTLED', 'READ_PROJECTED']
    expect(progressOf(run.map((kind) => event(kind))).index).toBe(CHAIN.length - 1)
  })
})
