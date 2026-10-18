<script setup lang="ts">
import type { OperationSnapshot } from '../api/types'
import EvidenceBadge from './EvidenceBadge.vue'

const props = defineProps<{ snapshot: OperationSnapshot | null }>()

const FIELDS: Array<[string, (view: OperationSnapshot) => string]> = [
  ['接受', (view) => view.acceptance_state],
  ['派发', (view) => view.dispatch_state],
  ['效果', (view) => view.effect_state],
  ['回执', (view) => view.receipt_state],
  ['attempt', (view) => view.attempt_id ?? '—'],
  ['执行资格已消费', (view) => (view.exec_consumed ? '是' : '否')],
  ['查询次数', (view) => String(view.queries)],
  ['终局', (view) => view.final_outcome ?? '未结算'],
  ['终局事实', (view) => view.final_fact_id ?? '—'],
  ['接受时刻', (view) => view.accepted_at ?? '—'],
]
</script>

<template>
  <div class="detail">
    <template v-if="snapshot">
      <div class="head">
        <strong>{{ snapshot.profile }}</strong>
        <el-text class="mono" size="small" truncated>{{ snapshot.operation_id }}</el-text>
        <EvidenceBadge />
      </div>
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item v-for="[label, read] in FIELDS" :key="label" :label="label">
          <span class="mono">{{ read(snapshot) }}</span>
        </el-descriptions-item>
      </el-descriptions>
      <el-text size="small" type="info">
        以上来自观察面投影，不是协议自身的签名状态回执。
      </el-text>
    </template>
    <el-empty v-else description="点选左边一个操作，看它的当前投影" :image-size="60" />
  </div>
</template>

<style scoped>
.detail {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
