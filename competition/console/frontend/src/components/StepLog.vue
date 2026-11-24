<script setup lang="ts">
import { roleLabel, stepLabel } from '../constants'
import { state } from '../store'

function pretty(detail: unknown): string {
  if (typeof detail === 'string') return detail
  return JSON.stringify(detail, null, 2)
}

/** Signed reads move the page, not the operation; label them as reads. */
function readStep(step: string): boolean {
  return ['status', 'audit', 'query'].includes(step)
}

/** Local page actions (attach, restore, another tab) are not flow steps. */
function localStep(step: string): boolean {
  return ['接手操作', '恢复当前操作', '另一标签切换当前操作', '另一标签清空当前操作',
    '放弃当前操作', '候选出现，自动接手'].includes(step)
}
</script>

<template>
  <el-card shadow="never" class="panel">
    <template #header><h2 class="card-title">操作时间线</h2></template>
    <el-empty v-if="!state.log.length" description="还没有执行任何步骤" :image-size="56" />
    <el-timeline v-else>
      <el-timeline-item
        v-for="(entry, index) in state.log"
        :key="index"
        :timestamp="entry.at"
        :type="entry.ok ? 'success' : 'danger'"
      >
        <div class="line">
          <strong>{{ localStep(entry.step) ? '页面' : roleLabel(entry.side) }}</strong>
          <span>· {{ stepLabel(entry.step) }}</span>
          <el-tag
            size="small"
            :type="entry.ok
              ? (readStep(entry.step) || localStep(entry.step) ? 'info' : 'success')
              : 'danger'"
          >
            {{ entry.ok
              ? (localStep(entry.step) ? '页面' : readStep(entry.step) ? '读取' : '通过')
              : '拒绝' }}
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
  background: var(--ak-bg-surface-2);
  border: 1px solid var(--ak-border-subtle);
  border-radius: 0;
  font-size: 12px;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
}
</style>
