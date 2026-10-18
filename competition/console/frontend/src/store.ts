/**
 * One page's worth of state, and the calls it makes.
 *
 * The store is deliberately flat: the scenarios the entry fixes, an operation
 * handle the page holds, the last authenticated view it read, and a timeline of
 * what was asked and what came back.  Nothing here decides which side may drive
 * a step -- that is the entry's caller list, and a refusal comes back under its
 * own rule name and is recorded as it is.
 */
import { computed, reactive, watch } from 'vue'

import { consoleApi, DenyError } from './api'
import type {
  ConsoleStatus,
  OperationRow,
  Pending,
  Scenario,
  Side,
  StepRecord,
} from './types'

/** The steps the page offers each side.  Buttons, not authority. */
export const HOLDER_STEPS = ['prepare', 'accept', 'status', 'audit'] as const
export const WORKER_STEPS = ['claim', 'exec', 'query', 'settle', 'cancel'] as const

export interface ConsoleState {
  status: ConsoleStatus | null
  scenarios: Scenario[]
  profile: string
  pending: Pending | null
  operations: OperationRow[]
  intent: Record<string, string>
  operationId: string
  view: Record<string, unknown> | null
  log: StepRecord[]
  error: string
  busy: boolean
  packageOpen: boolean
  packageText: string
}

export const state = reactive<ConsoleState>({
  status: null,
  scenarios: [],
  profile: '',
  pending: null,
  operations: [],
  intent: {},
  operationId: '',
  view: null,
  log: [],
  error: '',
  busy: false,
  packageOpen: false,
  packageText: '',
})

/** The intent fields of the scenario currently chosen, from the console. */
export const currentIntents = computed(
  () => state.scenarios.find((entry) => entry.profile === state.profile)?.intents ?? [],
)

/** The roles of the scenario currently chosen, in the order the console lists
 *  them: the two that drive steps first, then the four that sign inside the
 *  chain.  The page keys its panels on the alias and shows the scenario's own
 *  name beside it. */
export const currentRoles = computed(
  () => state.scenarios.find((entry) => entry.profile === state.profile)?.roles ?? [],
)

/** What is waiting on one role, from the last read.  A read, not a step: the
 *  page shows it the same way it shows the roster. */
export function todosFor(role: string) {
  return (state.pending?.todos ?? []).filter((todo) => todo.role === role)
}

// A new scenario is a new operation's worth of fields: keep the ones the chosen
// scenario takes and drop the rest, so a stale field cannot be submitted.
watch(
  () => state.profile,
  (profile) => {
    const scenario = state.scenarios.find((entry) => entry.profile === profile)
    state.intent = Object.fromEntries((scenario?.intents ?? []).map((key) => [key, '']))
  },
)

// The operation being driven belongs to the instance, not to this page's memory:
// keeping the id across a reload means a status refresh does not lose the handle
// that was picked out of the shared pool.
watch(
  () => state.operationId,
  (id) => {
    if (id) window.localStorage.setItem('zjj.operation', id)
    else window.localStorage.removeItem('zjj.operation')
  },
)

state.operationId = window.localStorage.getItem('zjj.operation') ?? ''

function now(): string {
  return new Date().toLocaleTimeString('zh-CN', { hour12: false })
}

function codeOf(error: unknown): string {
  if (error instanceof DenyError) return error.code
  return error instanceof Error ? error.message : String(error)
}

function record(side: string, step: string, ok: boolean, detail: unknown): void {
  state.log.unshift({ at: now(), side, step, ok, detail })
}

/** Run one call, keep its answer, and keep a refusal under its own rule name. */
async function guard<T>(side: string, step: string, action: () => Promise<T>): Promise<T | null> {
  state.busy = true
  state.error = ''
  try {
    const result = await action()
    record(side, step, true, result)
    return result
  } catch (error) {
    const code = codeOf(error)
    state.error = code
    record(side, step, false, { deny: code })
    return null
  } finally {
    state.busy = false
  }
}

export const actions = {
  async refresh(): Promise<void> {
    state.busy = true
    state.error = ''
    try {
      const [status, scenarios] = await Promise.all([
        consoleApi.status(),
        consoleApi.scenarios(),
      ])
      state.status = status
      state.scenarios = scenarios.profiles
      // Keep the operator's choice across a refresh; on the first load, start
      // where the work starts.  The entry assembles the chain in the order the
      // console lists the scenarios, so the first one is where the first request
      // to a person appears -- landing on the console's own default instead opens
      // a scene that is still empty and looks like nothing is happening.
      if (!scenarios.profiles.some((entry) => entry.profile === state.profile)) {
        state.profile = scenarios.profiles[0]?.profile ?? ''
      }
      state.pending = state.profile ? await consoleApi.pending(state.profile) : null
      state.operations = (await consoleApi.operations()).operations
    } catch (error) {
      state.error = codeOf(error)
    } finally {
      state.busy = false
    }
  },

  // Take one operation out of the instance's pool and make it the one this page
  // drives.  It may be one this page submitted, or one the agent delivered over
  // MCP -- the pool is the same, and the entry decides who may do each step.
  attach(operationId: string): void {
    const id = operationId.trim()
    if (!id) return
    state.operationId = id
    state.view = null
    record('H', '接手操作', true, { operation_id: id })
  },

  async chooseScenario(profile: string): Promise<void> {
    // The sidebar picks the scenario.  Switching is a read: the watch above
    // resets the intent fields to the ones the newly chosen scenario takes, and
    // what is waiting is re-read under that scenario.
    state.profile = profile
    state.view = null
    await actions.refreshPending()
  },

  async refreshPending(): Promise<void> {
    // A read of four endpoints rather than a step, so it is not recorded in the
    // timeline, and a role that is not up yet -- or was started without a waiting
    // room -- is simply not shown rather than reported as an error.
    if (!state.profile) return
    try {
      // Ask for the scenario on screen, not whatever the console happens to
      // default to: the entry assembles the chain one scenario at a time, and the
      // two are not the same one for most of the run.
      const [pending, operations] = await Promise.all([
        consoleApi.pending(state.profile),
        consoleApi.operations(),
      ])
      state.operations = operations.operations
      state.pending = pending
      // The scenario a person has to look at moves on its own, as the entry
      // finishes one and starts the next.  Follow it, rather than making them
      // notice and click the sidebar: an empty page while something waits in
      // another scenario reads exactly like nothing happening at all.
      if (!pending.todos.length) {
        for (const entry of state.scenarios) {
          if (entry.profile === state.profile) continue
          const other = await consoleApi.pending(entry.profile)
          if (other.todos.length) {
            state.profile = entry.profile
            state.pending = other
            break
          }
        }
      }
    } catch {
      state.pending = null
    }
  },

  async decide(role: string, id: string, approve: boolean): Promise<void> {
    // A decision is a step, so it is recorded the way every other one is.  It
    // travels to the role's own endpoint; this page carries a yes or a no and
    // never a signature.
    await guard(role, approve ? '同意' : '拒绝', () =>
      consoleApi.decide(state.profile, role, id, approve),
    )
    await actions.refreshPending()
  },

  async submit(): Promise<void> {
    // Only the fields the operator actually filled: an empty box means "use the
    // fixed scenario's value", not "send the empty string".
    const intent = Object.fromEntries(
      Object.entries(state.intent).filter(([, value]) => value !== ''),
    )
    const reply = await guard('H', 'submit', () => consoleApi.submit(state.profile, intent))
    if (reply) {
      state.operationId = reply.operation_id
      state.view = null
    }
  },

  async step(side: Side, step: string): Promise<void> {
    if (!state.operationId) {
      state.error = 'CONSOLE_OPERATION'
      record(side, step, false, { deny: 'CONSOLE_OPERATION' })
      return
    }
    const reply = await guard(side, step, () =>
      consoleApi.step(side, state.operationId, step),
    )
    if (reply && (step === 'status' || step === 'audit')) {
      state.view = reply
    }
  },

  async showPackage(): Promise<void> {
    const reply = await guard('H', 'package', () => consoleApi.package())
    if (reply !== null) {
      state.packageText = JSON.stringify(reply, null, 2)
      state.packageOpen = true
    }
  },
}
