<script setup lang="ts">
import { computed } from 'vue'

import { intentLabel, intentPlaceholder, roleLabel, stepLabel } from '../constants'
import { HOLDER_STEPS, actions, currentIntents, currentRoles, state } from '../store'

// The scenario's own name for this role (HOLDER in all three), read from the
// console rather than kept here.
const roleName = computed(
  () => currentRoles.value.find((entry) => entry.alias === 'H')?.name ?? 'HOLDER',
)

const terminal = computed(() => ['SETTLED', 'HALTED', 'CANCELED', 'DENIED']
  .includes(String(state.view?.state ?? '')))

// The two steps this side owes the flow.  Status and audit are reads, not the
// main path, so they stay available but are not called "next".
const nextStep = computed(() => {
  if (!state.operationId || terminal.value) return ''
  if (!state.done.includes('prepare')) return 'prepare'
  if (!state.done.includes('accept')) return 'accept'
  return ''
})
</script>

<template>
  <el-card shadow="never" class="panel">
    <template #header>
      <div class="card-head">
        <h2 class="card-title">{{ roleLabel('H') }}</h2>
        <el-tag size="small" type="info">{{ roleName }}</el-tag>
      </div>
    </template>

    <!-- The primary action stays above the long scenario form: on 1280×800
         and below, putting it under seven fields pushed it off the first
         screen. -->
    <div class="actions">
      <el-button
        type="primary"
        :loading="state.submitting"
        :disabled="!!state.stepBusy || !!state.waitingElsewhere
          || !!(state.pending && state.pending.todos.length)"
        @click="actions.submit"
      >
        提交操作
      </el-button>
      <el-button text :loading="state.packageBusy" @click="actions.showPackage">
        查看公开包
      </el-button>
    </div>

    <el-form label-width="96px" label-position="left">
      <el-form-item v-for="key in currentIntents" :key="key" :label="intentLabel(key)">
        <el-input v-model="state.intent[key]" :placeholder="intentPlaceholder(key)" clearable />
      </el-form-item>
    </el-form>
    <p class="field-help">留空的字段沿用固定场景默认值，只填需要覆盖的。</p>

    <el-divider content-position="left">流程步骤</el-divider>
    <div class="steps">
      <el-button
        v-for="step in HOLDER_STEPS"
        :key="step"
        :type="state.done.includes(step) ? 'success' : undefined"
        :loading="state.stepBusy === 'H:' + step"
        :disabled="!state.operationId || state.submitting || !!state.waitingElsewhere
          || !!(state.pending && state.pending.todos.length)
          || (terminal && !['status', 'audit'].includes(step))
          || (state.done.includes(step) && !['status', 'audit'].includes(step))
          || (!!state.stepBusy && state.stepBusy !== 'H:' + step)"
        @click="actions.step('H', step)"
      >
        <span v-if="state.done.includes(step)">✓ </span>{{ stepLabel(step) }}
      </el-button>
    </div>
    <p v-if="!state.operationId" class="field-help">先提交操作，再逐步驱动。</p>
    <p v-else-if="terminal" class="field-help">这条操作已经结束，只能读取状态或审计。</p>
    <p v-else-if="nextStep" class="field-help">
      下一步：{{ stepLabel(nextStep) }}。如果这一步停在签名上，去下方对应角色的面板点「同意」。
    </p>
    <p v-else class="field-help">提出方的两步已完成，转到执行方面板继续。</p>
  </el-card>
</template>

<style scoped>
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.panel {
  height: 100%;
}
.actions {
  display: flex;
  gap: 8px;
  align-items: center;
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
