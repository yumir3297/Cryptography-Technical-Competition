/**
 * One page's worth of state, and the calls it makes.
 *
 * The store is deliberately flat: the scenarios the entry fixes, an operation
 * handle the page holds, the last authenticated view it read, and a timeline of
 * what was asked and what came back.  Nothing here decides which side may drive
 * a step -- that is the entry's caller list, and a refusal comes back under its
 * own rule name and is recorded as it is.
 */
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, reactive, watch } from 'vue'

import { consoleApi, DenyError } from './api'
import { roleLabel, stepLabel } from './constants'
import type { CallTrace } from './api'
import { newTrace, note } from './trace'
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
  /** False for an id restored from localStorage until the pool confirms it. */
  operationKnown: boolean
  /** Consecutive reads that did not show a restored id; one may be a lag. */
  attachMisses: number
  /** At least one operations read has succeeded, so an empty list is real. */
  operationsLoaded: boolean
  view: Record<string, unknown> | null
  log: StepRecord[]
  error: string
  busy: boolean
  submitting: boolean
  /** ``side:step`` of the one step in flight, if any.  A step can wait a long
   *  time on G/U/V/X, so it gets its own marker instead of freezing every
   *  button on the page -- the approvals have to stay clickable. */
  stepBusy: string
  /** Role/ticket of each decision in flight, so one person's yes does not
   *  disable the next role's panel. */
  deciding: Record<string, boolean>
  /** Steps this page has seen succeed for the attached operation. */
  done: string[]
  /** Follow a scenario that has a new waiting request until the operator picks
   *  one by hand; after that the sidebar is theirs. */
  follow: boolean
  /** Ids already in the pool when a submit started; a new row in the same
   *  scenario is this submit's candidate, even before its response returns. */
  submitBaseline: string[]
  /** When the last read answered, for the freshness line. */
  lastUpdated: Date | null
  /** A scenario other than the selected one has a request waiting.  The entry
   *  assembles one chain at a time, so a new submit while this is set queues
   *  behind it; the page says so instead of hanging silently. */
  waitingElsewhere: string
  /** The last pending read failed: keep the previous list and mark it stale. */
  pendingError: boolean
  /** The last operations read failed; the candidate list is stale too. */
  operationsError: boolean
  packageOpen: boolean
  packageBusy: boolean
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
  operationKnown: false,
  attachMisses: 0,
  operationsLoaded: false,
  view: null,
  log: [],
  error: '',
  busy: false,
  submitting: false,
  stepBusy: '',
  deciding: {},
  done: [],
  follow: true,
  submitBaseline: [],
  lastUpdated: null,
  waitingElsewhere: '',
  pendingError: false,
  operationsError: false,
  packageOpen: false,
  packageBusy: false,
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

// Two tabs share one pool.  The tab that did not write still has the old id in
// memory, so follow the storage event rather than letting the two drive
// different operations under the same visible page.
window.addEventListener('storage', (event) => {
  if (event.key !== 'zjj.operation') return
  const next = event.newValue ?? ''
  if (next === state.operationId) return
  state.operationId = next
  state.operationKnown = false
  state.view = null
  state.done = []
  record('H', next ? '另一标签切换当前操作' : '另一标签清空当前操作', true,
         { operation_id: next })
})

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

/** Run one call, keep its answer, and keep a refusal under its own rule name.
 *
 *  The call carries one trace id, and its measured duration is written beside the
 *  timeline entry: the timeline says a step was refused or passed, and this says
 *  how long the browser waited for that answer.  A server that took the time is
 *  then told apart from a browser that waited on its own poll.
 */
async function guard<T>(side: string, step: string, action: (trace: CallTrace) => Promise<T>,
                        quiet = false)
  : Promise<T | null> {
  const trace: CallTrace = { trace: newTrace() }
  const started = performance.now()
  state.error = ''
  try {
    const result = await action(trace)
    record(side, step, true, result)
    note({ kind: 'action', trace: trace.trace, side, step, ok: true,
           ms: performance.now() - started, call_ms: trace.ms })
    // The result card is below the fold on most desks; a toast is the one
    // receipt the person gets where they clicked.
    if (!quiet) {
      const read = ['status', 'audit', 'query'].includes(step)
      // A 200 can still be a no-op: exec twice answers UNKNOWN with a reason.
      const soft = result && typeof result === 'object'
        && ((result as Record<string, unknown>).state === 'UNKNOWN'
          || (result as Record<string, unknown>).reason)
      if (soft) {
        const reason = (result as Record<string, unknown>).reason
          || (result as Record<string, unknown>).state
        ElMessage.warning(`${roleLabel(side)} · ${stepLabel(step)} 未生效：${String(reason)}`)
      } else {
        ElMessage.success(`${roleLabel(side)} · ${stepLabel(step)} ${read ? '读取完成' : '通过'}`)
      }
    }
    return result
  } catch (error) {
    const code = codeOf(error)
    state.error = code
    record(side, step, false, { deny: code })
    note({ kind: 'action', trace: trace.trace, side, step, ok: false, deny: code,
           ms: performance.now() - started, call_ms: trace.ms })
    if (!quiet) ElMessage.error(`${roleLabel(side)} · ${stepLabel(step)} 被拒绝：${code}`)
    return null
  }
}

/** Remember a step the attached operation finished, for the step buttons. */
function markDone(step: string): void {
  if (!state.done.includes(step)) state.done.push(step)
}

/** A submit waits for the whole approval chain; its candidate may appear in
 *  the pool first.  Adopt that row so the page is not stuck on "(尚未提交)"
 *  while the submit request is still assembling. */
function adoptCandidate(): void {
  if (!state.submitting || state.operationId) return
  const fresh = state.operations.find(
    (row) => row.profile === state.profile
      && !state.submitBaseline.includes(row.operation_id),
  )
  if (!fresh) return
  state.operationId = fresh.operation_id
  state.operationKnown = true
  state.view = { state: fresh.state, stage: fresh.stage }
  state.done = []
  record('H', '候选出现，自动接手', true, { operation_id: fresh.operation_id })
}

/** Drop an id restored from localStorage that this instance no longer holds.
 *  A stale id must not leave every step button pointing at nothing. */
function checkAttached(): void {
  if (!state.operationId) return
  const found = state.operations.find((row) => row.operation_id === state.operationId)
  if (found) {
    state.operationKnown = true
    state.attachMisses = 0
    // A reload restores the id but starts on the first scenario; follow the
    // operation's own profile so the panels and the decision route agree.
    if (found.profile && found.profile !== state.profile) {
      state.profile = found.profile
    }
    // The row's own state drives "already settled / denied" even before a
    // status read.  A richer view from a status step is only replaced when the
    // row reaches a terminal state; otherwise the poll would erase its fields.
    const terminal = ['SETTLED', 'HALTED', 'CANCELED', 'DENIED']
    if (!state.view
        || (found.state && terminal.includes(found.state)
            && state.view.state !== found.state)) {
      state.view = { state: found.state, stage: found.stage }
    }
    return
  }
  // An empty list is a real answer once one read has succeeded; before that it
  // only means the page has not heard back yet.
  if (!state.operationsLoaded) return
  // A just-submitted id may reach the pool a poll later; only an id restored
  // from storage is checked, so a fresh submit is never dropped on the floor.
  if (state.operationKnown) return
  // The viewer's feed can lag the entry by one poll.  Two misses is a stale id.
  state.attachMisses += 1
  if (state.attachMisses < 2) return
  state.operationId = ''
  state.attachMisses = 0
  state.view = null
  state.done = []
  state.error = 'CONSOLE_OPERATION_UNKNOWN'
}

export const actions = {
  async refresh(): Promise<void> {
    if (state.busy) return
    const trace: CallTrace = { trace: newTrace() }
    const started = performance.now()
    state.busy = true
    state.error = ''
    try {
      const [status, scenarios] = await Promise.all([
        consoleApi.status(trace),
        consoleApi.scenarios(trace),
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
      let reached = false
      try {
        state.operations = (await consoleApi.operations(50, trace)).operations
        state.operationsLoaded = true
        state.operationsError = false
        reached = true
        adoptCandidate()
        // This may move the profile to the restored operation's own scenario.
        checkAttached()
      } catch {
        // A dead candidate route must not also throw away the roster or the
        // waiting-room read that follows it.
        state.operationsError = true
      }
      try {
        state.pending = state.profile ? await consoleApi.pending(state.profile, trace) : null
        state.pendingError = false
        reached = true
      } catch {
        state.pendingError = true
      }
      if (reached) state.lastUpdated = new Date()
      if (state.operationsError && state.pendingError) state.error = 'CONSOLE_UNREACHABLE'
      if (state.operationId && !state.log.length) {
        record('H', '恢复当前操作', true, { operation_id: state.operationId })
      }
    } catch (error) {
      state.error = codeOf(error)
    } finally {
      state.busy = false
      note({ kind: 'refresh', trace: trace.trace, ms: performance.now() - started,
             ok: !state.error })
    }
  },

  // Take one operation out of the instance's pool and make it the one this page
  // drives.  It may be one this page submitted, or one the agent delivered over
  // MCP -- the pool is the same, and the entry decides who may do each step.
  attach(operationId: string): void {
    const id = operationId.trim()
    if (!id || state.stepBusy) return
    // The panels and the approval routing both come from the scenario, so the
    // page follows the operation's own profile instead of whichever one happened
    // to be selected.  Otherwise a decision would travel to the wrong endpoint.
    const row = state.operations.find((entry) => entry.operation_id === id)
    if (row && row.profile) state.profile = row.profile
    state.operationId = id
    state.operationKnown = true
    state.attachMisses = 0
    state.view = row ? { state: row.state, stage: row.stage } : null
    state.done = []
    state.error = ''
    record('H', '接手操作', true, { operation_id: id })
    note({ kind: 'attach', operation_id: id })
  },

  /** Stop driving the attached operation.  Local only: the operation and its
   *  records stay in the instance; the page just stops pointing at it. */
  detach(): void {
    if (!state.operationId) return
    const id = state.operationId
    state.operationId = ''
    state.operationKnown = false
    state.attachMisses = 0
    state.view = null
    state.done = []
    state.error = ''
    record('H', '放弃当前操作', true, { operation_id: id })
  },

  async chooseScenario(profile: string): Promise<void> {
    // The sidebar picks the scenario.  Switching is a read: the watch above
    // resets the intent fields to the ones the newly chosen scenario takes, and
    // what is waiting is re-read under that scenario.  An operation belongs to
    // one scenario, so switching away from its scenario detaches it rather than
    // leaving the step buttons pointing at an operation the new panels cannot
    // describe (or route a decision to the wrong endpoint).
    if (state.operationId) {
      const row = state.operations.find((entry) => entry.operation_id === state.operationId)
      if (row && row.profile !== profile) {
        state.operationId = ''
        state.operationKnown = false
        state.view = null
        state.done = []
        ElMessage.info('已切换场景；原来的操作留在候选列表里，需要时可重新接手')
      }
    }
    state.profile = profile
    state.view = null
    // A click is a decision: stop following waiting rooms around after it.
    state.follow = false
    await actions.refreshPending()
  },

  async refreshPending(): Promise<void> {
    // A read of four endpoints rather than a step, so it is not recorded in the
    // timeline, and a role that is not up yet -- or was started without a waiting
    // room -- is simply not shown rather than reported as an error.
    if (!state.profile) return
    // This runs every three seconds on its own, so only a slow one is written:
    // what the trace is for is the poll that is still in flight when a person
    // presses a button, not the page being alive.
    const trace: CallTrace = { trace: newTrace() }
    const started = performance.now()
    let visited = 0
    try {
      // Ask for the scenario on screen, not whatever the console happens to
      // default to: the entry assembles the chain one scenario at a time, and the
      // two are not the same one for most of the run.  The two reads are kept
      // apart so a dead operations route is not reported as a dead waiting room.
      const [pendingResult, operationsResult] = await Promise.allSettled([
        consoleApi.pending(state.profile, trace),
        consoleApi.operations(50, trace),
      ])
      let pending: Pending | null = null
      if (operationsResult.status === 'fulfilled') {
        state.operations = operationsResult.value.operations
        state.operationsLoaded = true
        state.operationsError = false
        adoptCandidate()
        checkAttached()
      } else {
        // Keep the last list: "could not read" is not "nothing is there".
        state.operationsError = true
      }
      if (pendingResult.status === 'fulfilled') {
        pending = pendingResult.value
        state.pending = pending
        state.pendingError = false
      } else {
        state.pendingError = true
      }
      if (pendingResult.status === 'fulfilled' || operationsResult.status === 'fulfilled') {
        state.lastUpdated = new Date()
        // A successful read proves the transport is back; clear only a
        // connectivity banner, never a rule the entry named.
        if (['CONSOLE_UNREACHABLE', 'ENTRY_UNAVAILABLE', 'ENDPOINT_UNAVAILABLE',
             'ENTRY_ANSWER', 'CONSOLE_ANSWER'].includes(state.error)) {
          state.error = ''
        }
      } else {
        // Both reads failed: this really looks like the console backend is
        // gone, not just one role endpoint being briefly unavailable.
        state.error = 'CONSOLE_UNREACHABLE'
      }
      // The scenario a person has to look at moves on its own only while no
      // operation is attached.  Once one is, switching the sidebar under the
      // panels would make a decision travel to the new scenario's endpoint for
      // an operation that belongs to the old one -- so the page stays put.
      if (pending) {
        state.waitingElsewhere = ''
        if (!pending.todos.length) {
          for (const entry of state.scenarios) {
            if (entry.profile === state.profile) continue
            visited += 1
            let other: Pending
            try {
              other = await consoleApi.pending(entry.profile, trace)
            } catch {
              continue
            }
            if (!other.todos.length) continue
            // The entry assembles one chain at a time; while another scenario
            // waits, a new submit queues behind it.  Say where the work is
            // instead of letting the submit look hung.
            state.waitingElsewhere = entry.profile
            if (!state.operationId && state.follow) {
              state.profile = entry.profile
              state.pending = other
              state.waitingElsewhere = ''
            }
            break
          }
        }
      }
    } finally {
      note({ kind: 'poll', trace: trace.trace, ms: performance.now() - started,
             call_ms: trace.ms, others: visited,
             ok: !state.pendingError && !state.operationsError }, true)
    }
  },

  async decide(role: string, id: string, approve: boolean): Promise<void> {
    // A decision is a step, so it is recorded the way every other one is.  It
    // travels to the role's own endpoint; this page carries a yes or a no and
    // never a signature.  Only the ticket being answered is marked busy: the
    // step that is parked on a yes must not disable the button that gives it.
    if (!approve) {
      try {
        await ElMessageBox.confirm(
          `拒绝后这条签名请求会失败，正在等它的流程会停下。确定拒绝 ${role} 的请求？`,
          '拒绝签名',
          { type: 'warning', confirmButtonText: '确认拒绝', cancelButtonText: '返回' },
        )
      } catch {
        return
      }
    }
    const key = role + ':' + id
    if (state.deciding[key]) return
    state.deciding[key] = true
    try {
      await guard(role, approve ? '同意' : '拒绝', (trace) =>
        consoleApi.decide(state.profile, role, id, approve, trace),
      )
    } finally {
      delete state.deciding[key]
    }
    await actions.refreshPending()
  },

  async submit(): Promise<void> {
    if (state.submitting) return
    // Only the fields the operator actually filled: an empty box means "use the
    // fixed scenario's value", not "send the empty string".
    const intent = Object.fromEntries(
      Object.entries(state.intent).filter(([, value]) => value !== ''),
    )
    state.submitting = true
    state.submitBaseline = state.operations.map((row) => row.operation_id)
    ElMessage.info('已提交，正在装配审批链；需要放行时页面会提示')
    try {
      const reply = await guard('H', 'submit', (trace) =>
        consoleApi.submit(state.profile, intent, trace),
      )
      if (reply) {
        state.operationId = reply.operation_id
        state.operationKnown = true
        state.attachMisses = 0
        // The candidate was already adopted (with SUBMITTED) while the chain
        // assembled; do not blank the status card when the response lands.
        if (!state.view) state.view = { state: 'SUBMITTED' }
        state.done = []
      }
    } finally {
      state.submitting = false
      state.submitBaseline = []
    }
  },

  async step(side: Side, step: string): Promise<void> {
    if (!state.operationId) {
      state.error = 'CONSOLE_OPERATION'
      record(side, step, false, { deny: 'CONSOLE_OPERATION' })
      return
    }
    if (state.stepBusy) return
    if (step === 'cancel') {
      try {
        await ElMessageBox.confirm(
          '取消会终止这条操作，之后不能再用它继续执行；这不是“撤销上一步”。',
          '取消操作',
          { type: 'warning', confirmButtonText: '确认取消', cancelButtonText: '返回',
            confirmButtonClass: 'el-button--danger' },
        )
      } catch {
        return
      }
    }
    state.stepBusy = side + ':' + step
    try {
      const reply = await guard(side, step, (trace) =>
        consoleApi.step(side, state.operationId, step, trace),
      )
      // Every step answers with the operation's authenticated view; keeping it
      // means the status card moves as the flow does, not only after a manual
      // "状态" click.
      if (reply && typeof reply === 'object') {
        state.view = reply
        const soft = reply.state === 'UNKNOWN' || Boolean(reply.reason)
        if (!soft) markDone(step)
      }
    } finally {
      state.stepBusy = ''
    }
  },

  async showPackage(): Promise<void> {
    // A read, not a step: it does not change the operation, so it stays out of
    // the timeline (and its 170k-character body stays out of the page log).
    state.packageBusy = true
    state.error = ''
    try {
      const reply = await consoleApi.package()
      state.packageText = JSON.stringify(reply, null, 2)
      state.packageOpen = true
    } catch (error) {
      state.error = codeOf(error)
      ElMessage.error(`公开包读取失败：${state.error}`)
    } finally {
      state.packageBusy = false
    }
  },
}
