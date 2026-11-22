# 安装依赖与比赛运行范围

环境：Python 3.13；依赖见 [requirements.txt](requirements.txt)。Node.js 用于可选的公开编码向量交叉核对，Python 运行与回归不依赖 Node。

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s competition/tests -v
```

从仓库根目录运行，进程须有权限创建本地临时文件和子进程。Windows 沙箱如限制系统临时目录，可将 TMP/TEMP 设为工作区 `.runtime/` 内的新目录。运行命令与导出步骤见[开发入口](competition/README.md)。

比赛代码执行签名模拟动作：工业分流、模拟付款、合成医疗登记。W 与模拟工具分别保存持久账；EXEC 已消费或消费情况无法确认时，只按可用权限查询原 attempt；领取后已确认未消费的首次 EXEC 仍须通过守卫，恢复不新增执行权。固定角色、公钥登记和 C 时间来自受信初始化。当前同用户子进程分离不建立操作系统权限隔离，泛化部署条件见[开发注释](competition/docs/final/developer-scope-notes.md)。

当前内部 Python 方法不直接构成 HTTP 服务；会话认证、外部输入解码、界面与安装包由后续软件开发接入。接入须保持[接口对照](competition/docs/final/interface-reference.md)中的认证主体、状态维度和幂等规则。

比赛消息采用 ZJJ-CORE-COMP-1，被 protected 签名覆盖；已有运行不能自动转换协议标识。agent 的 Action 字节入口及角色签署认证见[安全边界](competition/docs/final/security-boundaries.md)。
