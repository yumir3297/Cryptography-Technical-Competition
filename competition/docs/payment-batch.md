# PAY-1 批次封账与第三单支付

在比赛工作树根目录（包含 `competition/` 和 `requirements.txt`）运行。示例使用 PAY-1 原有单笔配置 2,000 分，同一付款池的容量设为 4,000 分。每轮创建独立的临时主账、支付工具账和夹具密钥。命令输出公开证据 JSON 和最终对账摘要。

```powershell
python -B -m competition.run_payment_batch --output .runtime/payment-batch-demo.json
```

| 阶段 | 主账预占 | 主账累计支出 | 可用 | 工具累计实付 | 旧单结果 |
|---|---:|---:|---:|---:|---|
| 两个尝试均收到未知应答 | 40 元 | 0 元 | 0 元 | 20 元 | 均未知，第三单因额度不足被拒 |
| 工具封账，W 重启取回并核销同一回执 | 0 元 | 20 元 | 20 元 | 20 元 | 两笔仍未归属，业务意图继续禁重 |
| 第三单重新审批、接受、派发、结算 | 0 元 | 40 元 | 0 元 | 40 元 | 两笔仍未归属 |
| 原两单明细签回并各重复处理一次 | 0 元 | 40 元 | 0 元 | 40 元 | 一笔成功，一笔确认无效果 |

## 应用接线

1. 已经受理并消费执行资格、效果仍未知的付款，按同一付款方、币种、工具账及 W 资源池分组。用每笔原操作的当前 `SETTLE` worker 凭据调用 `w.request_pay_batch(operation_ids, proofs)`。W 从本账的冻结操作生成请求，先登记成员归属。此时余额保持预占，普通逐笔结算会提示 `BATCH_PENDING`。
2. 调用 `gateway.close_batch(request)`。支付工具在同一写事务里统计原尝试、锁定成员、阻止这些尝试再增加扣款，并生成签名回执。工具已提交却未收到回执时，重新取得同一成员集合的请求并重试。并发的普通支付与封账由工具账排序。
3. 用一组新的 worker 凭据调用 `w.settle_pay_batch(certificate, proofs)`。W 验证工具身份、账本、成员、原尝试及金额，在与新单接受共用的主账内一次性减少原预占、增加批次支出。成员继续保留各自唯一意图。第三单经过正常 `prepare / accept / claim / execute_once / settle`，在原 pay-sim 生成真实模拟支付记录。
4. 晚到明细依次走 `w.request_pay_batch_detail`、`gateway.batch_detail` 和 `w.settle_pay_batch_detail`。W 核对对应终账与原尝试，归属后关闭该单在途状态。批次总额已经入账，逐笔归属不再增加资源支出。重复提交同一终账或明细会返回已有结果。

调用顺序、参数和故障配置可直接从[可运行演示](../run_payment_batch.py)复制。支付工具在这里是本地具名模拟器。接银行时，只有能够认证完整批次范围、最终金额并阻止迟到追加扣款的接口，才满足同一封账语义。本轮验证范围为单机、同一资源池、逐笔全额或零扣款，手续费、部分扣款和后续冲正需约定独立的账务事件。

## 验证结果

以下命令对仓库这份[已导出的公开证据](../evidence/pay-batch-20261123/report.json)做离线复验。根公钥固定于该次演示。新运行会生成新密钥。

```powershell
python -B -m competition.verify_payment_batch competition/evidence/pay-batch-20261123/report.json --root-public u5ZI8VFQEgSMifWFOPOlMDBlzDFQ-bP1oVvV0FMOljc
python -B -m unittest -v competition.tests.test_payment_batch
```

离线程序从给定根公钥验证支付工具证书，验证批次总额、两个尝试的签名明细、第三单签名终局与检查点，并复算两笔实际支付共 4,000 分。报告的阶段余额是演示时直接读取的数据库快照，复跑专项测试会重新创建数据库并检查这些值。版本受控的证据随附测试公钥，用于本地复验；外部审计应独立取得信任根。[离线核验代码](../verify_payment_batch.py) · [批次专项测试](../tests/test_payment_batch.py)
