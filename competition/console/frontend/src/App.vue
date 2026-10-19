<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'

import HolderPanel from './components/HolderPanel.vue'
import OperationList from './components/OperationList.vue'
import RolePanel from './components/RolePanel.vue'
import StepLog from './components/StepLog.vue'
import StateView from './components/StateView.vue'
import WorkerPanel from './components/WorkerPanel.vue'
import { scenarioLabel } from './constants'
import { actions, currentRoles, state } from './store'

const sessions = computed(() => state.status?.sessions ?? [])

let timer: number | undefined

onMounted(() => {
  actions.refresh()
  // What is waiting changes without anyone touching this page: a chain that
  // reached one of the four signing roles is parked over there, in that role's
  // own endpoint.  So the page re-reads it on its own rather than waiting to be
  // told -- and that read goes to the endpoints, not through the entry, which is
  // exactly what is blocked while one of them waits.
  timer = window.setInterval(() => actions.refreshPending(), 3000)
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
        :disabled="state.busy"
        @select="actions.chooseScenario"
      >
        <el-menu-item
          v-for="entry in state.scenarios"
          :key="entry.profile"
          :index="entry.profile"
        >
          {{ scenarioLabel(entry.profile) }}
        </el-menu-item>
      </el-menu>
      <div class="aside-foot muted">
        六个角色，各自只拿到自己那几个动作
      </div>
    </el-aside>

    <el-container direction="vertical">
      <el-header class="header">
        <div>
          <h1 class="title">ZJJ-CORE 客户端控制台</h1>
          <div class="muted">
            {{ scenarioLabel(state.profile) }} —— 提出方与执行方逐步驱动，签发、批准、复核、效果端在链内签署
          </div>
        </div>
        <div class="header-actions">
          <el-tag
            v-for="session in sessions"
            :key="session.side"
            :type="session.open ? 'success' : 'info'"
          >
            {{ session.side }} 会话{{ session.open ? '已开' : '未开' }}
          </el-tag>
          <el-button :icon="Refresh" :loading="state.busy" @click="actions.refresh">刷新</el-button>
        </div>
      </el-header>

      <el-main>
        <el-alert
          v-if="state.error"
          :title="`被拒绝：${state.error}`"
          :description="state.error === 'CONSOLE_UNREACHABLE' ? '控制台后端不可达' : ''"
          type="error"
          show-icon
          :closable="false"
          class="alert"
        />

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

        <el-drawer v-model="state.packageOpen" title="受信端公开包" size="60%">
          <pre class="mono package">{{ state.packageText }}</pre>
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
  background: #fff;
  border-right: 1px solid #ebeef5;
}
.aside-title {
  padding: 0 20px 8px;
  font-size: 13px;
  color: #909399;
}
.aside-foot {
  padding: 16px 20px 0;
  font-size: 12px;
  line-height: 1.6;
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
  background: #fff;
  border-bottom: 1px solid #ebeef5;
}
.title {
  margin: 0;
  font-size: 20px;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.alert {
  margin-bottom: 16px;
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
</style>
