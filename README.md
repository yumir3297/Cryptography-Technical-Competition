# ZJJ-CORE 安全协议与比赛模拟软件

IND 统一优化交付：[如何解决、其他影响、补全方案、实验代码与结果](competition/docs/final/ind-complete-delivery-20261018.md)。

本仓库用于密码学技术竞赛的软件开发与演示。agent 提出动作，独立的受信验证、必要批准和执行约束决定动作能否产生模拟效果。工业、付款、医疗共用接受与执行核心。

- [共同安全协议](competition/docs/final/competition-protocol.md)
- [比赛配置与三个场景开发总交接](competition/docs/final/scenario-integration-handoff.md)
- [完整交付入口](competition/FINAL_PROTOCOL_HANDOFF.md)
- [开发入口与运行命令](competition/README.md)
- [当前内部接口与返回值](competition/docs/final/interface-reference.md)
- [协议 1.1 优化与复检](competition/docs/final/optimization-review-20261012.md)
- [安装依赖与运行范围](INSTALL_AND_SCOPE.md)
- [消息契约、Schema 与公开编码向量](system_dev/v26/README.md)
- [声明与实际证据](competition/docs/final/claims-evidence.md)
- [仓库范围与整理记录](REPOSITORY_SCOPE.md)

比赛采用受信单机、固定登记范围和三个签名模拟工具。当前查询与审计是经过认证的本地应用投影；正式 R2 签名响应与应用实现差异在交接材料中分别说明。

仓库当前内容提供比赛代码、协议说明、场景交接、开发契约、回归测试及模拟证据。论文正文、研究模型、研究实验结果与研究分支快照已完整归档本地。既有运行证据保持原构建身份，当前运行命令见开发入口。

当前比赛语义、agent 能力与角色签署边界见[安全边界](competition/docs/final/security-boundaries.md)；修复和验证结果见[整改记录](competition/docs/final/rectification-results-20261012.md)。

协议共同规则与具体比赛开发内容已分层，见[CORE-SPEC-1.3 整理记录](competition/docs/final/protocol-separation-record-20261012.md)；既有执行代码和 wire 标识保持。
