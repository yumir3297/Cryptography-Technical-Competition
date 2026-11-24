<script setup lang="ts">
/** One of the four roles that sign *inside* the chain.
 *
 *  They have no steps: their signatures are made while the chain is assembled,
 *  in one pass, and the endpoint that holds the key parks the request until
 *  someone answers it.  So this panel shows what is waiting and takes a yes or a
 *  no -- not a button per step.  Nothing here signs: the answer travels to the
 *  endpoint, and the endpoint's own signing point is what produces anything.
 */
import { computed, reactive } from 'vue'

import { roleDuty, roleLabel } from '../constants'
import { actions, state, todosFor } from '../store'
import type { RoleInfo } from '../types'

const props = defineProps<{ role: RoleInfo }>()

const todos = computed(() => todosFor(props.role.alias))
const expanded = reactive<Record<string, boolean>>({})

/** One ticket's own in-flight state; never the page's global busy flag. */
function deciding(id: string): boolean {
  return !!state.deciding[props.role.alias + ':' + id]
}

/** What would be signed, shown as it is: a person agrees to a message, not an id. */
function shown(claim: unknown): string {
  return JSON.stringify(claim, null, 2)
}

/** The operation this ticket belongs to, found in the claim as delivered.
 *  The page does not invent it; the signed body carries it. */
function operationOf(claim: unknown): string {
  const match = /"operation_id"\s*:\s*"([^"]+)"/.exec(JSON.stringify(claim))
  return match ? match[1] : ''
}

function toggle(id: string): void {
  expanded[id] = !expanded[id]
}
</script>

<template>
  <el-card shadow="never" class="panel" :data-role="role.alias">
    <template #header>
      <div class="card-head">
        <h2 class="card-title">{{ roleLabel(role.alias) }}</h2>
        <el-tag size="small" type="info">{{ role.name }}</el-tag>
      </div>
    </template>

    <p class="duty">{{ roleDuty(role.alias) }}</p>

    <div v-if="!todos.length" class="empty">
      暂无待办<span class="empty-note"> · 提出方准备 / 接受时，这里才会出现需要放行的签名</span>
    </div>
    <div v-for="todo in todos" :key="todo.id" class="todo">
      <div class="todo-title">{{ todo.domain }}</div>
      <div class="todo-meta mono">
        <span>{{ todo.profile }}</span>
        <span v-if="operationOf(todo.claim)">
          操作 {{ operationOf(todo.claim).slice(0, 12) }}
        </span>
        <span>#{{ todo.id }}</span>
      </div>
      <pre class="todo-claim mono" :class="{ 'is-expanded': expanded[todo.id] }">{{ shown(todo.claim) }}</pre>
      <el-button link type="primary" size="small" class="todo-more" @click="toggle(todo.id)">
        {{ expanded[todo.id] ? '收起内容' : '展开全文' }}
      </el-button>
      <div class="todo-actions">
        <el-button
          type="primary"
          size="small"
          :loading="deciding(todo.id)"
          :aria-label="`同意 ${operationOf(todo.claim).slice(0, 12)} 的请求`"
          @click="actions.decide(role.alias, todo.id, true)"
        >
          同意
        </el-button>
        <el-button
          size="small"
          :disabled="deciding(todo.id)"
          :aria-label="`拒绝 ${operationOf(todo.claim).slice(0, 12)} 的请求`"
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
  color: var(--ak-fg-secondary);
}
.empty {
  padding: 8px 0;
  font-size: 13px;
  color: var(--ak-fg-muted);
}
.empty-note {
  font-size: 11px;
}
.todo-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  margin-top: 4px;
  font-size: 11px;
  color: var(--ak-fg-muted);
}
.todo-more {
  margin-top: 2px;
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
  background: var(--ak-bg-surface-2);
  border-radius: 0;
  white-space: pre-wrap;
}
.todo-claim.is-expanded {
  max-height: 60vh;
}
.todo-actions {
  position: sticky;
  bottom: 8px;
  z-index: 1;
  margin-top: 8px;
  padding: 6px 0;
  display: flex;
  gap: 8px;
  background: var(--ak-bg-surface);
}
</style>
