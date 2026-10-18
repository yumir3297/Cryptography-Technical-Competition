import type { ObservationEvent } from './types'

/**
 * One node of the protocol's step chain, as the display draws it.
 *
 * The chain is the repository's own step table (`competition.server.service.STEPS`)
 * plus the two things the entry publishes around it: the candidate submission and
 * the Resolver's assembly.  Nothing here is invented -- every node is landed on by
 * a ``kind`` the entry actually publishes, or by the ``step`` name it puts in
 * ``detail``.
 */
export interface ChainNode {
  key: string
  label: string
  side: string
  /** Step names (from ``detail.step``) that belong to this node. */
  steps: string[]
  /** Event kinds that belong to this node. */
  kinds: string[]
}

export const CHAIN: ChainNode[] = [
  { key: 'submit', label: '提交候选', side: '外部调用方',
    steps: [], kinds: ['CANDIDATE_SUBMITTED'] },
  { key: 'assemble', label: '装配与授权核验', side: 'Resolver',
    steps: [], kinds: ['CHAIN_ASSEMBLED', 'AUTHORIZED_GUARD', 'PUBLICATION'] },
  { key: 'prepare', label: 'prepare 准备', side: 'H',
    steps: ['prepare'], kinds: ['PREPARED'] },
  { key: 'accept', label: 'accept 接受', side: 'H',
    steps: ['accept'], kinds: ['ACCEPT_COMMITTED'] },
  { key: 'claim', label: 'claim 领取', side: 'worker',
    steps: ['claim'], kinds: ['CLAIMED'] },
  { key: 'exec', label: 'exec 执行', side: 'worker / 工具',
    steps: ['exec', 'query'], kinds: ['EXEC_DISPATCHED', 'QUERY_DISPATCHED', 'TOOL_RESPONDED'] },
  { key: 'settle', label: 'settle 结算', side: 'worker',
    steps: ['settle', 'cancel'], kinds: ['SETTLED', 'CANCELED'] },
  { key: 'status', label: 'status 读取投影', side: 'H',
    steps: ['status', 'audit'], kinds: ['READ_PROJECTED'] },
]

// Registration and bootstrap events are published to the same face, but they are
// not a step of any flow; the chain must not jump to a node because of them.
const BOOTSTRAP = new Set([
  'W_BOOTSTRAP', 'W_RESOURCE', 'W_TOOL', 'CONTROL_PUBLISHED', 'COVERAGE_INITIALIZED',
])

const BY_KIND = new Map<string, number>()
const BY_STEP = new Map<string, number>()
CHAIN.forEach((node, index) => {
  for (const kind of node.kinds) BY_KIND.set(kind, index)
  for (const step of node.steps) BY_STEP.set(step, index)
})

/** The chain node one event lands on, or -1 when it is not a step of the flow. */
export function stageOf(event: ObservationEvent): number {
  if (BOOTSTRAP.has(event.kind)) return -1
  const step = event.detail && event.detail['step']
  if (step && BY_STEP.has(step)) return BY_STEP.get(step) as number
  return BY_KIND.has(event.kind) ? (BY_KIND.get(event.kind) as number) : -1
}

export interface Progress {
  /** The furthest node reached, or -1 when nothing has moved yet. */
  index: number
  /** Whether the run ended in a trusted contradiction or a cancel. */
  failed: boolean
  /** The step name the entry last named, when it named one. */
  step: string | null
}

/** Where one operation's flow has got to, from its own committed steps. */
export function progressOf(events: ObservationEvent[]): Progress {
  let index = -1
  let failed = false
  let step: string | null = null
  for (const event of events) {
    if (event.kind === 'HALTED' || event.kind === 'CANCELED') failed = true
    index = Math.max(index, stageOf(event))
    const named = event.detail && event.detail['step']
    if (named) step = named
  }
  return { index, failed, step }
}

/** Whether one event is a step of the flow at all, bootstrap aside. */
export function isFlowEvent(event: ObservationEvent): boolean {
  return stageOf(event) >= 0
}
