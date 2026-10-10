# 时间与接受观察：二轮候选检查

对应[精确候选合同0.2](../../system_dev/v26/06_time_observation_candidate_contract.md)、[二轮设计](../../docs/research/2026-10-10-协议时间补全_二轮设计.md)及[关闭论证](../../docs/research/2026-10-10-协议时间补全_条件证明与关闭报告.md)。原R2接受和原39项状态不变；本目录不是产品服务或正式R3。

## 复现

```powershell
python -m pip install -r verification/protocol_time_closure_v2/requirements.txt
python verification/protocol_time_closure_v2/run_all.py
```

另需Node.js（CI固定22，开发本机24）。运行器保存`runs/<UTC>/tests.txt`、有限探索/反例`interleavings.json`、三个Profile的签名`vectors.json`、Node交叉检查和`results.json`。向量的17/34/51等32字节重复值是**公开测试私钥材料**，不得用于真实登记。没有真实服务凭据。

## 检查范围

- `codec.py`：规范JSON字节、重复键/Unicode/整数/base64url拒绝；Ed25519公钥/R规范非单位主子群检查、S<L，再用cryptography核等式。手写点运算仅筛查公共输入，不用于签署。
- `observation.py`：独立Query/Package结构及真实签名；原R2 Core/COMMIT三Profile结构和动作/时间/引用绑定；当前资格/账权限、可信挑战、受信FrozenRead、发布CAS/精确字节及接收时再检查。
- `schema.json`：新候选结构Schema；原Core/COMMIT还须按选定原Profile Schema验证。Schema不替代语义或信任。
- `test_*.py`：正负故障轨迹，含原sig从未存在/原回执过期、新观察钥、错事实/状态/查询/档案、撤销/ABA、无可信独立高水位、时钟跨界、重放及精确响应恢复。三Profile正常向量作为结构和候选观察路径示例，不是三Profile全部业务验收。
- `interleavings.py`：一个历史接受、一个服务查询事务、两个客户端绑定（第二只是重放目标），拆开read/sign/publish/receive/控制变化/时钟/状态；缺CAS反例与修复后有限探索。
- `check_vectors.mjs`：独立Node/OpenSSL重算三Profile签名、域和摘要，并检查改字节/误用R2签名域失败。它不是完整第二协议实现，不验证全部严格子群拒绝集合或C/W授权。
- 第一轮实验仍运行27项和原有限域，本轮修复了其持久时间下界使用hi的过度拒绝。新域与旧域分别报告，不合并状态数当更大证明。

## 可信输入边界

Authority、Grant、History、**FrozenRead**及Publication都来自可信C/W适配器。在研究中由固定测试输入表示：完整当前授权交集、历史合法性/真实持久接受、独立恢复高水位/连续账、W冻结读取/原子发布和可信时间。真实服务必须按query_ref查受保护的读见证，不能接收客户端提供的FrozenRead/Publication或自报roles。

检查器只是纯函数模拟这些合同转换，不实现网络、认证管理、数据库CAS、独立高水位托管、时钟设备、原承重历史图全量审计或真实工具。测试中的`archive_validated=True`、`continuous=True`等是前提，不能成为“独立历史安全证明”。未实现前提的真实系统不能仅接入此代码宣称合规。

publish有资格/时间/nonce/档案/控制revision检查，且保存完整响应；没有可信精确发布记录时，正确新签名也只能U。资格点是W发布，候选签名不是协议有效证明；原Acceptance真实签署资格仍按R2。

物理设备截止、无界网络下最终进展、完整39/66项、双实现互操作和恶意W均未由本目录证明。规则的条件关闭与这些工程义务在关闭报告中逐项区分。
