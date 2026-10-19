<script setup lang="ts">
/**
 * The trusted instance's operation pool.
 *
 * One entry, one pool: an operation this page submitted and one the agent
 * submitted over MCP appear side by side, because they are the same kind of
 * thing.  Picking one only fills in the id the H and worker panels below then
 * drive -- the entry, not this page, decides who may take each step.
 *
 * The row is the entry's read-only projection: scalar state and nothing else, so
 * the business intent stays in the conversation that proposed it.
 */
import { scenarioLabel } from '../constants'
import { actions, state } from '../store'

/** The state tag is a reading aid, not this page's decision. */
function tagType(rowState: string): 'success' | 'warning' | 'info' {
  if (rowState === 'SETTLED') return 'success'
  if (rowState === 'HALTED' || rowState === 'CANCELED') return 'warning'
  return 'info'
}
</script>

<template>
  <el-card shadow="never" class="panel">
    <template #header>
      <div class="card-head">
        <span>候选操作</span>
        <el-tag size="small" type="info">同一受信实例</el-tag>
      </div>
    </template>

    <p class="hint">
      这里列出该实例收到的全部候选，包括 agent 通过 MCP 提交的。点“接手”后，下面的提出方与执行方按钮就是对它驱动；不接受就不会执行。
    </p>

    <el-empty v-if="!state.operations.length" description="还没有候选" :image-size="56" />
    <div
      v-for="row in state.operations"
      :key="row.operation_id"
      class="row"
      :class="{ current: row.operation_id === state.operationId }"
    >
      <div class="line">
        <span class="profile">{{ scenarioLabel(row.profile) }}</span>
        <el-tag size="small" :type="tagType(row.state)">{{ row.state }}</el-tag>
        <span class="muted">{{ row.stage }}</span>
      </div>
      <div class="line">
        <code class="oid mono">{{ row.operation_id }}</code>
        <el-button
          size="small"
          text
          type="primary"
          :disabled="row.operation_id === state.operationId"
          @click="actions.attach(row.operation_id)"
        >
          {{ row.operation_id === state.operationId ? '已接手' : '接手' }}
        </el-button>
      </div>
    </div>
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
.hint {
  margin: 0 0 12px;
  font-size: 13px;
  line-height: 1.6;
  color: #606266;
}
.row {
  padding: 8px 10px;
  border: 1px solid #ebeef5;
  border-radius: 4px;
}
.row + .row {
  margin-top: 8px;
}
.row.current {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.line + .line {
  margin-top: 6px;
}
.profile {
  font-size: 13px;
}
.oid {
  font-size: 12px;
  word-break: break-all;
}
</style>
