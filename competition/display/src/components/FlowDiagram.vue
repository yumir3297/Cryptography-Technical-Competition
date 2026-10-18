<script setup lang="ts">
import { computed } from 'vue'

import { CHAIN, progressOf } from '../api/flow'
import type { ObservationEvent } from '../api/types'

const props = defineProps<{ events: ObservationEvent[]; operationId: string | null }>()

const progress = computed(() => progressOf(props.events))
// ``index`` is -1 until the first flow step lands, and el-steps reads a step as
// "in process" only when its index equals ``active`` -- so -1 leaves every node
// waiting rather than lighting up the first one for no reason.
const active = computed(() => progress.value.index)
const reached = computed(() => progress.value.index >= 0)
const finished = computed(() => progress.value.index >= CHAIN.length - 1)

const status = computed<'process' | 'error' | 'success'>(() => {
  if (progress.value.failed) return 'error'
  return finished.value ? 'success' : 'process'
})

const current = computed(() => CHAIN[Math.max(0, progress.value.index)])

// ``align-center`` lays the steps out in equal cells, so the centre of step ``i``
// is known without measuring anything -- which is what lets the pointer track it.
const pointerLeft = computed(() => ((Math.max(0, active.value) + 0.5) / CHAIN.length) * 100 + '%')
</script>

<template>
  <div class="flow">
    <div class="head">
      <el-text>
        当前流程：
        <strong :class="{ failed: progress.failed }">
          {{ reached ? current.label : '还没有进入流程' }}
        </strong>
      </el-text>
      <el-tag v-if="operationId" size="small" type="info" class="mono">{{ operationId }}</el-tag>
      <el-tag v-if="progress.failed" size="small" type="danger" effect="dark">已终止</el-tag>
      <el-tag v-else-if="finished" size="small" type="success" effect="dark">已完成</el-tag>
    </div>

    <div class="chain" :class="{ failed: progress.failed, idle: !reached }">
      <span v-if="reached" class="pointer" :style="{ left: pointerLeft }">▼</span>
      <el-steps :active="active" align-center finish-status="success" :process-status="status">
        <el-step v-for="(node, index) in CHAIN" :key="node.key"
                 :class="{ 'is-current': index === active && reached }"
                 :title="node.label" :description="node.side" />
      </el-steps>
    </div>

    <el-text size="small" type="info">
      节点按受信端发布的步骤推进（核心步骤 + 入口的挑战/签名往返）；引导类登记事件不计入。
    </el-text>
  </div>
</template>

<style scoped>
.flow {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 18px;
  height: 100%;
  min-height: 0;
}
.head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.head strong {
  color: var(--el-color-primary);
  font-size: 16px;
}
.head strong.failed {
  color: var(--el-color-danger);
}
.chain {
  position: relative;
  padding: 34px 6px 6px;
}
/* A wall is read from a distance, so the nodes are deliberately larger than the
   default step component's. */
:deep(.el-step__icon) {
  width: 44px;
  height: 44px;
  font-size: 18px;
}
:deep(.el-step__title) {
  font-size: 15px;
  line-height: 1.4;
}
:deep(.el-step__description) {
  font-size: 13px;
}
:deep(.el-step__line) {
  top: 22px;
}
/* The pointer, and the glow under it, are the whole "you are here" of the page. */
.pointer {
  position: absolute;
  top: 8px;
  transform: translateX(-50%);
  color: var(--el-color-primary);
  font-size: 18px;
  line-height: 1;
  filter: drop-shadow(0 0 6px currentColor);
  animation: bob 1.1s ease-in-out infinite;
}
@keyframes bob {
  0%, 100% { transform: translateX(-50%) translateY(0); }
  50% { transform: translateX(-50%) translateY(5px); }
}
.chain.failed .pointer {
  color: var(--el-color-danger);
}
/* The glow is driven by our own active index, not by Element's status classes:
   a finished run puts the last node in ``is-success``, and it still has to be
   the one that reads "you are here". */
:deep(.is-current .el-step__icon) {
  border-color: var(--el-color-primary);
  animation: glow 1.6s ease-in-out infinite;
}
:deep(.is-current .el-step__title) {
  color: var(--el-color-primary);
  font-weight: 700;
}
@keyframes glow {
  0%, 100% { box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.20), 0 0 12px rgba(64, 158, 255, 0.55); }
  50% { box-shadow: 0 0 0 9px rgba(64, 158, 255, 0.10), 0 0 26px rgba(64, 158, 255, 0.85); }
}
.chain.failed :deep(.is-current .el-step__icon) {
  border-color: var(--el-color-danger);
  animation-name: glow-bad;
}
@keyframes glow-bad {
  0%, 100% { box-shadow: 0 0 0 3px rgba(245, 108, 108, 0.22), 0 0 12px rgba(245, 108, 108, 0.60); }
  50% { box-shadow: 0 0 0 9px rgba(245, 108, 108, 0.12), 0 0 26px rgba(245, 108, 108, 0.90); }
}
/* Nothing glowing while nothing has happened. */
.chain.idle :deep(.el-step__icon) {
  box-shadow: none;
  animation: none;
}
</style>
