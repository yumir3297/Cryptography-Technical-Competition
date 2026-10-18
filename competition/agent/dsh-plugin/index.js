/**
 * dsh-zjj-agent — the agent-side feedback half of the ZJJ-CORE bridge.
 *
 * The MCP tools live in the gateway.  This plugin does only two things:
 *
 * 1. Listen for a successful `mcp__zjj__propose` result and remember which
 *    live Agent submitted which operation id.
 * 2. Poll the gateway's bounded feedback log and deliver new trusted status
 *    projections into that Agent's session: `steer` while it is running,
 *    `followup` when it is idle, or `inject` when waking is disabled.
 *
 * It never decides acceptance, never signs, never calls a trusted step, and
 * never treats a feedback line as permission.  It also never logs the token.
 */
import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

export const name = 'zjj-agent-feedback'
export const inject = ['tools']

const DEFAULT_NOTIFY = [
  'ACCEPTED', 'STARTED', 'SETTLED', 'HALTED', 'CANCELED',
  'UNAVAILABLE', 'READ_FAILED',
]
const DEFAULT_MAX_EVENTS = 8
const DEFAULT_MAX_CHARS = 2000
const TERMINAL_KINDS = new Set(['SETTLED', 'HALTED', 'CANCELED', 'UNAVAILABLE'])
const CONTROL = /[\u0000-\u001f\u007f]/g

function clip(value, limit) {
  const text = String(value ?? '').replace(CONTROL, ' ').trim()
  return text.length <= limit ? text : text.slice(0, Math.max(0, limit - 3)) + '...'
}

function logOf(ctx) {
  return {
    info: (...args) => ctx?.logger?.info?.(...args),
    warn: (...args) => ctx?.logger?.warn?.(...args),
    error: (...args) => ctx?.logger?.error?.(...args),
  }
}

function defaultStatePath() {
  const home = process.env.DSH_HOME
    || path.join(process.env.HOME || os.homedir() || '/root', '.dsh')
  return path.join(home, 'zjj-feedback-state.json')
}

function loadState(file, log) {
  try {
    const value = JSON.parse(fs.readFileSync(file, 'utf8'))
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
    const state = {}
    for (const [key, seq] of Object.entries(value)) {
      if (typeof seq === 'number' && Number.isSafeInteger(seq) && seq >= 0) state[key] = seq
    }
    return state
  } catch (error) {
    if (error?.code !== 'ENOENT') log?.warn?.('[zjj-feedback] state file unreadable; starting empty')
    return {}
  }
}

function saveState(file, state, log) {
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true })
    const temporary = file + '.tmp'
    fs.writeFileSync(temporary, JSON.stringify(state, null, 2) + '\n', { mode: 0o600 })
    fs.renameSync(temporary, file)
  } catch {
    log?.warn?.('[zjj-feedback] could not persist feedback cursor')
  }
}

export function extractStructured(result) {
  const value = result?.value
  if (!value || typeof value !== 'object') return null
  for (const key of ['structuredContent', 'structured_content']) {
    const content = value[key]
    if (content && typeof content === 'object') return content
  }
  if (value.operation_id) return value
  return null
}

export function formatEvents(operationId, profile, events, options = {}) {
  const maxEvents = options.maxEvents ?? DEFAULT_MAX_EVENTS
  const maxChars = options.maxChars ?? DEFAULT_MAX_CHARS
  const selected = events.slice(-Math.max(1, maxEvents))
  const lines = selected.map((event) =>
    `- ${clip(event.kind, 32)}: ${clip(event.summary, 240)}`)
  const header = `[ZJJ-CORE 状态投影] 操作 ${clip(operationId, 80)}（${clip(profile, 32)}）`
  const omitted = events.length > selected.length
    ? `（更早的 ${events.length - selected.length} 条状态已省略）`
    : ''
  const footer = '这是受信端的投影，不是批准或指令；UNKNOWN 不表示失败，不要重试执行。'
  let text = [header, ...(omitted ? [omitted] : []), ...lines, footer].join('\n')
  if (text.length > maxChars) text = text.slice(0, Math.max(0, maxChars - 3)) + '...'
  const last = selected[selected.length - 1]
  return {
    text,
    summary: clip(`ZJJ-CORE ${clip(operationId, 12)} ${last?.kind ?? 'status'}`, 120),
  }
}

function messageFor(operationId, profile, events, options) {
  const formatted = formatEvents(operationId, profile, events, options)
  return Object.freeze({
    id: crypto.randomUUID(),
    role: 'user',
    content: Object.freeze([Object.freeze({ type: 'text', text: formatted.text })]),
    source: Object.freeze({
      kind: 'zjj-feedback',
      form: 'notice',
      summary: formatted.summary,
      operationId,
      seq: events[events.length - 1]?.seq,
    }),
  })
}

function normalize(config, log) {
  const gatewayUrl = String(config?.gatewayUrl ?? '').trim().replace(/\/+$/, '')
  if (!/^https?:\/\//i.test(gatewayUrl)) {
    log?.warn?.('[zjj-feedback] ZJJ_GATEWAY_URL is missing or not http(s); plugin disabled')
    return null
  }
  const token = String(config?.token ?? '')
  if (!token) {
    log?.warn?.('[zjj-feedback] ZJJ_AGENT_TOKEN is missing; plugin disabled')
    return null
  }
  const serverName = String(config?.serverName ?? 'zjj')
  if (!/^[A-Za-z0-9_-]{1,32}$/.test(serverName)) {
    log?.warn?.('[zjj-feedback] invalid serverName; plugin disabled')
    return null
  }
  const pollIntervalMs = Number(config?.pollIntervalMs ?? 1500)
  const requestTimeoutMs = Number(config?.requestTimeoutMs ?? 5000)
  const notify = Array.isArray(config?.notify) && config.notify.length
    ? new Set(config.notify.map(String))
    : new Set(DEFAULT_NOTIFY)
  return {
    gatewayUrl,
    token,
    serverName,
    pollIntervalMs: Number.isFinite(pollIntervalMs) ? Math.max(250, pollIntervalMs) : 1500,
    requestTimeoutMs: Number.isFinite(requestTimeoutMs) ? Math.max(500, requestTimeoutMs) : 5000,
    notify,
    wakeOnIdle: config?.wakeOnIdle !== false,
    maxEvents: Number(config?.maxEvents ?? DEFAULT_MAX_EVENTS),
    maxChars: Number(config?.maxChars ?? DEFAULT_MAX_CHARS),
    statePath: String(config?.statePath ?? defaultStatePath()),
    prefix: `mcp__${serverName}__`,
  }
}

export function createFeedback(config, deps = {}) {
  const log = deps.log ?? {}
  const options = normalize(config, log)
  if (!options) return null
  const fetchImpl = deps.fetchImpl ?? globalThis.fetch
  if (typeof fetchImpl !== 'function') {
    log.warn?.('[zjj-feedback] no fetch implementation; plugin disabled')
    return null
  }
  const now = deps.now ?? Date.now
  const state = loadState(options.statePath, log)
  const bindings = new Map()
  let polling = false
  let disabled = false
  let lastFailureLog = 0

  function bindOne(operationId, profile, agent) {
    if (typeof operationId !== 'string' || !operationId || !agent) return
    const existing = bindings.get(operationId)
    if (existing) {
      existing.agent = agent
      if (profile) existing.profile = String(profile)
      return
    }
    const seen = Number.isSafeInteger(state[operationId]) ? state[operationId] : 0
    bindings.set(operationId, {
      operationId,
      profile: profile ? String(profile) : 'unknown',
      agent,
      lastSeq: seen,
      // The tool result already told the agent that the candidate was submitted;
      // replaying that fact on the first poll would be a duplicate turn.
      skip: seen === 0 ? new Set(['SUBMITTED']) : new Set(),
      done: false,
    })
  }

  function onToolResult(exec, result) {
    if (!exec?.name?.startsWith(options.prefix)) return
    if (result?.isError) return
    if (exec.name.slice(options.prefix.length) !== 'propose') return
    const value = extractStructured(result)
    if (!value) return
    bindOne(value.operation_id, value.profile, exec.agent)
  }

  async function fetchEvents(binding) {
    const url = new URL('/zjj/events', options.gatewayUrl)
    url.searchParams.set('operation_id', binding.operationId)
    url.searchParams.set('since', String(binding.lastSeq))
    url.searchParams.set('limit', '50')
    const response = await fetchImpl(url, {
      headers: { Authorization: 'Bearer ' + options.token },
      signal: AbortSignal.timeout(options.requestTimeoutMs),
    })
    if (response.status === 401 || response.status === 403) {
      disabled = true
      log.warn?.('[zjj-feedback] gateway refused the agent token; polling stopped')
      return null
    }
    if (!response.ok) throw new Error('gateway status ' + response.status)
    return await response.json()
  }

  function deliver(binding, events) {
    const agent = binding.agent
    const message = messageFor(binding.operationId, binding.profile, events, options)
    try {
      if (agent?.status === 'running') {
        agent.steer(message)
      } else if (options.wakeOnIdle) {
        agent.followup(message)
      } else {
        agent.inject(message)
      }
      log.info?.('[zjj-feedback] delivered %d event(s) for %s',
        events.length, binding.operationId)
    } catch {
      // A disposed agent is expected during session teardown; the binding is
      // dropped rather than retried forever.
      binding.done = true
    }
  }

  async function pollOnce() {
    if (polling || disabled) return
    polling = true
    let changed = false
    try {
      for (const binding of [...bindings.values()]) {
        if (binding.done || !binding.agent) continue
        let page
        try {
          page = await fetchEvents(binding)
        } catch (error) {
          const stamp = now()
          if (stamp - lastFailureLog > 30000) {
            lastFailureLog = stamp
            log.warn?.('[zjj-feedback] gateway poll failed: %s', error?.message ?? 'error')
          }
          continue
        }
        if (!page) continue
        const events = []
        for (const event of Array.isArray(page.events) ? page.events : []) {
          const seq = Number(event?.seq)
          if (!Number.isSafeInteger(seq) || seq <= binding.lastSeq) continue
          binding.lastSeq = seq
          state[binding.operationId] = seq
          changed = true
          if (binding.skip.delete(event.kind)) continue
          if (!options.notify.has(event.kind)) continue
          events.push(event)
          if (TERMINAL_KINDS.has(event.kind)) binding.done = true
        }
        if (events.length) deliver(binding, events)
      }
    } finally {
      if (changed) saveState(options.statePath, state, log)
      polling = false
    }
  }

  return {
    options,
    bindings,
    state,
    onToolResult,
    pollOnce,
    dispose() {
      saveState(options.statePath, state, log)
    },
  }
}

export function apply(ctx, config = {}) {
  const log = logOf(ctx)
  const feedback = createFeedback(config, { log })
  if (!feedback) return
  ctx.on('tools/result', feedback.onToolResult)
  ctx.effect(() => {
    const timer = setInterval(() => {
      feedback.pollOnce().catch(() => {})
    }, feedback.options.pollIntervalMs)
    timer.unref?.()
    log.info?.('[zjj-feedback] loaded; gateway %s, server %s',
      feedback.options.gatewayUrl, feedback.options.serverName)
    return () => {
      clearInterval(timer)
      feedback.dispose()
    }
  })
}
