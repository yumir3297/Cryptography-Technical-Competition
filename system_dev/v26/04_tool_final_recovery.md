# 工具终局事实与再认证合同

日期：2026-10-07。合同修订：ZJJ-CORE-2.6-R2，支撑方法`tool-final-v2`。关闭R1审查A02：工具效果已确定但首次回执延迟过期/遇换钥，以及同事实新签名被误认为矛盾终局。核心10消息和Envelope.version="2.6"不变；本文件定义工具支撑记录和恢复语义，不交付工具/产品服务。

## 1. 精确记录、不可变事实与身份

Record外壳仍为`{version:"2.6",profile,kind,scope,value}`，按对应Profile和kind严格解析。

```text
TOOL_TRUST.value = {
  issuer:Id,tool:Id,tool_version:Id,destination:Id,
  ledger_id:Id,evidence_method:"tool-final-v2",
  public_key:B32,kid:B32,epoch:Positive,iat:Time,exp:Time
}
TOOL_FINAL.value = {
  method:"tool-final-v2",ledger_id:Id,
  operation_id:B16,action_hash:B32,dispatch_attempt:B16,
  tool:Id,tool_version:Id,destination:Id,
  outcome:"SUCCEEDED"|"FAILED_CONFIRMED",effect_id:Id|"",no_late_effect:Bool,
  final_seq:Positive,finalized_at:Time,
  iat:Time,exp:Time,attestation:{issuer:Id,kid:B32,sig:B64}
}
```

FinalFact是TOOL_FINAL.value中精确的以下子对象，全部不可变：

```text
{ledger_id,operation_id,action_hash,dispatch_attempt,tool,tool_version,destination,
 outcome,effect_id,no_late_effect,final_seq,finalized_at}
FinalFactID = B64url(SHA256(Enc([
  "ZJJ-TOOL-FACT-v1","2.6","tool-final-v2",profile,scope,FinalFact
])))
FinalToSign = Enc([
  "ZJJ-TOOL-FINAL-v2","2.6",profile,scope,
  TOOL_FINAL.value_without_attestation,{issuer,kid}
])
```

FinalFactID为派生标识，不放进自己的摘要输入、不增加自引用字段。RecordRef仍标识整份Record，包括认证字段；更新iat/exp或换签署钥会改变RecordRef，但同一事实的FinalFactID保持不变。scope/Profile也进入事实标识，不能跨域、跨场景复用。不得把两种标识混为幂等键。

`finalized_at`是工具首次原子固定该终局事实的可信时间，不是每次查询时刻；`final_seq`是该ledger内首次终局的单调序号，两者不在再认证时更新。iat/exp是本次认证的有效期，0<exp-iat≤900秒，finalized_at≤iat且exp不晚于当前TOOL_TRUST.exp。签名算法/公钥/签名点采用核心严格Ed25519规则，不从record加载任意算法。

SUCCEEDED必须effect_id非空且no_late_effect=false；FAILED_CONFIRMED必须effect_id为空且no_late_effect=true。后者必须是工具账已持久固定的“不生效且不会迟到生效”终局，不能从查询不到记录推导。effect_id在完整(scope,ledger_id)内永久唯一，并绑定其操作/attempt；final_seq在同ledger内永久唯一，不被第二个事实复用。未知不是TOOL_FINAL.outcome。

## 2. 账本连续性与领取冻结

TOOL_TRUST由C认证发布，当前键仍为`[domain,tenant,scenario,tool,tool_version,destination]`，同键最多一个活动映射。公钥严格有效、kid=KeyID(public_key)、epoch/revision单调、寿命≤31536000秒，撤销墓碑保留。evidence_method必须精确等于tool-final-v2，不协商或降级。

ledger_id由C受控登记，标识这一工具目的端的持久效果账，不由H、G或网络响应选择。其注册身份元组固定为(scope,tool,tool_version,destination,ledger_id)，不得重用于不同账。C轮换工具钥或工具认证主体时，只有核验同一账的不可变操作、终局、唯一effect_id及final_seq完整连续后，才能保留ledger_id；该核验、移交批准和前后认证映射须永久留存于控制发布证据。仅设置相同ledger_id字符串不构成连续性证明。

账丢失、回退、部分拷贝或无法确认连续性为U：不得为原ledger激活新认证映射，也不能为未知操作签FAILED_CONFIRMED。新账必须新ledger_id，只能服务新操作，不能结算旧账的未决attempt。恢复依赖诚实C/工具及可用持久账；本修订不保证丢失账或工具失陷仍可恢复。

ClaimDispatch在原pending→started事务中，除核心资格/占用检查外，读取当前TOOL_TRUST，核scope、工具三元组、method、公钥、有效时间和撤销；冻结不可变的派发见证：

```text
DispatchWitness = {scope,operation_id,action_hash,dispatch_attempt,
                   tool_trust_ref:B32,ledger_id:Id,evidence_method:"tool-final-v2"}
```

tool_trust_ref是领取时TOOL_TRUST原RecordRef，必须与W所保存原登记证据一致；恢复不要求它今天仍活动，但它证明本attempt最初归属哪个账。恢复另用当前映射认证，其ledger_id与注册身份元组必须匹配原见证。这个见证不反写已冻结COMMIT/Acceptance，避免修改历史回执或摘要环。

实际工具请求固定为`{action:COMMIT.frozen_tool_request,action_hash,dispatch_attempt,ledger_id}`；最后三个字段来自W唯一派发见证及原Action摘要。工具须核映射和ledger归属，不接收客户端另加效果参数。EXEC-0的原应用层执行调用仍至多一次；再认证不是该执行接口的另一次调用。

## 3. 首终局与历史事实再认证

工具首次完成或确认最终无效果时，在同一个持久原子事件中固定FinalFact、唯一序号/效果身份、操作终态与防迟到门闩，然后签当时新鲜的TOOL_FINAL。先签响应但效果/终局账未提交，不构成可结算证明。FAILED_CONFIRMED必须使随后迟到的原执行请求也不可能产生效果。

受认证的W恢复职责可以只读查询`(scope,operation_id,action_hash,dispatch_attempt,ledger_id)`，调用固定内部职责`ReattestFinal`。只读查询和本地签署不触发执行、不回pending、不产生新effects、不增加final_seq、不改任何FinalFact字段。它不是新的核心公网端点，不能由STATUS查询直接触发工具执行。

| 工具账情况 | 再认证结果 |
|---|---|
| 原attempt持久终局完整、账连续、当前认证映射为T | 从原FinalFact逐字构造新的TOOL_FINAL，用当前允许的工具钥与当前可信时间签名 |
| 原attempt仍执行中、效果不明，或可信时间/账暂不可读 | 返回受控未知；无TOOL_FINAL、无结算/释放/执行 |
| 未找到原attempt记录 | 不能生成FAILED_CONFIRMED；仍未知并调查原账，不换账或重派 |
| 相同绑定下出现相反终局、不同effect_id/seq/time，或账无法解释的回退 | 矛盾/完整性事件；停止再认证，W保持HALTED或未知占用 |
| 当前钥不能签，或当前工具映射未被合法激活 | 保留未知，不用旧过期证明直接首次结算 |

当前认证者只能声明同一持久账中原来已经固定的事实，不能从客户端提供的旧签名/自报字段复制事实。旧签名过期或钥已撤销不会被此规则直接当成可信；恢复的信任来自当前工具认证、账连续性及原派发绑定。

## 4. W的验收、幂等结算与矛盾处理

除已经确认保存的完全相同RecordRef/原字节历史重传外，任何首终局或新再认证都先执行以下验证，未通过不得改变资源、在途或操作终态：

1. 严格解析外壳/精确method/Profile及全部字段，重算RecordRef与FinalFactID，严格验签。
2. 当前TOOL_TRUST及其C认证、来源通道身份、epoch/撤销/有效时间为T，issuer/kid及公钥匹配；本次TOOL_FINAL.iat/exp按W可信区间为T，finalized_at≤iat。
3. scope/op/AH/attempt/工具三元组及ledger_id精确匹配原DispatchWitness/COMMIT.Action；核原trust见证、当前同账授权与连续性。没有started派发见证，不接受工具成功来生成一笔新接受或结算pending取消。
4. 终局的outcome/effect_id/no_late_effect结构和永久唯一性成立。不同操作复用effect_id或final_seq是工具账冲突，不作为另一笔正常成功结算。
5. 在同一W事务内读取该操作已确认FinalFactID、状态、逐操作预占及总账，然后执行下表。认证预计算的映射/范围见证也在此事务重验；换钥/撤销与结算按W同序。

| W已确认事实与输入 | 转换 |
|---|---|
| 无原事实，started/EFFECT_UNKNOWN且全部验证T | 原子保存事实/原认证证据、该次RecordRef与当前trust见证，按outcome恰一次结算并释放适用在途 |
| 已确认同FinalFactID，同事实完整字段相等；新RecordRef通过当前认证 | 保存可选的再认证证据，返回原结算及当前状态；不增加settlement_count，不再次释放/转支出 |
| 完全相同已确认RecordRef及原字节历史重传 | 用已保存历史认证/原公钥核验并返回原结算；不要求旧证明/钥今天仍有效，不进行新结算 |
| 同操作/attempt但通过认证与绑定的新事实与原已确认事实不同 | HALTED，保存矛盾证据，保留既有结算账及尚未结算占用；不反向改账、不择一重派 |
| 未认证、签名坏、时间未知/过期、错op/attempt/ledger或其他错误绑定 | 拒绝/暂缓该输入，原操作账不变；任意网络垃圾不能只凭“不同Ref”将操作HALTED |
| 原操作已HALTED | 合法相同事实只能返回当前HALTED及原结算；再认证不能自动解除停止或补第二次结算 |

事实比较以scope/Profile/FinalFact完整内容及FinalFactID为准，不以RecordRef不同判矛盾；其中哈希相等仍应核对归档的完整事实。未确认的不同身份/绑定包应先拒绝，不能当成原操作有一个可信相反终局。W所有结算事件按(scope,operation_id,dispatch_attempt)唯一，资源/Flight/累计墓碑规则保持原合同。

STATUS仍仅查询W快照。收到当前再认证只允许恢复已有attempt的结算，不创建Accept、Permit、nonce执行权或Dispatch。正常轮换所需再认证不会重新执行；坏映射、账丢失、可信时间长期不可用仍可能持续未知，这些前提不由密码学保证。

## 5. 兼容与验证边界

R1的TOOL_FINAL/TOOL_TRUST缺ledger/method/原事实时间，不能补默认字段、把旧sig换标签或自动解释为v2。已有已确认历史R1结算保留原字节和账，不再次结算；未确认历史R1终局只有在C明确登记连续的原效果账、当前工具从该账核验完整原事实后，才能生成v2再认证。没有这种出处不能迁移成功。此前R1尚未交付完整产品，不声明已有在线迁移实现。

本修订使用既有SHA-256/严格Ed25519与受控账，不引入新的密码原语、核心消息或执行轮次。新鲜证明可多次签署，工具效果及W结算仍各按原身份唯一。局部测试覆盖真实签名/摘要/时间/换钥/重复/矛盾及占用模型；模型不是三场景产品、真实工具账、分布式/崩溃一致性或完整协议互操作证明。完整系统及C移交验证仍由开发实施。
