# 独立只读复核原始结论

复核范围：本地edc24之后的公共授权、固定roster/PoP/broker、三个推导适配器、IND接受桥、测试与导出。审核者a_final_review（独立上下文）实际用受控新库/真签名复现，未改源码/提交，未启动子代理。

3 Important，0 Critical，0 Minor：

1. authorization_scene.py复用原verify_evidence时E资格核action=None，漏SOURCE业务范围。MED当前E grant patient_set换为不同患者，epoch2、重新derive deps/Basis/Ctx及重签/注册覆盖，guard仍T。PAY已有动作范围，IND原_windows额外挡住；公共IND/MED guard/read缺此约束。
2. signer_broker.py核独立action后直接签unsigned，未比对Ctx/action_hash/op。PAY U待签ctx.action_hash指向金额99999999，但传入允许2000的action，返回可验签名。公共W会阻断该链，属于签名过滤范围失效。
3. 原_bound无条件G/X/U/V全互异，工业DEMO_NORMAL→RELEASE无需V时U/V同主体也被拒绝，违反冻结的适用才分离规则。

公共DENY同W序、认证空集、当前重算与ACL先于候选的主体结构符合目标。

Declined to judge：MED/PAY完整业务提交、资源/dispatch/settle、Linux DAC、动态治理/HSM、独立历史全覆盖、任意图闭包。它们属于明确后置范围，不能将授权T升格完整ACCEPTED。

执行者修复记录：三项分别新增真实行为用例RED（2失败/1错误），竞赛层修复后3/3 GREEN，随后完整79/79竞赛回归通过。原研究文件保持原bytes；未重复派复核。对应test_source_current_business_scope_cannot_be_hidden_by_rebased_valid_chain、test_broker_checked_action_must_bind_signed_payload_context、test_ind_without_review_does_not_require_independent_v_subject。
