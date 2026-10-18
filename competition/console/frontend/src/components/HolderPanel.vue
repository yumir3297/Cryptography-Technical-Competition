<script setup lang="ts">
import { intentLabel, scenarioLabel, stepLabel } from '../constants'
import { HOLDER_STEPS, actions, currentIntents, state } from '../store'
</script>

<template>
  <el-card shadow="never" class="panel">
    <template #header>
      <div class="card-head">
        <span>提出方（H）</span>
        <el-tag size="small" type="info">propose / read</el-tag>
      </div>
    </template>

    <el-form label-width="96px" label-position="left">
      <el-form-item label="场景">
        <el-select v-model="state.profile" style="width: 100%">
          <el-option
            v-for="item in state.scenarios"
            :key="item.profile"
            :label="scenarioLabel(item.profile)"
            :value="item.profile"
          />
        </el-select>
      </el-form-item>
      <el-form-item v-for="key in currentIntents" :key="key" :label="intentLabel(key)">
        <el-input v-model="state.intent[key]" :placeholder="key" clearable />
      </el-form-item>
    </el-form>
    <p class="field-help">留空的字段沿用固定场景默认值，只填需要覆盖的。</p>

    <div class="actions">
      <el-button type="primary" :loading="state.busy" @click="actions.submit">提交操作</el-button>
      <el-button text @click="actions.showPackage">查看公开包</el-button>
    </div>

    <el-divider content-position="left">流程步骤</el-divider>
    <div class="steps">
      <el-button
        v-for="step in HOLDER_STEPS"
        :key="step"
        :disabled="!state.operationId"
        @click="actions.step('H', step)"
      >
        {{ stepLabel(step) }}
      </el-button>
    </div>
    <p v-if="!state.operationId" class="field-help">先提交操作，再逐步驱动。</p>
  </el-card>
</template>

<style scoped>
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
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
