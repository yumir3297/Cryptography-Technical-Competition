# 安全边界与签署入口契约

2026-10-12 · 比赛执行协议 `ZJJ-CORE-COMP-1` · 配套说明版本 `CORE-SPEC-1.3`。

本页是实现安全边界与接口契约；[共同协议](competition-protocol.md)规定原则，[比赛开发总交接](scenario-integration-handoff.md)规定固定配置与三场景接法。说明版本更新不更改下述认证 wire 标识。

## 攻击者与受信能力

比赛中的 agent 是提供候选 Action JSON 的模块，可以猜测、遗漏、替换或重放候选内容，不能为自己登记身份或批准。H 可以提交自己签署的完整请求及读取凭据，也可以提交恶意请求。网络或调用方可以截留、篡改和重放消息。W 不采用这些参与者自报的安全结论或成功标签。

| 主体 | 获准能力 | 受控边界 |
|---|---|---|
| agent | 向 CandidateIngress 提供严格 Action 字节；根据已获准裁剪数据提出候选 | 无 C/U/V/G/X、worker、W-delivery 或工具私钥；无可信回调代码、shell、密钥文件或账库写权限 |
| H | 用自己的登记密钥证明请求与读取身份 | H proof 不能请求 U/V 签名、代替 worker 或修改已冻结动作；H/U 同 subject 的允许情形仍分别核验对应 kid |
| U/V/G/X | 对自身登记角色、用途和范围内的确定消息签署；X 回执仅签原 COMMIT 的 Core | 当前资格由受信守卫复核；无默认按 alias 代签入口 |
| worker | 用 C 授予的能力触发领取、首次执行、查询、结算及合法取消 | 无业务批准权或任意动作派发权；工具只接收 W-delivery 认证的冻结派发 |
| C 与受控初始化者 | 登记根、公钥、角色、策略、固定图与运行环境；演示辅助器生成各角色真实签名 | 属受信管理职责；不开放给 agent/H；脚本自动批准代表签名模拟角色，不代表已采集真人同意 |
| W、受控签名进程及模拟工具 | 验证、持久记录并按协议推进 | OS、本地文件、根配置、私钥保存及唯一执行入口受信；进程分离用于职责约束和故障复现 |

签名安全依赖登记根与对应私钥未被攻击者取得。受信 OS/文件管理者不属于本轮攻击者；同一 Windows 用户若取得任意 shell 或账库/私钥访问权，超出了上表 agent 权限。Python 私有属性和 chmod 不作为 Windows ACL 隔离证据。将来给 agent 加入文件或命令工具时，先建立独立账户/受限进程或服务权限，再复用本协议。此处是开发接入条件，不增设比赛设施门槛。

## 有认证的比赛语义标识

十类比赛消息的 `protected.proto` 固定为 `ZJJ-CORE-COMP-1`，`version` 仍为字段基础版本 `2.6`。Ed25519 签名仍覆盖 `canonical(['ZJJ-SIG-v1', protected, body])`，因此 proto 也被签名认证；接收端固定预期值，不从输入选择规则版本。把旧签名换上新 proto 会验签失败，重新签过的原 R2 `ZJJ-AAP` 消息仍被比赛接收器拒绝。

[CompetitionSchema](../../support/schema.py)由保留的 R2 Schema 构造比赛视图，只更改十类消息 proto 常量；不改原文件、ActionHash、RecordRef、字段或枚举。付款原来源 Envelope 及工业/医疗来源、登记和工具终局使用各自保留的认证格式。原 R2 客户端不能直接把比赛批准/Acceptance 当作完整 R2 响应；对应差异见[R2 对照](r2-application-mapping.md)。

共同 W 的运行初始化记录同时固定此标识。已有运行若未登记该标识，当前 W 拒绝打开，不能自动迁移、清账、补签、改时间或重新领取；历史包继续按其原构建核验，旧运行的恢复须保持原版本与密钥及账身份。保留的工业时间组件明确采用原 R2 标识，不能作为共同 W 的比赛状态传入。

## 实际签署调用

[ScopedSignerBroker](../../core/signer_broker.py)新增以下受控接口：

```python
challenge(profile, alias, unsigned, action)
sign(profile, alias, unsigned, action, *, caller_proof=None)
```

challenge 返回 `claim`，包括 `proto/profile/scope/alias/subject/kid/request_ref/nonce`。`request_ref = digest(['COMP-APP-SIGN-REQUEST-v1', profile, alias, unsigned, action])`；调用角色以自己的登记密钥签 `canonical(['COMP-APP-SIGN-CALL-v1', claim])`，形成 `{claim, signature}`。客户端不能替换 claim 的角色、kid、内容、动作或范围。

sign 在同一受信事务核证明、服务端登记 nonce 的内容绑定及 30 秒窗口、一次使用、当前 KEY/ROLE/用途/业务范围、Schema、动作绑定和消息窗口；返回签名之前再刷新受信时间区间，复核 nonce、消息与资格窗口，样本过旧则拒绝。缺少 proof 为 SIGN_CALLER_REQUIRED；内容绑定失败为 SIGN_CALLER_BINDING；重复消费为 SIGN_CALLER_REPLAY。错误请求不返回签名，事务回滚。Malformed 输入转为 BROKER_FIELDS 或相应明确协议错误。一次性 nonce 不是实际批准本身，批准仍由 Authorization/Review 的签名内容及核心条件表达。

[AuthorizationRun.sign](../../profiles/authorization_seed.py)是受信演示辅助器：它显式取得对应 U/V/H/G/X 的真实 proof 后调用签署代理。代码验证持钥身份和范围；真人看到哪个界面、是否理解内容及点击证据属于后续软件的批准采集环节。软件接入不得向 H/agent 交付这一辅助器或全角色密钥集合。

## 候选输入与恢复处置

[CandidateIngress.parse(profile, blob)](../../core/candidate_ingress.py)只接收至多 64 KiB 的 canonical JSON bytes，拒绝重复键、未知字段、错误 scope、代码/回调/凭据路径和非 Action 对象；深层 JSON 与超长数字统一返回 LIMIT/NUMBER 等协议错误。解析成功只返回 Action 数据，不签署、不接受、不占用、不派发。上层构造完整链时仍独立重建依据并取得必要批准。AuthorizationService.read 的 Python candidate 回调只供受信启动配置，不运行 agent 生成的 Python。

遇到回执待签、执行效果未知或可信矛盾停止：H 可凭当前资格读取同一操作状态/审计，worker 可按当前权限查询原 attempt 并提交可信终局结算，受信负责人核对原 COMMIT、EXEC 标记、工具账身份和证据。负责人可以停止演示与保全资料，不能凭口头“未成功”、超时或新 operation_id 释放未决占用、删除意图墓碑、改动作或重授执行权。查不到或读取权限不可用时继续保留事实与占用；已有可信终局才按原规则结算。比赛不提供管理员强行成功/失败或人工重派接口。
