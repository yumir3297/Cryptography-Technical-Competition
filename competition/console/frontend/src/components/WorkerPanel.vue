<script setup lang="ts">
import { stepLabel } from '../constants'
import { WORKER_STEPS, actions, state } from '../store'
</script>

<template>
  <el-card shadow="never" class="panel">
    <template #header>
      <div class="card-head">
        <span>执行方（worker）</span>
        <el-tag size="small" type="warning">claim / execute / settle</el-tag>
      </div>
    </template>

    <div class="stack">
      <div>
        <div class="muted">当前操作 id</div>
        <div class="mono">{{ state.operationId || '（尚未提交）' }}</div>
      </div>
      <p class="field-help">
        执行方不提交，也不读业务状态；它领取、执行并结算提出方已经接受的操作。
      </p>
    </div>

    <el-divider content-position="left">流程步骤</el-divider>
    <div class="steps">
      <el-button
        v-for="step in WORKER_STEPS"
        :key="step"
        :disabled="!state.operationId"
        @click="actions.step('worker', step)"
      >
        {{ stepLabel(step) }}
      </el-button>
    </div>
    <p v-if="!state.operationId" class="field-help">先让提出方提交操作。</p>
  </el-card>
</template>

<style scoped>
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
