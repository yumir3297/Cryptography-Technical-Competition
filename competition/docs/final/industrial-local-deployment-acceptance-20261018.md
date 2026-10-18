# 工业场景本机部署配置验收报告

> 历史阶段记录：以下验证与“未推送”状态按当时保留。当前完整交付、替代关系与最新验证请从[统一交付入口](ind-complete-delivery-20261018.md)阅读。

日期：2026-10-18（Asia/Shanghai）。结论：**在用户确认的“本机服务＋工业模拟工具（竞赛原型）”范围内，通过部署配置验收。**

基线提交：63c5da6e6985d5d28102f1c905f2451abf7133a5。新增代码位于独立本地分支 deployment/ind-local-acceptance-20261018 的工作区；未创建新提交、推送、合并或修改旧统一整合仓库。以本次补丁及源码摘要标识新增版本。

## 1. 已落地的部署方式

新增[固定配置启动器](../../application/local_runtime.py)，从 service.json、原持久数据库和公开身份登记构建 RequestBoundW 与 OperationService，只监听 127.0.0.1:18765。启动不重新初始化旧账，原 W/应用/来源/工具关键账表缺失时直接拒绝。

业务宿主只加载 W 派发私钥；C、X 和工具密钥通过原客户端或受限子进程使用，并在启动时核对公开绑定。H/U/V/G/E 和 worker 私钥不被业务宿主读取。目录 0700、配置/密钥/token/数据库 0600；同一安装只能运行一个公开宿主。

[一次性模拟引导和验收操作端](../../deployment/README.md)与公开服务分开。操作端使用新生成的模拟角色密钥，经原 broker 生成真实签名；模拟批准不作为 Agent 的可调用批准或签名服务。初始引导者和同一 OS 用户仍拥有模拟私有材料，未声称独立 KMS/DAC 身份托管。

现有核心、Profile、工具运行规则、Schema、ActionHash、原签名域、DENY、时钟阈值和 EXEC 规则均未改动。新增代码是本机部署接线及验收，不扩大 PAY/MED 公开服务范围。

## 2. 实际验收结果

| 范围 | 最终结果 | 证据 |
|---|---|---|
| 完整回归 | 208 tests，0 failures，0 errors，572.885 秒 | [结果](../../../integration-evidence/deployment-joint-release/results.json)、[原始日志](../../../integration-evidence/deployment-joint-release/tests.log) |
| 配置及审查反例 | 12 tests 通过，36.131 秒；已包含在 208 项中 | [专项日志](../../../integration-evidence/deployment-config-release.log) |
| 最终字节版本的真实服务验收 | 12 项检查通过，实际启停四个宿主进程 | [结果](../../../integration-evidence/deployment-live-ready/results.json)、[脱敏结果摘要](../../../integration-evidence/deployment-live-ready/public-evidence-summary.json) |
| 配置预检 | --check 通过 C/X/W/工具绑定，未监听 HTTP | [预检记录](../../../integration-evidence/deployment-preflight-ready.json) |
| 离线签名与事实核验 | 15 份参与方/回执签名、根签工具证书、工具终局与 checkpoint、W 结算对应关系通过 | [只读核验](../../../integration-evidence/deployment-live-ready/offline-audit.json) |
| 独立只读代码审查 | 两项 Important 经红测复现和修正；复审无剩余 Critical/Important | [审查记录](../../../integration-evidence/deployment-review.md) |

真实服务验收包括：本机监听与重复宿主拒绝、错误传输认证与私有方法拒绝、同请求同 ID 与异内容冲突、缺 H 证明不保存、同授权短期更新与旧 ticket 拒绝、待接受请求重启恢复、丢弃接受响应后重启读取原 COMMIT、内部 worker 执行与结算、已结算状态重启恢复、真实 MCP stdio 认证恢复、私有文件权限。

最终真实账计数：**接受=1、attempt=1、EXEC 消费=1、工业模拟效果=1、结算=1**。重复执行/结算未增加效果。重启前后 Action、Permit、COMMIT、冻结 Core 和原 attempt 保持绑定。效果是 SQLite industrial_routes 的模拟事实。

208 项回归诊断仅记录专门注入时钟不可用反例的 CLOCK_UNKNOWN，测试按预期拒绝；没有因此放宽健康判定或阈值。该回归不证明所有历史时钟间歇原因已根治。

## 3. 发现、失败及修正

- 最初缺少部署启动器，红测按预期失败。
- 初版路径比较没有统一 macOS /var 与 /private/var 别名，导致配置误拒绝；规范化后通过。
- X 密钥错配初版未在监听前识别，真实反例复现后增加子进程公开绑定核对。
- 独立审查发现工具密钥错配检查过晚、缺表可能被原构造器建回空账。5 项真实反例先全部失败，再补工具受限预检及必要账表检查；反例均纳入最终套件。
- 修正前的 203 项回归也通过，但不能替代新增反例及最终 208 项结果。
- 补充安装因初始化后等待，120 秒 E 来源到期，propose 返回 EXPIRED。[失败记录](../../../integration-evidence/deployment-live-handoff/failure.json)及[诊断](../../../integration-evidence/deployment-live-handoff/expiry-diagnosis.json)保留：app_request、w_operation、w_outbox、w_settlement 均为 0。
- 随后使用明确独立的新模拟根/账本，把引导与验收连续执行，通过最终12项实际验收。没有重置失败安装、续期旧证明、改变时钟或绕过过期检查。

## 4. 测试源码与交付源码对应

完整208项运行期间源码摘要不变。为通过补丁空白检查，运行结束后只清理10个新增文件末尾的多余 LF；Python AST 一致，无行为修改。清理前的精确测试源码归档仅在原本地交付保留，因 ZIP 内两项本机路径条目而不上传；历史[测试前摘要](../../../integration-evidence/deployment-joint-release/source-before.json)和每文件变化见[格式处理记录](../../../integration-evidence/deployment-post-test-formatting.json)。

[最终源码摘要](../../../integration-evidence/deployment-final-source-sha256.json)记录清理后的文件；deployment-live-ready 的 source-before/source-after 对最终 Python 字节版本再次验收。没有为末尾空行清理重复完整回归，也没有把不同运行的数量相加。

## 5. 本机启动与新一轮演示

验收结束后服务已停止，私有安装保留在输出包旁的 private-installation-ready。根目录 start-industrial-local.sh 固定本机已验证解释器/依赖和该配置：

```sh
sh start-industrial-local.sh --check
sh start-industrial-local.sh
```

脚本在交付目录运行或使用其绝对路径；第二条在前台启动，Ctrl-C 正常关闭。service-ready.json 仅运行期间存在。token 和 lab-metadata.json 不在公开交接包内。其他机器按[部署说明](../../deployment/README.md)自行建立依赖与新的模拟安装，不能复制或伪造本机私有身份。

KEY/ROLE、worker、工具信任约30分钟，E 来源120秒，Assessment 最多90秒，短期证明最多30秒。预检成功不代表业务授权永久有效；新一轮完整模拟应连续执行新目录 provision→acceptance。已有操作的恢复继续使用原配置、账本和真实当前读取授权；启动器不承担正式重新审批或登记续期工作流。

## 6. 交付边界

完成本机工业模拟服务配置与闭环验收；真实设备、独立 OS 用户/生产密钥托管、远程服务器与多机状态均不在本次范围。原 R2 与竞赛变体的差异继续按[现有对照](r2-application-mapping.md)保留。

本报告保留验收时的事实；本次GitHub交付经脱敏，仅包含源码、部署说明、本报告、脱敏测试/审查/运行日志、核验结果记录与源码摘要；完整签名包仅本地留存，独立复核请重新运行实验。运行 SQLite、私钥、token 和模拟操作端元数据只留在本机私有安装目录，未上传 GitHub。
