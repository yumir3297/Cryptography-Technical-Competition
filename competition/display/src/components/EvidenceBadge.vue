<script setup lang="ts">
import { WarningFilled } from '@element-plus/icons-vue'
</script>

<template>
  <el-tooltip
    content="观察面发布的是展示投影：不签名、非证据、不是原始信封。"
    placement="bottom"
  >
    <el-tag type="warning" effect="dark" size="small" round :icon="WarningFilled">
      只读投影 · 未签名 · 非证据
    </el-tag>
  </el-tooltip>
</template>
