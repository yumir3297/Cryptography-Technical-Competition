# 协议收尾交付记录

2026-10-11 · `COMP-PROTOCOL-FINAL-1.0` · 协议设计、完善与所选模拟展示可行性

## 基线与实际修改

本轮先搜索工作区及父路径 AGENTS.md，未发现适用文件。Git 实际分支 `competition/zjj-core-final-20261010`，HEAD `42021274a2f7d6adf35337bb153f05bf89b3e8f9`；原未提交 `competition/evidence/` 和 `tmp/` 保留。最新本地交接为 13 W 实现报告及 07§7，覆盖 P/A/W 已完成能力；未将远端缓存或历史 CI 当成本轮状态。

交付为一份精简协议说明、一份查询审计口径、工业/付款/医疗三份开发交接、一份声明证据清单和本记录；由 [FINAL_PROTOCOL_HANDOFF](../../FINAL_PROTOCOL_HANDOFF.md)及仓库首页导向。根交付规格增加当前协议收尾入口，旧产品计划保留为历史/后续开发资料；根资料交接目录提供相同正文副本和新记录。

新增 `competition/verify_protocol_handoff.py` 仅复用已有真实组件验证所选拒绝/读取路径，不修改 P/A/W、签名、模拟工具、原 Schema 或消息定义。没有新增正式 STATUS/AUDIT 输出；当前展示所需的认证本地查询、原签名附件与离线核验均按实际范围说明。

W 原运行包绑定 `competition/README.md` 和五份开发合同原字节。本轮保持这些文件及研究/system_dev 资产不变，新入口明确原分阶段状态的来源身份，使既有摘要核验仍可复现。对外有效描述以本轮协议材料与共同 W 实际证据为准。

## 本轮验证及复现

以下命令在仓库根执行。报告使用新路径，不覆盖原证据；若输出目录已存在，补充脚本拒绝复用，改用新的目录并登记新证据身份。

```powershell
python -m competition.verify_w_slice competition/evidence/w-slice-20261011-final --manifest-sha256 65ee659c9636cf41e2de8647b5c49005d762cdf3074bc2e65ac6579952df0eda --report competition/evidence/protocol-final-20261011-w-verification.json
python -m competition.verify_protocol_handoff --output competition/evidence/protocol-handoff-20261011-final
```

附加同 ID 包使用 `competition.verify_w_slice.verify`，传 `expected_case_count=3` 和外部 pin `ab853d979c9853a966c7f771070115b82ab3dd62f4e8507168ba49f5110eb640`；完整调用保存于[核验脚本](verify-existing-evidence.py)，报告为 [same-oid-verification](../../evidence/protocol-final-20261011-same-oid-verification.json)。主包 CLI 固定默认 22，不能直接当 3 例包入口。

| 验证 | 实际范围与结果 |
|---|---|
| 既有共同 W 包重核 | 22 例，5168 项检查，3498 次验签、1538 个 C 时间包，外部 manifest pin 通过；无新业务执行 |
| 既有跨 Profile 同 ID 包重核 | 3 例，849 项检查，585 次验签、246 个 C 时间包，外部 pin 通过；无新业务执行 |
| 本轮最小展示验证 | 6 例：三场景共同 W 拒绝缺必要复核；三场景认证读取、重放拒绝及预签请求撤权拒绝，读取业务计数不增 |
| 文档与来源核对 | 见 [机器核对报告](../../evidence/protocol-final-document-check.json)：当前链接、双份正文、原证据摘要及原文件保留检查 |

补充六例使用随机真实钥、C 认证当前登记、真正 H 签名链和同一 CommonW。缺复核路径在共同 prepare 拒绝，不声称它执行了 accept 或工具；读取例先实际接受，然后核正常 status/audit 和拒绝，工具未调用。故障退出、并发、正常与结算复用既有 22 例，不为文档收尾重复开发。

## 规则与实现选择

协议规则是精确动作绑定、必要批准与完整否决、独立重算、当前性、持久接受后冻结回执、唯一 attempt、EXEC-0、未知保守恢复、FinalFactID 一次结算及可信矛盾停止。比赛实现选择是受信单机、固定 roster/有限登记图、同 W 持久事务域、三个签名模拟工具、C 签本机时间以及认证应用投影和外部 pin 离线审计。

原规则与比赛应用差异已在协议对应表限定：输入链统一完整 deps、Acceptance.deps 为空并在 COMMIT 归档资格、Review 受众 H/G/X、资格按事件检查而不预缩整个 Basis 寿命、异常回滚应用事务且不形成原协议拒绝响应账。应用挑战/错误码与原 wire 消息分层，投影没有完整签名 Result/AUDITBundle；长期换钥和工业复检保留规则身份。这些选择用于比赛模拟路径，不改变原 R2 结构字段或历史研究结论，也不声称完整 R2 消息语义符合。

本轮另运行工业/医疗与付款授权适配器的 15 项相关组件回归，全部通过，日志见 [component-check](../../evidence/protocol-final-component-check.log)。补充六例报告保存执行当时的源码/文档摘要；此后仅收敛上述协议文字与交付记录，运行代码摘要保持一致，最终正文摘要另由机器核对报告登记。

本轮交付内容限协议材料和最小展示验证。界面、安装包、产品会话与产品化由开发后续衔接；本轮没有提交、推送、合并、创建 PR 或向其他聊天发送指令。

补充验证首次将明确 ROLE 撤销预期为 NO_ROLE，实际拒绝码为 REVOKED。按 systematic-debugging 核对 current() 的 active 守卫后，仅修正新脚本预期；[首次记录](../../evidence/protocol-handoff-20261011/first-run-assertion.json)及部分输出保留，最终六例使用新目录，不删除原记录。

随后用户要求复检结构、语气和比赛执行流程：正文精简，R2 字段差异移至开发对照，比赛前提与暂不扩展行为加开发注释。此次新增材料、实际接法和验证以[复检记录](protocol-review.md)为准；原 22＋3＋6 例、15 项组件结果保持其原记录身份。
