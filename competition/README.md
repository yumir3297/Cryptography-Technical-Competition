# 比赛软件开发入口

先读[协议交接](FINAL_PROTOCOL_HANDOFF.md)，接线时使用[真实内部接口对照](docs/final/interface-reference.md)。CommonW 是工业、付款、医疗共用的接受、领取、执行、恢复与结算入口。

| 目录 | 用途 |
|---|---|
| core/ | 当前身份、来源、批准、时间、持久接受、回执和共同 W |
| profiles/ | 固定三场景的绑定、安全规则及受控初始化 |
| tools/ | 三个签名模拟工具与独立效果账 |
| support/ | 运行和测试实际依赖的编码、场景校验及恢复基础模块 |
| tests/ | 比赛组件、并发、故障恢复与终局回归 |
| docs/final/ | 比赛协议、接口、场景交接及证据口径 |
| evidence/ | 不含运行私钥的比赛模拟与核验记录 |

从仓库根目录运行：

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s competition/tests -v
python -m competition.run_w_slice --output .runtime/demo-evidence
python -m competition.verify_w_slice .runtime/demo-evidence --manifest-sha256 <manifest摘要> --report .runtime/demo-verification.json
```

输出目录必须是新的路径。运行初始化会生成临时测试角色钥和本地 SQLite 账，保存在被 Git 忽略的 `.runtime/`；公开证据导出器只导出公钥、签名和账投影。演示先经受控初始化与批准构造，再接 CommonW，不能把 fixture 当成外部认证入口。

```powershell
python competition/docs/final/verify-existing-evidence.py
python -m competition.verify_repository --report .runtime/repository-check.json
python system_dev/v26/tools/verify_contracts.py
```

第一条按证据记录的 Git 提交核对既有 W 22 例和同 ID 3 例，不声称这些旧运行来自整理后的源码。第二条检查当前入口、依赖和材料引用；第三条只检查 Schema、编码和密码向量。三个场景的实际正常、拒绝和恢复路径见各自交接。
