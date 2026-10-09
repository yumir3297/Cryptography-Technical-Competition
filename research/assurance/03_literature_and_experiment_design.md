# 相关工作、创新假设与可证伪对照实验

日期：2026-10-09。此稿是 **research positioning**，不是新颖性鉴定或系统性能结论。

## 1. 已有技术对 ZJJ 的挑战

| 对照技术 | 已有能力（简述） | ZJJ 应当回答的剩余问题 | 不可作出的主张 |
|---|---|---|---|
| OAuth 2.0 RAR / RFC 9396 | 能表达细粒度 `authorization_details`，例如付款金额和收款信息；建议请求完整性保护 | 独立 U 授权、依据范围新鲜度与 W 原子消费需要如何组合 | 「其他方案只能授权一个粗粒度 scope」 |
| OAuth mTLS token binding / RFC 8705 | 访问令牌可绑定客户端证书，抵抗单纯的 bearer 重放 | 证书持有证明之外如何验证授权依赖、业务意图及执行终局 | 「已有 OAuth 完全没有持有者绑定」 |
| Zanzibar (Pang et al., USENIX ATC 2019) | 因果顺序和外部一致性、全局授权状态 | ZJJ 的多方签署、动作唯一接受和工具终局之间新增何种 *specific* 保证 | 「首次提出一致的新鲜度授权」 |
| Macaroons (NDSS 2014) | MAC 链式委托与 caveats 细粒度限制 | ZJJ 的签名审批、拒绝集合、W 事务/效果证明和 caveats 的差异 | 「首次使用附带条件的许可」 |
| Cedar / AWS Verified Permissions | 对 principal/action/resource/context 做 ABAC/RBAC 判定，permit/forbid 模型 | ZJJ 是否给出比单次授权判定更多的时序安全保证 | 「现有授权引擎都没有 deny 优先」 |
| SPIFFE/SPIRE | 工作负载身份认证、短期证书与轮换 | 将可信身份映射、工具终局认证与持久事实绑定的端到端证明 | 「现有工具没有密钥轮换机制」 |

参考原始资料：

- RFC 9396: https://www.rfc-editor.org/rfc/rfc9396.html
- RFC 8705: https://www.rfc-editor.org/rfc/rfc8705.html
- Zanzibar: https://www.usenix.org/conference/atc19/presentation/pang
- Macaroons: https://www.ndss-symposium.org/ndss2014/ndss-2014-programme/macaroons-cookies-contextual-caveats-decentralized-authorization-cloud/
- Cedar: https://docs.aws.amazon.com/verifiedpermissions/latest/userguide/terminology.html
- SPIFFE/SPIRE: https://spiffe.io/docs/latest/spire-about/use-cases/

**文献没有覆盖所有现有系统和学术成果；以下创新点是待证伪假设。**

## 2. 三个可证伪贡献假设

**H1 动态闭包 + 原子接受：** 验证器独立重建所有承重依赖及空集合覆盖版本，并在 W 接受事务重新检查，能够排除「局部有效、整体过时」的授权链。对照 Zanzibar 的因果一致访问与典型带签名交易请求，测试同类性质是否已有直接实现。

**H2 不可变终局事实与可更新证明：** `FinalFactID` 不随认证钥/iat/exp 改变，旧证明失效时工具只读同一持久账可再签，W 不重复结算。对照一般幂等键 + 事件日志 + 再查询，以及常见 key rotation 处理，确认实际优势是否只是语义集成，而非已有原理。

**H3 明确区分 ACCEPTED、EFFECT_UNKNOWN、SUCCEEDED：** 在丢失确认的 started 状态保留占用且不自动重派，减少重复效果风险。代价是可用性下降；与具备幂等业务 API/事务外盒 (outbox) 的公平基线比较，不能把它们设定为「无幂等」。

## 3. 公平对照矩阵（设计，未运行）

对 B0–B3，使用相同的两类签名/密钥材料、相同 C/W 信任前提、同样的 action 和场景数据。明确记录每个系统 **是否设计支持该性质** 和 **实际实现结果**，不把「不在某方案范围内」记为漏洞。

- **B0**: 基础带签名动作和持有证明，无显式审查/终局机制（能力较弱的教学消融基线，不冒充真实主流部署）。
- **B1**: RAR 描述细粒度权限 + PoP + 在线授权重查 + W 单意图幂等事务；此为公平增强基线，需要实现和标注文献依据。
- **B2**: Zanzibar 式一致权限查询 + 独立签名 + 事务唯一接受；再补工具恢复作为独立正交维度。
- **B3**: ZJJ 完整候选与逐项消融（忽略独立 U、范围版本、DENY、幂等、再认证）。消融数据来自抽象模型必须明确只证明模型差异。

每个场景至少比较：授权撤销与 Commit 同时发生、空集变非空、G 产生不正确 Permit、相同意图 8 路并发、启动后回执丢失、工具合法换钥、两份同事实不同签名、账恢复失败。

**指标**：
- 安全：未授权接受条数、相同意图重复接受条数、重复效果风险标志、错绑终局接受条数、反例轨迹长度；
- 可用性：成功完成比例、永久 unknown 比例、合法恢复次数及时间上界（区分保证与观测）；
- 成本：每路径签名数、验签数、结构字节、引用图节点数、W 事务读写集、存储量、p50/p95 延迟、CPU 占用；
- 可复现：种子、环境、版本、输入哈希、脚本、独立 oracle。

## 4. 实验解释规则

1. `primitive_bench.py` 只测本机 Ed25519/SHA-256/编码 microbenchmark，不代表 ZJJ 端到端延迟。
2. `abstract_checker.py` 的反例是抽象模型变异，不代表攻击真实 OAuth、Cedar 或已部署服务。
3. 没有真实协议参考执行器之前，39 项规范语义验收仍是 `NOT_RUN`，且 66 项产品验收不属于当前密码协议作品的主要指标。
4. 可用性取舍要直说：宁可在工具效果未知时保留占用，也不制造没有依据的重试成功；是否满足目标业务 SLO 尚待评估。
