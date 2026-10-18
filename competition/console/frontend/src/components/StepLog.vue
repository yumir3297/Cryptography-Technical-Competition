<script setup lang="ts">
import { stepLabel } from '../constants'
import { state } from '../store'

function pretty(detail: unknown): string {
  if (typeof detail === 'string') return detail
  return JSON.stringify(detail, null, 2)
}
</script>

<template>
  <el-card shadow="never" class="panel">
    <template #header>操作时间线</template>
    <el-empty v-if="!state.log.length" description="还没有请求" :image-size="56" />
    <el-timeline v-else>
      <el-timeline-item
        v-for="(entry, index) in state.log"
        :key="index"
        :timestamp="entry.at"
        :type="entry.ok ? 'success' : 'danger'"
      >
        <div class="line">
          <strong>{{ entry.side === 'H' ? '提出方' : '执行方' }}</strong>
          <span>· {{ stepLabel(entry.step) }}</span>
          <el-tag size="small" :type="entry.ok ? 'success' : 'danger'">
            {{ entry.ok ? '通过' : '拒绝' }}
          </el-tag>
        </div>
        <pre class="mono detail">{{ pretty(entry.detail) }}</pre>
      </el-timeline-item>
    </el-timeline>
  </el-card>
</template>

<style scoped>
.line {
  display: flex;
  align-items: center;
  gap: 6px;
}
.detail {
  margin: 6px 0 0;
  padding: 8px;
  background: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  font-size: 12px;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
}
</style>
