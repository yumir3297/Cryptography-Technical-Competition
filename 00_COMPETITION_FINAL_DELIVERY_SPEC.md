# 比赛软件开发交付范围（2026 年 10 月历史记录）

当前协议材料以[比赛交接入口](competition/FINAL_PROTOCOL_HANDOFF.md)为准；真实调用以[接口对照](competition/docs/final/interface-reference.md)为准。

软件开发复用共同 W 和三个固定场景适配器，保持动作绑定、当前身份与来源、必要批准及否决、持久接受后冻结回执、唯一 attempt、一次执行资格、未知保守恢复与一次结算。各场景正常及代表性拒绝路径分别见[工业](competition/docs/final/industrial-handoff.md)、[付款](competition/docs/final/payment-handoff.md)、[医疗](competition/docs/final/medical-handoff.md)。

接入时应满足：

1. 外部入口认证会话并验证输入，调用方不能自报角色、公钥或注入测试故障开关。
2. 候选模块只有动作建议权；受信批准、签署、W 守卫和模拟工具访问由独立受控入口提供。
3. 展示使用认证 W 状态，区分接受、回执、领取与效果；不能仅凭工具成功标签确认已结算。
4. 应答丢失查询原操作，派发未知查询原 attempt；刷新页面只读取，不隐式执行或结算。
5. 导出公钥、签名、具名运行和核验报告，不导出私钥或运行账库。

适用前提与实际验证等级见[声明证据清单](competition/docs/final/claims-evidence.md)。主分支提供受信 HTTP 服务、会话认证、客户端控制台和只读观察页面，启动方式见[安装依赖与运行范围](INSTALL_AND_SCOPE.md)。完整研究模型与论文验证材料在本地归档中管理。
