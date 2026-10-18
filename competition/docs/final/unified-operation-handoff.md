# ZJJ-CORE 统一整合交接（2026-10-17）

> 历史阶段记录：以下验证与“未推送”状态按当时保留。当前完整交付、替代关系与最新验证请从[统一交付入口](ind-complete-delivery-20261018.md)阅读。

精确起点为 PR #3 @ 86f284bf4787e9990b47b8159cd1e6b9e5824b03。本次持久交付以 recovered-joint-01 为验收运行，历史运行记录另列。未推送、合并、删除或覆盖任何远程分支。

## 1. 如何解决

P2 保留一个 RequestStore，延续 V1 的受控分配和请求恢复。完整链首次冻结后，接受前只允许更新 ChallengeRequest、Challenge、CommitProof；固定 Action、ActionHash、Basis、批准、Issue 和 Permit。版本 CAS、历史短期标识防回退及 W 接受事务内的当前包核对共同阻断旧 ticket。已接受后恢复原 COMMIT/Core，工具效果未知只查询原 attempt。

P4 已实现固定 IND 的受信服务、真实回环 HTTP 短连接和 MCP stdio 桥接；公开十项方法采用显式白名单。传输 token 与 H 的签署授权分开，服务不持有参与者私钥。原 W、账写入、签署、complete_receipt 和派发 worker 均留在内部。

P5 重新核查远程发现 dev 已推进到 32370d4，与比赛分支不同。其旧链清理及自动生成证明的 facade 没有混入本次整合。main 仍是比赛分支的祖先，不需要反向合入。详见 [分支核查](unified-operation-branches.md)。

## 2. 对其他部分的影响

保留核心十字段、原 Schema、ActionHash、签名承诺、DENY、时间阈值及 EXEC 规则。CommonW 只增加两个事务检查接点及默认内部 hook；新公开入口强制绑定 RequestStore。app_request 增加版本与历史列，原真实 V1 行可迁移；原 a_journal 保存每版完整包。

159 项原测试保持原内部组件/可选 V1 配置，不能称全部经过强制新入口。PAY/MED 保留完整 Action，没有新增未确认的简化业务字段。生产身份提供者、实体设备、多机状态均不在已验证范围。

## 3. 具体补全方案和接手方式

方法、角色表、认证域、错误、接受与恢复时序见 [接口契约](unified-operation-contract.md)。核心实现为 application 下的 request_store、operation_orchestrator、request_bound_w、operation_service、http_service、mcp_stdio；MCP 只承载接口，不成为协议核心依赖。

本地分支 integration/unified-operation-lifecycle-20261017 是单一写入工作区；开发方以明确 SHA 交接，禁止同时修改共享分支。后续若发布增量 Draft PR，目标可选 PR #3 分支，但须先核对它的最新 head 并单独确认发布方式。本次只交付本地提交与 patch。

临时目录在交付前丢失，本次从保存会话恢复 53 次源码补丁操作，并在项目 outputs 中重建持久仓库。旧完整原始日志、失败数据库快照和演示没有全部恢复；只能提供保存会话中的真实输出摘录，不能冒充原文件。此前独立审查记录已恢复，当前代码重新验证，但没有宣称重新进行第二次独立审查。

## 4. 实验代码与真实结果

本次 recovered-joint-01 的原始结果见 summary.json 和 joint-final.log：**196/196，559.756 秒，退出码 0，源码前后摘要相同**。组成是原 159 项、P2 20 项、服务 10 项、真实传输 4 项、帧解析 3 项；没有相加旧 P2 的 25/137 或 PR #3 的历史 159。

本次保留 14344 条子进程观察，自然 unhealthy 包 0 个。公开 MCP→HTTP 演示中，原 Permit 不变，版本 1→2，旧 ticket 被拒绝；工具落账后退出 98，查询同一 attempt 完成恢复。接受、attempt、EXEC 消费、效果、结算各 1；冻结 Core 不变。离线签名/引用核验结果单独保存。

371 项结构契约、70 项 Node 样本、历史签名证据检查及仓库完整性检查分别保留原始输出，不加入联合套件计数。先前 joint-awake-01 的 196/196（534.929 秒）只作为会话历史记录，当前可交付证据以本次重建运行文件为准。

时钟未决项仍存在：历史样本缺失使部分 CLOCK_UNKNOWN/CASE_RECEIPT_PENDING 无法精确归因；已有记录支持一次休眠引起的 64.62 秒墙钟/单调计时偏离，另有约 45.42 ms 校时线索。防空闲休眠仅处理已知宿主条件，不放宽阈值、不修改 healthy、不重签冻结 Core。见 [时钟说明](unified-operation-clock.md)。本次通过不等于所有历史间歇问题已根治。

复现：安装 cryptography==50.0.2、jsonschema==4.26.0，从仓库根目录运行 ZJJ_PYTHON=<解释器> sh competition/run_unified_checks.sh <全新证据目录>。演示及其离线核验分别为 integration-evidence/demo.py 和 verify_demo.py，均为测试工具。
