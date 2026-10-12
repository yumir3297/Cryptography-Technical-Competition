# 共同核心与场景适配器

工业、付款、医疗共用 [CommonW](../core/common_w.py) 的接受、回执、领取、模拟派发、查询与结算。安全批准统一由 [AuthorizationService](../core/authorization.py) 核验，场景特有规则位于 `profiles/`，效果账位于 [CommonTool](../tools/common_tool.py)。

`support/` 是实际运行依赖的基础实现，保留场景 authority、编码、Schema 和恢复基类；来源说明见 [support](../support/README.md)。`core/acceptance.py` 与工业初始化供时间接受组件和回归使用；三个正式展示路径使用共同 W。

身份和动作范围在固定登记里匹配，场景适配器不能把共同核心的拒绝转成允许。接线从[接口对照](final/interface-reference.md)开始，业务输入与场景安全规则按三份[开发交接](../FINAL_PROTOCOL_HANDOFF.md)实施。
