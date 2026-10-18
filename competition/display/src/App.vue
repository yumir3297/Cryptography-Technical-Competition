<script setup lang="ts">
import { computed, watch } from 'vue'

import FlowDiagram from './components/FlowDiagram.vue'
import OperationDetail from './components/OperationDetail.vue'
import OperationList from './components/OperationList.vue'
import RedactionNote from './components/RedactionNote.vue'
import StatusBar from './components/StatusBar.vue'
import Timeline from './components/Timeline.vue'
import { useObserveStream } from './composables/useObserveStream'
import { useOperations } from './composables/useOperations'

// Steps after which the committed-operation list is worth re-reading.  Refreshing
// on every event would be one request per step for a list that only changes here.
const MILESTONES = new Set([
  'CANDIDATE_SUBMITTED', 'ACCEPT_COMMITTED', 'CLAIMED', 'SETTLED', 'CANCELED',
  'HALTED', 'READ_PROJECTED',
])

const { events, cursor, mode, pausedAt, pause, resume } = useObserveStream()
const { rows, selected, snapshot, error, select, sync } = useOperations()

const paused = computed(() => pausedAt.value !== null)
// Pausing stops the screen, not the read: events keep arriving behind it, and
// resuming shows everything that happened while it was held.
const visible = computed(() => pausedAt.value === null
  ? events.value
  : events.value.filter((event) => event.seq <= (pausedAt.value as number)))

// The diagram follows the operation someone picked, or the newest one that has
// actually reached the flow -- bootstrap events carry no operation id at all.
const latestOperation = computed(() => {
  for (let index = events.value.length - 1; index >= 0; index -= 1) {
    if (events.value[index].operation_id) return events.value[index].operation_id
  }
  return null
})
const focusOperation = computed(() => selected.value ?? latestOperation.value)
const focusEvents = computed(() => focusOperation.value
  ? events.value.filter((event) => event.operation_id === focusOperation.value)
  : [])

const milestones = computed(() => events.value.filter((event) => MILESTONES.has(event.kind)).length)
watch(milestones, () => { void sync() })
</script>

<template>
  <div class="wall">
    <StatusBar :mode="mode" :cursor="cursor" :count="events.length" :paused="paused"
               @toggle="paused ? resume() : pause()" />
    <main class="grid">
      <el-card class="panel" shadow="never">
        <template #header><span class="title">流程演示图</span></template>
        <div class="body"><FlowDiagram :events="focusEvents" :operation-id="focusOperation" /></div>
      </el-card>

      <div class="side">
        <el-card class="panel chain" shadow="never">
          <template #header><span class="title">链条</span></template>
          <div class="body flow"><Timeline :events="visible" :paused="paused" /></div>
        </el-card>
        <el-card class="panel" shadow="never">
          <template #header><span class="title">已提交操作</span></template>
          <div class="body"><OperationList :rows="rows" :selected="selected" :error="error"
                                           @select="select" /></div>
        </el-card>
        <el-card class="panel" shadow="never">
          <template #header><span class="title">操作快照</span></template>
          <div class="body"><OperationDetail :snapshot="snapshot" /></div>
        </el-card>
      </div>
    </main>
    <RedactionNote />
  </div>
</template>

<style scoped>
.wall {
  display: grid;
  grid-template-rows: auto 1fr auto;
  height: 100vh;
}
.grid {
  display: grid;
  grid-template-columns: minmax(520px, 1fr) 460px;
  gap: 12px;
  padding: 12px;
  min-height: 0;
}
.panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.panel :deep(.el-card__body) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 12px;
}
.title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
}
.body {
  height: 100%;
  min-height: 0;
  overflow: auto;
}
.body.flow {
  display: flex;
  overflow: hidden;
}
/* The chain is the long one; the other two get a bounded share and scroll. */
.side {
  display: grid;
  grid-template-rows: minmax(0, 1fr) minmax(0, 200px) minmax(0, 320px);
  gap: 12px;
  min-height: 0;
}
</style>
