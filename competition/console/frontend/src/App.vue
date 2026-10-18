<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'

import HolderPanel from './components/HolderPanel.vue'
import StepLog from './components/StepLog.vue'
import StateView from './components/StateView.vue'
import WorkerPanel from './components/WorkerPanel.vue'
import { actions, state } from './store'

const sessions = computed(() => state.status?.sessions ?? [])

onMounted(() => {
  actions.refresh()
})
</script>

<template>
  <el-container class="page" direction="vertical">
    <el-header class="header">
      <div>
        <h1 class="title">ZJJ-CORE 客户端控制台</h1>
        <div class="muted">提出方与执行方两侧，经受信端入口驱动一遍流程</div>
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

      <el-row :gutter="16">
        <el-col :xs="24" :md="9"><HolderPanel /></el-col>
        <el-col :xs="24" :md="9"><WorkerPanel /></el-col>
        <el-col :xs="24" :md="6"><StateView /></el-col>
      </el-row>

      <div class="timeline">
        <StepLog />
      </div>

      <el-drawer v-model="state.packageOpen" title="受信端公开包" size="60%">
        <pre class="mono package">{{ state.packageText }}</pre>
      </el-drawer>
    </el-main>
  </el-container>
</template>

<style scoped>
.page {
  min-height: 100%;
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
.timeline {
  margin-top: 16px;
}
.package {
  margin: 0;
  font-size: 12px;
  white-space: pre-wrap;
}
</style>
