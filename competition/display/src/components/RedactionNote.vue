<template>
  <div class="note">
    <el-alert type="warning" :closable="false" show-icon>
      <template #title>
        这是<strong>只读观察面</strong>的展示页：事件由受信端在决策<b>自身事务内</b>发布，
        提交才可见、回滚即消失；入口的候选、装配、挑战与签名往返为
        <code>source=ENTRY</code> 的<b>非权威</b>流程事件。
      </template>
      <template #default>
        页面只发 <code>GET</code>，不驱动任何步骤；不含业务 payload、患者/付款原始字段、
        nonce、session_id、签名或私钥。
      </template>
    </el-alert>
  </div>
</template>

<style scoped>
.note {
  padding: 10px 16px;
  background: var(--el-bg-color-page);
  border-top: 1px solid var(--el-border-color);
}
code {
  background: var(--el-fill-color);
  border-radius: 4px;
  padding: 0 4px;
}
</style>
