# 2026-10-12 实际整改与验证（1.2 运行记录）

本页保留 1.2 运行与修复身份；当前共同说明 CORE-SPEC-1.3 的文档分层见[本轮记录](protocol-separation-record-20261012.md)。

本次代码整改说明 `COMP-PROTOCOL-FINAL-1.2`，比赛执行标识 `ZJJ-CORE-COMP-1`。工作分支 `competition/zjj-core-final-20261010`，提交基线 `1aa5a9e`；本轮修改保留在工作区，源码文件身份与日志按证据列出，不宣称已推送。

## 实际修复

| 项目 | 修复与目的 | 层次 |
|---|---|---|
| 比赛与原 R2 的语义识别 | 十类 Envelope 的 protected.proto 固定为 ZJJ-CORE-COMP-1；原 R2 消息即使签名真实也被共同 W 拒绝；运行初始化固定标识，重启不能默许旧账 | 协议规则：认证语义身份；实现：比赛 Schema 视图、运行记录 |
| 请求签署的主体 | 对应登记角色签 caller proof，绑定整个 unsigned/Action/profile/角色；一次 nonce、窗口、当前凭证在事务内核验；H 不能凭 alias 请求 U/V 代签 | 协议规则：签署请求身份与内容认证；实现：30 秒 nonce/角色模拟器 |
| W 更新后的新请求依据 | 从共同 W 当前 Behavior/场景状态重建；取消后请求准确到达 INTENT_CONFLICT，不再被旧 C genesis 误判 BASIS_BINDING | 实现修复；永久意图与原来源寿命规则保持 |
| 签署中途跨界 | 返回前重验受信时间区间、caller nonce、消息及角色窗口，迟到签署拒绝并回滚 nonce 消费 | 实现修复；通过真实延迟 RED→GREEN |
| 深层候选输入 | 64 KiB 内的极深 JSON、超长数字及错误 profile 类型统一协议错误，宿主可以正常处理拒绝 | 输入实现修复 |
| 畸形签署参数 | KeyError/TypeError 等转换为协议错误，拒绝请求且不交付签名 | 实现修复 |
| agent 与人的批准责任 | 严格 Action JSON 字节入口；明确能力、私钥归属、可信回调与人工处置范围 | 协议/集成约定；不以私有属性或进程分离宣称 OS 权限隔离 |

这些改动复用原字段结构、签名域、ActionHash、RecordRef 与既有 P/A/W；不增加新核心消息 type、结果枚举、业务重办代际或生产部署设施。完整设计目的仍见[精简协议](competition-protocol.md)。

## 修复效果与实测范围

独立只读审查发现并修复上述签署中途跨界和深层输入问题，原失败及修复后测试保留。本轮全量回归结果见[验证总表](../../evidence/security-rectification-20261012/validation-summary.json)。

新回归直接检查原 R2 真签名混用、缺 caller proof、H 冒充 U、内容替换、nonce 重放、签署前撤权、畸形输入、当前 W 依据、运行标识固定，以及候选代码/路径/未知字段/重复 JSON 键拒绝。失败测试、修复后日志、首次完整回归与最终完整回归分别保留，不能用一次绿灯替代失败记录。

[安全检查结果](../../evidence/security-rectification-20261012/report.json)包含 13 项选择验证：6 条对抗拒绝、三个场景各一条正常路径、一个签名批准参照对比、三个场景各一条真实丢应答恢复。另有三个场景各 24 次认证 status 读取，8 个并发调用者，共 72 次；报告逐场景列成功数、错误及耗时，读取前后业务计数保持不变。该负载是本机固定规模试验，不推定分布式或生产吞吐。

[普通签名批准参照](../../evidence/security-rectification-20261012/signed-approval-comparison.json)与 W 使用同一份完整真实签名链、当前依赖及批准检查；参照也持久拒绝相同 operation_id 的重放。新的 operation_id 加真实重新批准时，参照可接收同一业务意图，W 则在接受点以 INTENT_CONFLICT 拒绝，并保持一次签名模拟效果。此结果显示业务意图持久去重的作用；不是“普通签名无法实现去重”或密码学新颖性的证明，参照的计数是接纳请求数。

[三场景 W 原始账包](../../evidence/security-rectification-20261012/w-slice/report.json)保存新的比赛标识、真实子进程、独立 W/工具账、原 COMMIT/Acceptance、FinalFactID 和恢复结果；[离线重核](../../evidence/security-rectification-20261012/w-verification.json)复用现有独立核验器。旧 22+3 例证据不重写，仍按原构建身份核验；新标识不能回写到旧包。

时间检查保留 iat ≤ lo、hi < exp 和两秒样本年龄上界。首轮串行演示在处理到医疗前，预先签好的 30 秒挑战已经 EXPIRED；调整为每条展示路径新建受信演示 fixture，按时处理真实批准链，没有放宽窗口或复用到期签名。已有跨秒、迟守卫、时间回退和到期测试继续检查安全拒绝。局部并发读取零 CLOCK_UNKNOWN 不等于任意负载都可用。

## 保留的边界与文书对应

业务范围的 DENY 暂停、效果提交前即时撤销、取消后的同意图重办是不同规则需求，仍按[开发注释](developer-scope-notes.md)限定。未知占用及原墓碑保留，负责人按[处置权限](security-boundaries.md)调查和查询，不能直接改成可执行。正式 R2 STATUS/AUDIT 与认证应用投影继续区分。

比赛文书围绕明确机制与信任前提表达保证；真人批准采集、同用户任意 shell 隔离与真实工业/银行/临床接入分别保留其责任身份。规则已定义、组件已验证、端到端已运行见[声明与证据](claims-evidence.md)，不把签名角色模拟或局部试验升级为现实效果承诺。

复现：从仓库根目录执行下列命令，output 必须是新目录；运行私钥仅写入忽略的 .runtime。

```powershell
python -m unittest discover -s competition/tests -v
python -m competition.run_security_checks --output competition/evidence/my-new-security-run
```

对 w-slice 子包使用 `competition.verify_w_slice.verify(path, expected_case_count=6, expected_root_manifest=外部保存的清单SHA256)`，结果写到另一路径。清单外部 pin 和构建哈希共同限定证据身份；签名核验次数不等于执行次数。
