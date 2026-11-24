<script setup lang="ts">
import { computed } from 'vue'

import { roleLabel, stepLabel } from '../constants'
import { WORKER_STEPS, actions, currentRoles, state } from '../store'

// The worker is one capability rather than a scenario-bound role, so the name
// beside it comes from the console's own role row.
const roleName = computed(
  () => currentRoles.value.find((entry) => entry.alias === 'worker')?.name ?? 'WORKER',
)

const terminal = computed(() => ['SETTLED', 'HALTED', 'CANCELED', 'DENIED']
  .includes(String(state.view?.state ?? '')))

const nextStep = computed(() => {
  if (!state.operationId || terminal.value) return ''
  for (const step of ['claim', 'exec', 'settle']) {
    if (!state.done.includes(step)) return step
  }
  return state.done.includes('query') ? '' : 'query'
})
</script>

<template>
  <el-card shadow="never" class="panel">
    <template #header>
      <div class="card-head">
        <h2 class="card-title">{{ roleLabel('worker') }}</h2>
        <el-tag size="small" type="warning">{{ roleName }}</el-tag>
      </div>
    </template>

    <div class="stack">
      <div>
        <div class="muted">当前操作 id</div>
        <div class="mono">{{ state.operationId || '（尚未提交）' }}</div>
      </div>
      <p class="field-help">
        执行方不提交、不写业务状态；它领取、执行并结算提出方已经接受的操作，「查询 query」是只读读取。
      </p>
    </div>

    <el-divider content-position="left">流程步骤</el-divider>
    <div class="steps">
      <el-button
        v-for="step in WORKER_STEPS"
        :key="step"
        :type="step === 'cancel' ? 'danger'
          : state.done.includes(step) ? 'success' : undefined"
        :loading="state.stepBusy === 'worker:' + step"
        :disabled="!state.operationId || state.submitting || !!state.waitingElsewhere
          || !!(state.pending && state.pending.todos.length)
          || (terminal && step !== 'query')
          || (state.done.includes(step) && step !== 'query')
          || (!!state.stepBusy && state.stepBusy !== 'worker:' + step)"
        @click="actions.step('worker', step)"
      >
        <span v-if="state.done.includes(step)">✓ </span>{{ stepLabel(step) }}
      </el-button>
    </div>
    <p v-if="!state.operationId" class="field-help">先让提出方提交操作，或从候选里接手一条。</p>
    <p v-else-if="terminal" class="field-help">这条操作已经结束，只能查询或回到提出方读状态。</p>
    <p v-else-if="nextStep" class="field-help">
      下一步：{{ stepLabel(nextStep) }}。如果这一步停在签名上，去下方对应角色的面板点「同意」。
    </p>
    <p v-else class="field-help">执行方步骤已完成，可回提出方读取状态。</p>
  </el-card>
</template>

<style scoped>
.panel {
  height: 100%;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.steps {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.steps :deep(.el-button + .el-button) {
  margin-left: 0;
}
</style>
