<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

import type { ObservationEvent } from '../api/types'

const props = defineProps<{ events: ObservationEvent[]; paused: boolean }>()

const box = ref<HTMLElement | null>(null)

function dotType(event: ObservationEvent): 'primary' | 'success' | 'danger' | 'info' {
  if (event.status_label === 'HALTED' || event.status_label === 'CANCELED') return 'danger'
  if (event.status_label === 'SETTLED') return 'success'
  return event.source === 'ENTRY' ? 'info' : 'primary'
}

// Follow the tail while the screen is live; leave it alone when it is paused, so
// pausing actually lets someone read a step instead of being dragged off it.
watch(() => props.events.length, async () => {
  if (props.paused) return
  await nextTick()
  if (box.value) box.value.scrollTop = box.value.scrollHeight
})
</script>

<template>
  <div ref="box" class="timeline">
    <el-timeline>
      <el-timeline-item v-for="event in events" :key="event.seq" :type="dotType(event)"
                        :timestamp="'#' + event.seq" placement="top" size="normal">
        <div class="row">
          <el-tag size="small" :type="dotType(event)" effect="dark">{{ event.kind }}</el-tag>
          <span class="stage">{{ event.stage }}</span>
        </div>
        <div class="tags">
          <el-tag size="small" :type="event.source === 'ENTRY' ? 'info' : 'primary'" effect="plain">
            {{ event.source === 'ENTRY' ? '入口流程' : '核心决策' }}
          </el-tag>
          <el-tag v-for="lane in event.lanes" :key="lane" size="small" type="info" effect="plain">
            {{ lane }}
          </el-tag>
          <el-text v-if="event.trusted_time" size="small" type="info" class="mono">
            trusted_time {{ event.trusted_time.lo }}–{{ event.trusted_time.hi }}
          </el-text>
        </div>
      </el-timeline-item>
    </el-timeline>
    <el-empty v-if="!events.length" description="还没有事件" :image-size="60" />
  </div>
</template>

<style scoped>
.timeline {
  overflow: auto;
  flex: 1;
  min-height: 0;
  padding-right: 6px;
}
.row {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.stage {
  color: var(--el-text-color-primary);
}
.tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  color: var(--el-text-color-secondary);
}
:deep(.el-timeline) {
  padding-left: 4px;
}
</style>
