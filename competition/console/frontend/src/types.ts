/** The two sides of the flow, named the way the entry names them. */
export type Side = 'H' | 'worker'

export interface SessionInfo {
  side: Side
  open: boolean
  caller?: string
  sides?: Side[]
  expires?: string
}

export interface ConsoleStatus {
  entry: string
  profile: string
  sessions: SessionInfo[]
}

/** One scenario the entry fixes, and the intent fields its action takes. */
export interface Scenario {
  profile: string
  intents: string[]
}

export interface Scenarios {
  profiles: Scenario[]
}

export interface SubmitReply {
  operation_id: string
  challenge?: unknown
}

/** One request the page made, and what came back, kept for the timeline. */
export interface StepRecord {
  at: string
  side: string
  step: string
  ok: boolean
  detail: unknown
}
