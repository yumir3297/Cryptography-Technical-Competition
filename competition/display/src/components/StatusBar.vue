<script setup lang="ts">
import { VideoPause, VideoPlay } from '@element-plus/icons-vue'

import type { FeedMode } from '../composables/useObserveStream'
import EvidenceBadge from './EvidenceBadge.vue'

defineProps<{ mode: FeedMode; cursor: number; count: number; paused: boolean }>()
defineEmits<{ toggle: [] }>()

const STATUS: Record<FeedMode, { label: string; type: 'success' | 'warning' | 'danger' }> = {
  live: { label: '实时推送', type: 'success' },
  polling: { label: '轮询兜底', type: 'warning' },
  offline: { label: '连接中断', type: 'danger' },
}
</script>

<template>
  <header class="bar">
    <el-tag :type="STATUS[mode].type" effect="dark" round size="large">
      {{ STATUS[mode].label }}
    </el-tag>
    <el-text class="metric">游标 seq <b class="mono">{{ cursor }}</b></el-text>
    <el-text class="metric">事件 <b class="mono">{{ count }}</b></el-text>
    <EvidenceBadge />
    <span class="spacer"></span>
    <el-button :type="paused ? 'primary' : 'info'" plain
               :icon="paused ? VideoPlay : VideoPause" @click="$emit('toggle')">
      {{ paused ? '继续' : '暂停' }}
    </el-button>
  </header>
</template>

<style scoped>
.bar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 16px;
  background: var(--el-bg-color-page);
  border-bottom: 1px solid var(--el-border-color);
  flex-wrap: wrap;
}
.metric {
  font-size: 14px;
}
.spacer {
  flex: 1;
}
</style>
