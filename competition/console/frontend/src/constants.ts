/** Display labels the page shows.  The scenario list and each scenario's intent
 *  fields come from the console (which reads the entry's own table); only the
 *  Chinese wording lives here, and an unknown key falls back to the key itself. */

export const STEP_LABELS: Record<string, string> = {
  submit: '提交操作',
  package: '查看公开包',
  prepare: '准备 prepare',
  accept: '接受 accept',
  claim: '领取 claim',
  exec: '执行 exec',
  query: '查询 query',
  settle: '结算 settle',
  cancel: '取消 cancel',
  status: '状态 status',
  audit: '审计 audit',
}

export function stepLabel(step: string): string {
  return STEP_LABELS[step] ?? step
}

export const SCENARIO_LABELS: Record<string, string> = {
  'IND-DEMO-1': '工业 IND-DEMO-1',
  'PAY-1': '付款 PAY-1',
  'MED-DEMO-1': '医疗 MED-DEMO-1',
}

export function scenarioLabel(profile: string): string {
  return SCENARIO_LABELS[profile] ?? profile
}

export const INTENT_LABELS: Record<string, string> = {
  // 工业
  line_id: '产线',
  station_id: '工位',
  unit_id: '单元',
  batch_id: '批次',
  inspection_cycle: '检验周期',
  phase: '阶段',
  route: '路径',
  // 付款
  order_id: '订单号',
  payer: '付款方',
  payee: '收款方',
  amount_minor: '金额（分）',
  stage: '阶段',
  // 医疗
  synthetic_patient_id: '合成患者',
  encounter_id: '就诊',
  template_id: '模板',
}

export function intentLabel(key: string): string {
  return INTENT_LABELS[key] ?? key
}

/** The scenario fixes these values.  A made-up example can also be refused by
 *  the upstream schema, so the honest placeholder is the default, not a guess. */
export const INTENT_PLACEHOLDERS: Record<string, string> = {
  amount_minor: '整数，单位分；留空用默认值',
  inspection_cycle: '整数；留空用默认值',
}

export function intentPlaceholder(key: string): string {
  return INTENT_PLACEHOLDERS[key] ?? '留空用场景默认值'
}

/** What each role is, in plain words.  This is only the purpose beside the
 *  alias: the scenario's own name for the role (LINE_OPERATOR, FINANCE,
 *  MEDICAL_AUTHORIZER, ...) comes from the console and is shown as it is. */
/** The operation's scalar state, in the page's own words.  The code stays
 *  beside it so a trace or a log can still be matched. */
export const STATE_LABELS: Record<string, string> = {
  SUBMITTED: '已提交',
  STARTED: '进行中',
  SETTLED: '已结算',
  HALTED: '已中止',
  CANCELED: '已取消',
  DENIED: '已拒绝',
}

export function stateLabel(value: string): string {
  const label = STATE_LABELS[value]
  return label ? `${label} ${value}` : value
}

/** The authenticated view's field names. */
export const VIEW_LABELS: Record<string, string> = {
  acceptance_state: '接受状态',
  dispatch_state: '派发状态',
  effect_state: '效果状态',
  receipt_state: '回执状态',
  exec_consumed: '执行已消费',
  state: '操作状态',
  attempt_id: '尝试 id',
}

export function viewLabel(value: string): string {
  const label = VIEW_LABELS[value]
  return label ? `${label} · ${value}` : value
}

export const ROLE_LABELS: Record<string, string> = {
  H: '提出方',
  worker: '执行方',
  G: '签发方',
  U: '批准人',
  V: '复核人',
  X: '效果端',
}

export const ROLE_DUTIES: Record<string, string> = {
  H: '提交操作，逐步准备与接受',
  worker: '领取、执行、查询、结算',
  G: '签发 Permit',
  U: '批准 EXECUTE',
  V: '复核',
  X: '应答挑战，签执行端回执',
}

export function roleLabel(alias: string): string {
  return ROLE_LABELS[alias] ?? alias
}

export function roleDuty(alias: string): string {
  return ROLE_DUTIES[alias] ?? ''
}

/** The roles that drive steps.  The rest sign inside the chain, so a page shows
 *  them what is waiting rather than a button per step. */
export const STEPPED_ROLES: readonly string[] = ['H', 'worker']
