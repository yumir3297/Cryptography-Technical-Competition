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
import type { ConsoleStatus, Scenario, Side, StepRecord } from './types'

/** The steps the page offers each side.  Buttons, not authority. */
export const HOLDER_STEPS = ['prepare', 'accept', 'status', 'audit'] as const
export const WORKER_STEPS = ['claim', 'exec', 'query', 'settle', 'cancel'] as const

export interface ConsoleState {
  status: ConsoleStatus | null
  scenarios: Scenario[]
  profile: string
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

// A new scenario is a new operation's worth of fields: keep the ones the chosen
// scenario takes and drop the rest, so a stale field cannot be submitted.
watch(
  () => state.profile,
  (profile) => {
    const scenario = state.scenarios.find((entry) => entry.profile === profile)
    state.intent = Object.fromEntries((scenario?.intents ?? []).map((key) => [key, '']))
  },
)

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
      // Keep the operator's choice across a refresh; on the first load pick the
      // console's own default profile, falling back to whatever it offers.
      if (!scenarios.profiles.some((entry) => entry.profile === state.profile)) {
        const chosen =
          scenarios.profiles.find((entry) => entry.profile === status.profile) ??
          scenarios.profiles[0]
        state.profile = chosen ? chosen.profile : ''
      }
    } catch (error) {
      state.error = codeOf(error)
    } finally {
      state.busy = false
    }
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
