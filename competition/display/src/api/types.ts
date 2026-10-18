// The shapes the observation face publishes.  Every one of them is a *display*
// projection: the entry marks them ``not_evidence``, ``signed: false`` and
// ``original_envelope: false``, and this page repeats that claim rather than
// treating any field here as authority.

export interface ObservationEvent {
  seq: number
  kind: string
  stage: string | null
  source: 'CORE' | 'ENTRY'
  profile: string
  operation_id: string
  lanes: string[]
  trusted_time: { lo: number; hi: number } | null
  refs: Record<string, string>
  status_label: string | null
  detail: Record<string, string>
  view_kind: 'OBSERVATION_PROJECTION'
  original_envelope: false
  signed: false
  not_evidence: true
  /** Only on entry-side flow events, which are best-effort and non-authoritative. */
  flow?: true
}

export interface OperationRow {
  profile: string
  operation_id: string
  dispatch_state: string
  effect_state: string
  receipt_state: string
}

export interface OperationSnapshot {
  kind: 'competition_operation_observation'
  profile: string
  operation_id: string
  acceptance_state: string
  dispatch_state: string
  effect_state: string
  receipt_state: string
  attempt_id: string | null
  exec_consumed: boolean
  queries: number
  accepted_at: string | null
  trusted_time: { lo: number; hi: number } | null
  final_fact_id: string | null
  final_outcome: string | null
  events: ObservationEvent[]
  view_kind: string
  original_envelope: false
  signed: false
  not_evidence: true
}
