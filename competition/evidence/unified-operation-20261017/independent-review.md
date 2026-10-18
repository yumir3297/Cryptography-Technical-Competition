# 独立只读审查记录

审查者为本轮独立 review 子代理，未继承主代理历史，读取指定基线、设计和当前实现；未编辑代码、未运行全套，未接触其他 Work 任务。

初审无 Critical；两个 Important：
1. submit_authenticated 在开始时检查 H 身份 nonce，保存结束缺少其到期与当前读取资格的最终检查。已用原 H 真签名、测试端缩短服务器 nonce 期限及小于原 2 秒阈值的真实延迟复现：两个新反例均曾错误成功保存。
2. 畸形传输入口没有统一错误边界：非 ASCII Authorization 触发 hmac TypeError；5000 位整数触发 json.loads ValueError 并终止 MCP。另由主代理反例发现非字符串工具名会触发 TypeError。

修正包括最终 nonce/资格/原窗口检查并依原事务回滚、ASCII 认证头检查、JSON ValueError 规范化、保留原 ProtocolError，以及工具名类型检查。修正中 ValueError 捕获误吞 DUPLICATE_KEY 的回归也被现有测试发现并保留失败记录；已修正。

复审结论：该修正范围内无剩余 Critical/Important；审查者独立运行 5 项定向测试，9.030 秒全部通过。CAS、历史防回退、接受/换包串行、冻结 Core 及原 attempt 恢复未发现具体绕过。未将定向检查等同于完整系统安全证明。

可选覆盖建议：同版旧短期证明过期后的公开幂等确认，不增加 APP_SUBMISSION。主代理已将该用例加入最终联合套件。

原自然 CLOCK_UNKNOWN 仍未定位；审查者没有宣称修复时钟。最终全套结果另存，不能与独立定向测试相加。
