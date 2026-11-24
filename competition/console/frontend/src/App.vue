<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, onUnmounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'

import HolderPanel from './components/HolderPanel.vue'
import OperationList from './components/OperationList.vue'
import RolePanel from './components/RolePanel.vue'
import StepLog from './components/StepLog.vue'
import StateView from './components/StateView.vue'
import WorkerPanel from './components/WorkerPanel.vue'
import { roleLabel, scenarioLabel, stepLabel } from './constants'
import { actions, currentRoles, state } from './store'

const sessions = computed(() => state.status?.sessions ?? [])
const pendingTodos = computed(() => state.pending?.todos ?? [])
const pendingRoles = computed(() => {
  const seen: string[] = []
  for (const todo of pendingTodos.value) {
    if (!seen.includes(todo.role)) seen.push(todo.role)
  }
  return seen
})
const pollErrorText = computed(() => {
  if (state.pendingError && state.operationsError) {
    return '待办与候选列表都读取失败，下面显示上一次结果'
  }
  if (state.operationsError) return '候选列表读取失败，下面显示上一次结果'
  return '待办读取失败，下面显示上一次结果'
})
const freshText = computed(() => {
  const at = state.lastUpdated
  if (!at) return '每 3 秒自动刷新'
  return `最后更新 ${at.toLocaleTimeString('zh-CN', { hour12: false })} · 3s 自动刷新`
})
const stepBusyText = computed(() => {
  if (!state.stepBusy) return ''
  const [side, step] = state.stepBusy.split(':')
  return `${roleLabel(side)} · ${stepLabel(step)}`
})
const errorTitle = computed(() => {
  if (state.error === 'CONSOLE_OPERATION') return '还没有接手操作'
  if (state.error === 'CONSOLE_OPERATION_UNKNOWN') return '当前操作已失效'
  if (state.error === 'CONSOLE_UNREACHABLE') return '无法连接控制台后端'
  if (state.error === 'ENTRY_UNAVAILABLE' || state.error === 'ENTRY_ANSWER') {
    return '受信端暂时不可用'
  }
  if (state.error === 'ENDPOINT_UNAVAILABLE') return '某个角色端暂时不可用'
  if (state.error === 'INTENT_CONFLICT') return '这个场景的意图已被占用'
  if (state.error === 'UPSTREAM_SCHEMA_REJECT') return '字段格式被上游拒绝'
  if (state.error === 'STALE') return '这个场景的固定操作已经推进过'
  return `被拒绝：${state.error}`
})
const errorHint = computed(() => {
  if (state.error === 'CONSOLE_OPERATION') {
    return '先在「候选操作」里接手一条，或在提出方面板提交一条新操作。'
  }
  if (state.error === 'CONSOLE_OPERATION_UNKNOWN') {
    return '这条操作已不在该实例的候选列表里；请在「候选操作」里重新接手。'
  }
  if (state.error === 'CONSOLE_UNREACHABLE') return '检查控制台服务是否在运行，恢复后 3 秒轮询会自动清掉这条提示。'
  if (state.error === 'ENTRY_UNAVAILABLE' || state.error === 'ENTRY_ANSWER') {
    return '受信端入口没有应答；等它恢复后重试。'
  }
  if (state.error === 'ENDPOINT_UNAVAILABLE') return '检查对应角色的端点是否在运行；这一步可以稍后重试。'
  if (state.error === 'INTENT_CONFLICT') {
    return '同一场景的固定意图只能被一条操作使用。换一个场景，或换一笔新的业务单号再提交。'
  }
  if (state.error === 'UPSTREAM_SCHEMA_REJECT') {
    return '上游拒绝了字段格式；把拿不准的字段留空，使用场景默认值。'
  }
  if (state.error === 'STALE') {
    return '同一场景的固定操作已经走过一轮，不能重复提交。换一个场景，或重新开始一轮演示。'
  }
  return '这条请求被拒绝；按码处理后重试。'
})

function focusRole(role: string): void {
  const node = document.querySelector(`[data-role="${role}"]`)
  if (node) node.scrollIntoView({ block: 'center', behavior: 'smooth' })
}

function ensureMenuVisible(event: FocusEvent): void {
  const item = event.target as HTMLElement | null
  if (item && item.classList.contains('el-menu-item')) {
    item.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }
}

function focusPackage(): void {
  const button = Array.from(document.querySelectorAll('button')).find(
    (entry) => entry.textContent?.includes('查看公开包'),
  )
  button?.focus()
}

async function copyPackage(): Promise<void> {
  try {
    await navigator.clipboard.writeText(state.packageText)
    ElMessage.success('公开包已复制到剪贴板')
  } catch {
    ElMessage.error('浏览器拒绝了剪贴板访问，请在抽屉里手动选择')
  }
}

let timer: number | undefined

onMounted(() => {
  actions.refresh()
  // What is waiting changes without anyone touching this page: a chain that
  // reached one of the four signing roles is parked over there, in that role's
  // own endpoint.  So the page re-reads it on its own rather than waiting to be
  // told -- and that read goes to the endpoints, not through the entry, which is
  // exactly what is blocked while one of them waits.
  timer = window.setInterval(() => {
    // A failed first load leaves no roster and no panels; retry it rather than
    // leaving the page half there until somebody presses 刷新.
    if (!state.status || !state.scenarios.length) void actions.refresh()
    else void actions.refreshPending()
  }, 3000)
})

onUnmounted(() => {
  if (timer !== undefined) window.clearInterval(timer)
})
</script>

<template>
  <el-container class="page">
    <el-aside class="aside" width="200px">
      <div class="aside-title">场景</div>
      <el-menu
        :default-active="state.profile"
        :disabled="state.submitting || !!state.stepBusy"
        @select="actions.chooseScenario"
        @focusin="ensureMenuVisible"
      >
        <el-menu-item
          v-for="entry in state.scenarios"
          :key="entry.profile"
          :index="entry.profile"
          tabindex="0"
          :aria-current="state.profile === entry.profile ? 'true' : undefined"
          @keydown.enter.prevent="actions.chooseScenario(entry.profile)"
          @keydown.space.prevent="actions.chooseScenario(entry.profile)"
        >
          {{ scenarioLabel(entry.profile) }}
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container direction="vertical">
      <el-header class="header">
        <div>
          <h1 class="title">ZJJ-CORE 客户端控制台</h1>
        </div>
        <div class="header-actions">
          <el-tag
            v-for="session in sessions"
            :key="session.side"
            :type="session.open ? 'success' : 'info'"
          >
            {{ session.side }} 会话{{ session.open ? '已开' : '未开' }}
          </el-tag>
          <el-badge v-if="pendingTodos.length" :value="pendingTodos.length" type="warning">
            <el-button size="small" type="warning" plain @click="focusRole(pendingRoles[0])">
              待放行
            </el-button>
          </el-badge>
          <el-switch
            v-model="state.follow"
            size="small"
            active-text="跟随待办"
            aria-label="跟随有待办的场景"
          />
          <el-button :icon="Refresh" :loading="state.busy" @click="actions.refresh">刷新</el-button>
          <span class="fresh mono">{{ freshText }}</span>
        </div>
      </el-header>

      <el-main>
        <el-alert
          v-if="state.error"
          :title="errorTitle"
          :description="errorHint"
          type="error"
          show-icon
          closable
          class="alert"
          @close="state.error = ''"
        />

        <el-alert
          v-if="state.stepBusy"
          :title="`正在执行 ${stepBusyText}`"
          description="这一步会停在 G/U/V/X 的签名上；下方对应面板出现待办后点「同意」即可继续。批准按钮不会因为这一步还没返回而失效。"
          type="info"
          show-icon
          :closable="false"
          class="alert"
        />

        <el-alert
          v-if="state.pendingError || state.operationsError"
          :title="pollErrorText"
          description="等下一次 3 秒轮询恢复；如果一直失败，检查对应服务是否在运行。"
          type="error"
          show-icon
          :closable="false"
          class="alert"
        />

        <el-alert
          v-if="state.waitingElsewhere"
          type="warning"
          show-icon
          :closable="false"
          class="alert"
        >
          <template #title>
            <span>
              另一个场景（{{ scenarioLabel(state.waitingElsewhere) }}）还有签名请求在等待放行；现在提交或执行会排在它后面。
            </span>
            <el-button link type="primary" @click="actions.chooseScenario(state.waitingElsewhere)">
              切过去
            </el-button>
          </template>
        </el-alert>

        <el-alert
          v-if="pendingTodos.length"
          type="warning"
          show-icon
          :closable="false"
          class="alert"
        >
          <template #title>
            <span>
              有 {{ pendingTodos.length }} 个签名请求等待放行：{{ pendingRoles.map(roleLabel).join('、') }}
            </span>
            <el-button link type="primary" @click="focusRole(pendingRoles[0])">去放行</el-button>
          </template>
        </el-alert>

        <div class="guide">
          <span class="guide-title">流程</span>
          <span class="guide-step">① 提交操作，或从候选里接手</span>
          <span class="guide-arrow">→</span>
          <span class="guide-step">② 提出方：准备、接受</span>
          <span class="guide-arrow">→</span>
          <span class="guide-step">③ 执行方：领取、执行、结算</span>
          <span class="guide-arrow">→</span>
          <span class="guide-step">④ 提出方：状态</span>
          <span class="guide-note">G/U/V/X 的签名在下方对应面板放行</span>
        </div>

        <!-- The instance's pool comes first: an operation the agent submitted
             over MCP appears here, and picking it is what the panels below then
             drive.  The page never submits on its own account of it. -->
        <div class="block">
          <OperationList />
        </div>

        <el-row :gutter="16">
          <el-col v-for="role in currentRoles" :key="role.alias" :xs="24" :md="8">
            <HolderPanel v-if="role.alias === 'H'" />
            <WorkerPanel v-else-if="role.alias === 'worker'" />
            <RolePanel v-else :role="role" />
          </el-col>
        </el-row>

        <div class="block">
          <StateView />
        </div>

        <div class="block timeline">
          <StepLog />
        </div>

        <el-drawer v-model="state.packageOpen" size="min(720px, 92vw)" @closed="focusPackage">
          <template #header>
            <div class="drawer-head">
              <span>受信端公开包</span>
              <span class="muted">{{ state.packageText.length.toLocaleString() }} 字符</span>
              <el-button size="small" @click="copyPackage">复制全文</el-button>
            </div>
          </template>
          <pre class="mono package" tabindex="0" role="region"
               aria-label="公开包 JSON，可用方向键滚动">{{ state.packageText }}</pre>
        </el-drawer>
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.page {
  min-height: 100%;
}
.aside {
  padding: 16px 0;
  background: var(--ak-bg-surface);
  border-right: 1px solid var(--ak-border);
}
.aside-title {
  padding: 0 20px 8px;
  font-size: 13px;
  color: var(--ak-fg-muted);
}
.aside :deep(.el-menu) {
  border-right: none;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  height: auto;
  padding: 16px 24px;
  background: var(--ak-bg-surface);
  border-bottom: 1px solid var(--ak-border);
}
.title {
  margin: 0;
  font-family: var(--ak-font-display);
  font-size: 20px;
  letter-spacing: .06em;
}
.header-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.fresh {
  font-size: 11px;
  color: var(--ak-fg-muted);
  white-space: nowrap;
}
.alert {
  margin-bottom: 16px;
}
.guide {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
  padding: 10px 14px;
  font-size: 13px;
  color: var(--ak-fg-secondary);
  background: var(--ak-bg-surface);
  border: 1px solid var(--ak-border-subtle);
}
.guide-title {
  color: var(--ak-fg);
  letter-spacing: .08em;
}
.guide-step {
  color: var(--ak-fg);
}
.guide-arrow {
  color: var(--ak-fg-muted);
}
.guide-note {
  margin-left: auto;
  color: var(--ak-fg-muted);
}
.block {
  margin-top: 16px;
}
.timeline {
  padding-bottom: 24px;
}
.package {
  margin: 0;
  font-size: 12px;
  white-space: pre-wrap;
}
.drawer-head {
  display: flex;
  align-items: center;
  gap: 12px;
}
.drawer-head .el-button {
  margin-left: auto;
}
</style>
