/** The two sides of the flow, named the way the entry names them. */
export type Side = 'H' | 'worker'

/** Every role a flow needs.  ``H`` and ``worker`` drive steps; ``G``, ``U``,
 *  ``V`` and ``X`` sign *inside* the assembled chain and have no steps of their
 *  own -- what a page owes them is a view, not a button per step. */
export type Role = Side | 'G' | 'U' | 'V' | 'X'

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

/** One role the scenario needs, and what that scenario calls it. */
export interface RoleInfo {
  alias: Role
  name: string
}

/** One scenario the entry fixes, the intent fields its action takes, and the
 *  roles it needs.  All three are the trusted side's own, read not copied. */
export interface Scenario {
  profile: string
  intents: string[]
  roles: RoleInfo[]
}

export interface Scenarios {
  profiles: Scenario[]
}

export interface SubmitReply {
  operation_id: string
  challenge?: unknown
}

/** One thing waiting on a role that signs inside the chain. */
export interface Todo {
  role: Role
  id: string
  op: string
  profile: string
  domain: string
  claim: unknown
}

export interface Pending {
  profile: string
  todos: Todo[]
}

/** One request the page made, and what came back, kept for the timeline. */
export interface StepRecord {
  at: string
  side: string
  step: string
  ok: boolean
  detail: unknown
}
