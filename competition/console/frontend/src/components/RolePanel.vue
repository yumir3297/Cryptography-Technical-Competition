<script setup lang="ts">
/** One of the four roles that sign *inside* the chain.
 *
 *  They have no steps: their signatures are made while the chain is assembled,
 *  in one pass, and the endpoint that holds the key parks the request until
 *  someone answers it.  So this panel shows what is waiting and takes a yes or a
 *  no -- not a button per step.  Nothing here signs: the answer travels to the
 *  endpoint, and the endpoint's own signing point is what produces anything.
 */
import { computed } from 'vue'

import { roleDuty, roleLabel } from '../constants'
import { actions, state, todosFor } from '../store'
import type { RoleInfo } from '../types'

const props = defineProps<{ role: RoleInfo }>()

const todos = computed(() => todosFor(props.role.alias))

/** What would be signed, shown as it is: a person agrees to a message, not an id. */
function shown(claim: unknown): string {
  return JSON.stringify(claim, null, 2)
}
</script>

<template>
  <el-card shadow="never" class="panel">
    <template #header>
      <div class="card-head">
        <span>{{ roleLabel(role.alias) }}</span>
        <el-tag size="small" type="info">{{ role.name }}</el-tag>
      </div>
    </template>

    <p class="duty">{{ roleDuty(role.alias) }}</p>

    <div v-if="!todos.length" class="empty">暂无待办</div>
    <div v-for="todo in todos" :key="todo.id" class="todo">
      <div class="todo-title">{{ todo.domain }}</div>
      <pre class="todo-claim mono">{{ shown(todo.claim) }}</pre>
      <div class="todo-actions">
        <el-button
          type="primary"
          size="small"
          :loading="state.busy"
          @click="actions.decide(role.alias, todo.id, true)"
        >
          同意
        </el-button>
        <el-button
          size="small"
          :disabled="state.busy"
          @click="actions.decide(role.alias, todo.id, false)"
        >
          拒绝
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
.duty {
  margin: 0 0 12px;
  font-size: 13px;
  color: #606266;
}
.empty {
  padding: 8px 0;
  font-size: 13px;
  color: #909399;
}
.todo + .todo {
  margin-top: 12px;
}
.todo-title {
  font-size: 13px;
  word-break: break-all;
}
.todo-claim {
  margin: 6px 0 0;
  padding: 8px;
  max-height: 180px;
  overflow: auto;
  font-size: 11px;
  line-height: 1.5;
  background: #f5f7fa;
  border-radius: 4px;
  white-space: pre-wrap;
}
.todo-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
}
</style>
