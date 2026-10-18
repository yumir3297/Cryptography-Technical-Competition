/** Display labels the page shows.  The scenario list and each scenario's intent
 *  fields come from the console (which reads the entry's own table); only the
 *  Chinese wording lives here, and an unknown key falls back to the key itself. */

export const STEP_LABELS: Record<string, string> = {
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

/** What each role is, in plain words.  This is only the purpose beside the
 *  alias: the scenario's own name for the role (LINE_OPERATOR, FINANCE,
 *  MEDICAL_AUTHORIZER, ...) comes from the console and is shown as it is. */
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
