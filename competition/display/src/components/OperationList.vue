<script setup lang="ts">
import type { OperationRow } from '../api/types'

const props = defineProps<{ rows: OperationRow[]; selected: string | null; error: string }>()
defineEmits<{ select: [oid: string] }>()

function rowClass({ row }: { row: OperationRow }): string {
  return row.operation_id === props.selected ? 'is-selected' : ''
}
</script>

<template>
  <div class="list">
    <el-alert v-if="error" type="error" :closable="false" :title="error" show-icon />
    <el-table :data="rows" size="small" :row-class-name="rowClass" stripe
              empty-text="还没有已提交的操作"
              @row-click="(row: OperationRow) => $emit('select', row.operation_id)">
      <el-table-column prop="profile" label="场景" width="86" />
      <el-table-column prop="operation_id" label="操作" min-width="128" show-overflow-tooltip />
      <el-table-column label="状态" min-width="150">
        <template #default="{ row }">
          <el-tag size="small" effect="plain">{{ row.dispatch_state }}</el-tag>
          <el-tag size="small" effect="plain">{{ row.effect_state }}</el-tag>
          <el-tag size="small" effect="plain" type="info">{{ row.receipt_state }}</el-tag>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
:deep(.el-table__row) {
  cursor: pointer;
}
:deep(.el-table .is-selected) {
  --el-table-tr-bg-color: var(--el-color-primary-light-9);
}
</style>
