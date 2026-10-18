# Trusted Action Resolver V1：验证记录

> 历史阶段记录：以下验证与“未推送”状态按当时保留。当前完整交付、替代关系与最新验证请从[统一交付入口](ind-complete-delivery-20261018.md)阅读。

基线：`competition/zjj-core-final-20261010`，`cc4e36b4e302fcdc53cc809a012c77d8464182af`。本轮应用库、测试和文档均为新增文件。原 350 个受版本控制文件逐字节一致，见 [原文件完整性](../../evidence/trusted-action-resolver-v1-20261017/original-files-integrity.json)。

## 当前验证范围

| 要求 | 本轮检查与验收依据 |
|---|---|
| E1 / 六字段来源 | 严格 CandidateProposal；只含 request_id/unit_id/route；H 认证和固定 Task；Task/Policy/KEY/ROLE/工具交叉检查；生成原十字段 Action |
| E2 / 原链兼容 | 原 ActionHash、真实模拟参与方签名链、CommonGuard、CommonW；伪造六字段、缺 review、坏签名拒绝，不能占用首次冻结槽 |
| E3 / 分配与重试 | W 事务内随机 B16；8 并发映射、碰撞重试/耗尽、同键异内容冲突、重启读取；相同 Action 重签也不能替换冻结 op/request_ref |
| E4 / 闭环与恢复 | prepare→accept→claim→execute→settle；真实子进程 COMMIT 后退出恢复；工具丢应答查询同一事实；未知结果保留资源；重复操作只有一次执行效果 |
| 缓存与当前权限 | 命中映射仍检查当前 Policy ACL/READER 动作范围；新请求读取 W 当前业务状态，缓存保持原材料 |
| 能力边界 | 应用模块无私钥、seed 或自动批准导入；测试模拟审批 fixture 不作为 Agent 接口；DelegationProof 未实现，额外委托/身份字段拒绝 |

应用层新增 22 个测试；其中若干测试包含多项拒绝断言。测试用已登记真实密钥和模拟工业工具，并非生产身份系统或实体设备验证。

## 实际运行与失败记录

最终版本完整回归：**159/159 通过，488.176 秒，退出码 0**（原 137 项 + 新应用层 22 项），见 [完整原始日志](../../evidence/trusted-action-resolver-v1-20261017/full-regression-release.log)。运行期间全部 7 个应用/测试源文件摘要保持不变，见 [源代码摘要](../../evidence/trusted-action-resolver-v1-20261017/tested-source-sha256.json)。仓库检查通过：88 个 Python 文件、38 份当前文档、356 个本地链接、35 个既有 W 证据文件字节核对。

早期结果和失败均保留，不能用其中较早的通过结果替代当前版本：

| 日志 | 实际结果 |
|---|---|
| [red.log](../../evidence/trusted-action-resolver-v1-20261017/red.log) | 初始应用模块缺失，预期失败 |
| [application-first.log](../../evidence/trusted-action-resolver-v1-20261017/application-first.log) | 初版 15 项通过，57.849 秒 |
| [full-regression-01.log](../../evidence/trusted-action-resolver-v1-20261017/full-regression-01.log) | 中间版本 156 项通过，359.005 秒 |
| [review-red.log](../../evidence/trusted-action-resolver-v1-20261017/review-red.log) | 2 项复核测试：短 PACKAGE 导致 EXPIRED；延迟首次冻结未拒绝，1 error + 1 failure |
| [review-green.log](../../evidence/trusted-action-resolver-v1-20261017/review-green.log) | 上述两项修正后通过，11.164 秒 |
| [current-state-red.log](../../evidence/trusted-action-resolver-v1-20261017/current-state-red.log) | 新请求误读 C 初始业务状态，1 failure；原 W 仍阻止失效材料执行 |
| [full-regression-final.log](../../evidence/trusted-action-resolver-v1-20261017/full-regression-final.log) | 修正当前状态读取前的 158 项回归：1 error，424.542 秒。原 test_signer_failure_preserves_acceptance_and_blocks_claim 在 prepare 阶段报 CLOCK_UNKNOWN |
| [current-state-green.log](../../evidence/trusted-action-resolver-v1-20261017/current-state-green.log) | 当前状态修正测试及上述原时间测试单独复测，2 项通过，11.812 秒 |

CLOCK_UNKNOWN 的当次原因未定位；没有修改原时间测试或放松核心时钟限制。单独复测不能证明消除了所有环境相关时序风险，最终完整回归结果单独列示。

其他检查：[契约检查](../../evidence/trusted-action-resolver-v1-20261017/contracts.log) 371 项通过（30 envelopes、34 records、3 actions、3 tool evidence、70 Node checks）。[历史证据核验](../../evidence/trusted-action-resolver-v1-20261017/existing-evidence.log) 分别核验原 22 案例/5168 检查、3 案例/849 检查；只证明已固定历史包的签名、引用与账本一致性。核验脚本产生的三个新报告另存，原报告已按基线字节恢复，见 [保存记录](../../evidence/trusted-action-resolver-v1-20261017/verification-report-preservation.json)。

## 必要修正及问题性质

1. **软件工程：来源窗口交集。** 有效的短 PACKAGE 不应被新 Assessment 的过长有效期排除。构造时取 Task/Policy/IDENTITY/PACKAGE/E 的共同窗口。
2. **软件工程：首次冻结时效。** 签名链验证后仍可能经过时间；在同一事务内刷新 W 时间和批准/资格窗口，通过后才能首次冻结。
3. **软件工程：当前状态读取。** 新请求使用 WState 的当前 UNIT/BEHAVIOR；重复请求保持原构造、原 op 和摘要，以原 W COMMIT/outbox 恢复。
4. **设计边界：principal 的授权。** 当前权威为 C 认证 Task 中的 principal/holder 绑定；它不单凭签名证明现实业务权属。未来委托需单独定义 DelegationProof 的发行者、权限交集、撤销、有效期和 Action 绑定。

本轮没有证据要求修改 R2 Schema、既有签名域、COMMIT 或 EXEC-0。独立只读复核及修正范围见 [复核记录](../../evidence/trusted-action-resolver-v1-20261017/review-notes.md)。不将有限测试结果表述为普遍协议安全证明。

## 复现命令与环境

实际工作目录为 `<LOCAL_PATH> Python 3.14.7、cryptography 50.0.2、jsonschema 4.26.0。清除宿主预设 PYTHONHOME 后运行。CI 使用 Python 3.13，结果以 GitHub 实际检查为准。

```sh
cd <LOCAL_PATH>
# 最终完整回归；测试过程中原始 stdout/stderr 都写入同一个日志。
env -u PYTHONHOME <LOCAL_PATH> -m unittest discover -s competition/tests -v > <LOCAL_PATH> 2>&1
# 当前状态边界及原失败时间用例的单独复测。
env -u PYTHONHOME <LOCAL_PATH> -m unittest competition.tests.test_action_resolver.ActionResolverTests.test_new_requests_use_W_current_state_while_cached_request_stays_frozen competition.tests.test_time_acceptance.IndustrialTimeAcceptance.test_signer_failure_preserves_acceptance_and_blocks_claim -v > <LOCAL_PATH> 2>&1
# 下列脚本可能写生成报告，请在临时检出中执行并单独保存新报告。
env -u PYTHONHOME <LOCAL_PATH> system_dev/v26/tools/verify_contracts.py > <LOCAL_PATH> 2>&1
env -u PYTHONHOME <LOCAL_PATH> competition/docs/final/verify-existing-evidence.py > <LOCAL_PATH> 2>&1
# 只读范围、导入、链接与历史证据检查。
env -u PYTHONHOME <LOCAL_PATH> -m competition.verify_repository --report <LOCAL_PATH>
```

其他机器：从本功能分支临时检出、安装 requirements.txt 后，使用自身 Python 路径替换以上解释器和临时路径。只跑新增库可用 `python -m unittest competition.tests.test_action_resolver -v`。测试文件和 [test-only fixture](../../tests/resolver_fixtures.py) 随本分支交付；fixture 不得部署成 Agent 自动签署服务。

待后续最小集成：受信宿主接入真实 H 身份提供者与独立审批端、持久运行目录和受控暴露的提案端点，再进行部署环境时钟/重启验证。PAY/MED 简化提案、真实工具、HTTP/MCP、进程级密钥隔离、跨节点 ID 分配及 DelegationProof 均未声称完成。
