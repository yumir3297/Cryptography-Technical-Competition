<script setup lang="ts">
import { computed } from 'vue'

import { state } from '../store'

// The fields the entry's authenticated view carries.  Read-only, and only the
// ones actually present: the flow does not always fill the same set.
const NAMES = [
  'acceptance_state',
  'dispatch_state',
  'effect_state',
  'receipt_state',
  'exec_consumed',
  'state',
  'attempt_id',
]

function display(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

const rows = computed(() => {
  const view = state.view
  if (!view) return []
  return NAMES.filter((name) => name in view).map((name) => ({ name, value: display(view[name]) }))
})
</script>

<template>
  <el-card shadow="never" class="panel">
    <template #header>操作状态</template>
    <div class="stack">
      <div>
        <div class="muted">操作 id</div>
        <div class="mono">{{ state.operationId || '（尚未提交）' }}</div>
      </div>
      <el-descriptions v-if="rows.length" :column="1" border size="small">
        <el-descriptions-item v-for="row in rows" :key="row.name" :label="row.name">
          {{ row.value }}
        </el-descriptions-item>
      </el-descriptions>
      <el-empty v-else description="提交并读取状态后，这里显示认证视图" :image-size="56" />
    </div>
  </el-card>
</template>
