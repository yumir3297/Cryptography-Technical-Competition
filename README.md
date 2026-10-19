# ZJJ-CORE 安全协议与比赛模拟软件

##作者吐槽：其实作者本人觉得这个东西出产的逻辑就存在一点问题。从实际科研与解决的问题的角度出发，进行一个协议的或者系统的设计应该以实际问题的现象入手，进而剖析问题背后的逻辑，然后针对该问题逻辑进行优化。但是该作品的初衷是针对工业生产情况进行一些问题的解决，但是因为不可抗力的要求下，被要求抽象成一套宽泛的安全协议，其中包括签名内容，参与签名者，参与签名者之间的关系等因素其实逻辑上并不满足抽象成一个宽泛协议的条件，这点在另外两个展示场景的开发过程中就生动形象的体现出来，很多非对称密码学实现的过程中的数学逻辑分配的别扭的不行。

**统一交付入口：[工业全流程主展示与三场景本地补充演示](competition/docs/final/unified-competition-delivery-20261018.md)。** 本提交收束 PR #5、#6、#7，开发方只需审阅和集成这一份完整修改。

工业提供受信单机中的候选、审批签署、接受、模拟执行、结算和重启恢复全流程；工业、付款、医疗三个场景的可信本地 CLI 作为补充演示。两种入口共用核心、保持隔离，PAY/MED 不声明已提供工业新版公开服务。

工业实现细节：[如何解决、其他影响、补全方案、实验代码与结果](competition/docs/final/ind-complete-delivery-20261018.md)。

本仓库用于密码学技术竞赛的软件开发与演示。agent 提出动作，独立的受信验证、必要批准和执行约束决定动作能否产生模拟效果。工业、付款、医疗共用接受与执行核心。

- [共同安全协议](competition/docs/final/competition-protocol.md)
- [比赛配置与三个场景开发总交接](competition/docs/final/scenario-integration-handoff.md)
- [完整交付入口](competition/FINAL_PROTOCOL_HANDOFF.md)
- [开发入口与运行命令](competition/README.md)
- [当前内部接口与返回值](competition/docs/final/interface-reference.md)
- [协议 1.1 优化与复检](competition/docs/final/optimization-review-20261012.md)
- [声明与实际证据](competition/docs/final/claims-evidence.md)
- [竞品与作品指标台账](competition/docs/metrics/竞品与作品指标台账.md)：公开能力、厂商数字、作品证据与待同测指标
- [安装依赖与运行范围](INSTALL_AND_SCOPE.md)
- [消息契约、Schema 与公开编码向量](system_dev/v26/README.md)
- [仓库范围与整理记录](REPOSITORY_SCOPE.md)

比赛采用受信单机、固定登记范围和三个签名模拟工具。当前查询与审计是经过认证的本地应用投影；正式 R2 签名响应与应用实现差异在交接材料中分别说明。

仓库当前内容提供比赛代码、协议说明、场景交接、开发契约、回归测试及模拟证据。论文正文、研究模型、研究实验结果与研究分支快照已完整归档本地。既有运行证据保持原构建身份，当前运行命令见开发入口。

当前比赛语义、agent 能力与角色签署边界见[安全边界](competition/docs/final/security-boundaries.md)；修复和验证结果见[整改记录](competition/docs/final/rectification-results-20261012.md)。

协议共同规则与具体比赛开发内容已分层，见[CORE-SPEC-1.3 整理记录](competition/docs/final/protocol-separation-record-20261012.md)；既有执行代码和 wire 标识保持。
