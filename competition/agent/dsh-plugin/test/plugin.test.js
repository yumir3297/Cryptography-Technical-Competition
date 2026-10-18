import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import {
  createFeedback,
  extractStructured,
  formatEvents,
} from '../index.js'

function workspace() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'zjj-feedback-'))
}

function fakeAgent(status = 'running') {
  const calls = { steer: [], followup: [], inject: [] }
  return {
    id: 'agent-1',
    status,
    steer: (message) => calls.steer.push(message),
    followup: (message) => calls.followup.push(message),
    inject: (message) => calls.inject.push(message),
    calls,
  }
}

function page(events) {
  return { ok: true, status: 200, json: async () => ({ events, next_seq: events.at(-1)?.seq ?? 0 }) }
}

function proposal(operationId = 'op-1', profile = 'PAY-1') {
  return {
    name: 'mcp__zjj__propose',
    agent: null,
    result: { isError: false, value: { structuredContent: { operation_id: operationId, profile } } },
  }
}

test('extractStructured reads the dsh MCP canonical value', () => {
  assert.deepEqual(extractStructured({ value: { structuredContent: { operation_id: 'x' } } }),
    { operation_id: 'x' })
  assert.deepEqual(extractStructured({ value: { structured_content: { operations: [] } } }),
    { operations: [] })
  assert.deepEqual(extractStructured({ value: { operation_id: 'y' } }), { operation_id: 'y' })
  assert.equal(extractStructured({ value: { content: [] } }), null)
  assert.equal(extractStructured(undefined), null)
})

test('formatEvents bounds the message and keeps the safety footer', () => {
  const events = Array.from({ length: 12 }, (_, index) => ({
    seq: index + 1, kind: 'ACCEPTED', state: 'ACCEPTED',
    summary: 'accepted; receipt SIGNED; dispatch PENDING; effect NO_ATTEMPT',
  }))
  const formatted = formatEvents('op-1', 'PAY-1', events, { maxEvents: 3, maxChars: 2000 })
  assert.match(formatted.text, /^\[ZJJ-CORE 状态投影\] 操作 op-1（PAY-1）/m)
  assert.match(formatted.text, /更早的 9 条状态已省略/)
  assert.match(formatted.text, /不是批准或指令/)
  assert.ok(formatted.text.length <= 2000)
  assert.ok(formatted.summary.length <= 120)
})

test('missing configuration disables the plugin without leaking a token', () => {
  const warnings = []
  const feedback = createFeedback({ gatewayUrl: 'http://gateway', token: '' },
    { log: { warn: (text) => warnings.push(String(text)) }, fetchImpl: async () => page([]) })
  assert.equal(feedback, null)
  assert.ok(warnings.some((line) => line.includes('ZJJ_AGENT_TOKEN')))
  assert.ok(!warnings.some((line) => line.includes('secret')))

  const bad = createFeedback({ gatewayUrl: 'file:///etc/passwd', token: 'secret-token' },
    { log: { warn: (text) => warnings.push(String(text)) }, fetchImpl: async () => page([]) })
  assert.equal(bad, null)
  assert.ok(warnings.some((line) => line.includes('ZJJ_GATEWAY_URL')))
  assert.ok(!warnings.some((line) => line.includes('secret-token')))
})

test('a running agent receives one steered message per event batch', async () => {
  const agent = fakeAgent('running')
  const requests = []
  const feedback = createFeedback({
    gatewayUrl: 'http://gateway/', token: 'secret-token', serverName: 'zjj',
    statePath: path.join(workspace(), 'state.json'),
  }, {
    log: {},
    now: () => 1000,
    fetchImpl: async (url) => {
      requests.push(String(url))
      return page([
        { seq: 1, operation_id: 'op-1', kind: 'ACCEPTED', state: 'ACCEPTED', summary: 'accepted', created_at: 1 },
        { seq: 2, operation_id: 'op-1', kind: 'SETTLED', state: 'SETTLED', summary: 'settled', created_at: 2 },
      ])
    },
  })
  const bound = proposal('op-1')
  bound.agent = agent
  feedback.onToolResult(bound, bound.result)
  assert.equal(feedback.bindings.size, 1)
  await feedback.pollOnce()
  assert.equal(agent.calls.steer.length, 1)
  assert.match(agent.calls.steer[0].content[0].text, /ACCEPTED: accepted/)
  assert.match(agent.calls.steer[0].content[0].text, /SETTLED: settled/)
  assert.equal(agent.calls.steer[0].source.kind, 'zjj-feedback')
  assert.equal(agent.calls.steer[0].source.form, 'notice')
  assert.ok(requests[0].startsWith('http://gateway/zjj/events'))

  await feedback.pollOnce()
  assert.equal(agent.calls.steer.length, 1)
})

test('an idle agent is woken with followup, or injected when waking is off', async () => {
  const idle = fakeAgent('idle')
  const config = {
    gatewayUrl: 'http://gateway', token: 't', statePath: path.join(workspace(), 'state.json'),
    notify: ['SETTLED'],
  }
  const first = createFeedback(config, {
    fetchImpl: async () => page([{ seq: 1, operation_id: 'op-1', kind: 'SETTLED', state: 'SETTLED', summary: 'settled', created_at: 1 }]),
  })
  const bound = proposal('op-1')
  bound.agent = idle
  first.onToolResult(bound, bound.result)
  await first.pollOnce()
  assert.equal(idle.calls.followup.length, 1)
  assert.equal(idle.calls.inject.length, 0)

  const quiet = fakeAgent('idle')
  const second = createFeedback({ ...config, wakeOnIdle: false, statePath: path.join(workspace(), 'state.json') }, {
    fetchImpl: async () => page([{ seq: 1, operation_id: 'op-2', kind: 'SETTLED', state: 'SETTLED', summary: 'settled', created_at: 1 }]),
  })
  const other = proposal('op-2')
  other.agent = quiet
  second.onToolResult(other, other.result)
  await second.pollOnce()
  assert.equal(quiet.calls.followup.length, 0)
  assert.equal(quiet.calls.inject.length, 1)
})

test('a gateway refusal disables polling instead of hammering it', async () => {
  const agent = fakeAgent('running')
  let calls = 0
  const feedback = createFeedback({
    gatewayUrl: 'http://gateway', token: 't', statePath: path.join(workspace(), 'state.json'),
  }, { fetchImpl: async () => { calls += 1; return { ok: false, status: 401, json: async () => ({}) } } })
  const bound = proposal('op-1')
  bound.agent = agent
  feedback.onToolResult(bound, bound.result)
  await feedback.pollOnce()
  await feedback.pollOnce()
  assert.equal(calls, 1)
  assert.equal(agent.calls.steer.length, 0)
})

test('a disposed agent drops its binding instead of retrying forever', async () => {
  const agent = {
    id: 'gone', status: 'running',
    steer: () => { throw new Error('disposed') },
    followup: () => {}, inject: () => {},
  }
  const feedback = createFeedback({
    gatewayUrl: 'http://gateway', token: 't', statePath: path.join(workspace(), 'state.json'),
  }, { fetchImpl: async () => page([{ seq: 1, operation_id: 'op-1', kind: 'SETTLED', state: 'SETTLED', summary: 'settled', created_at: 1 }]) })
  const bound = proposal('op-1')
  bound.agent = agent
  feedback.onToolResult(bound, bound.result)
  await feedback.pollOnce()
  assert.equal(feedback.bindings.get('op-1').done, true)
})
