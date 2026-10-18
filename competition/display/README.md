# 观察面展示页（Vue）

[只读观察面](../docs/final/interface-reference.md#7-只读观察面展示接口)的展示页：订阅受信端发布的每一步，
用**流程演示图**标出当前走到哪一步（发光节点 + 指针），侧栏放**链条**（事件链）、已提交操作与操作快照。

页面**只读**：只发 `GET`，不驱动任何步骤。它不持有 observer 私钥——凭据在观察网关
（[`competition/deploy/viewer.py`](../deploy/viewer.py)）里，浏览器只与网关同源通信。

## 开发

先起一套部署与网关（见[总说明](../../README.md)）：

```bash
python -m competition.deploy.up --local     # 或 --no-deepseek 只起竞赛这套
```

再起开发服务器（默认把 `/api` 代理到 `http://127.0.0.1:8008` 的网关）：

```bash
cd competition/display
npm install
ZJJ_VIEWER=http://127.0.0.1:8008 npm run dev
```

## 构建与测试

```bash
npm run build     # 产物在 competition/display/dist，网关会托管它
npm test          # 折叠逻辑的单元测试（不连网）
```

## 配置

| 变量 | 作用 |
|---|---|
| `ZJJ_VIEWER` | 仅开发：开发服务器把 `/api` 代理到哪个网关 |
| `VITE_VIEWER_KEY` | 仅当网关设置了共享口令（`ZJJ_VIEWER_SECRET`）时填，随每次读取携带 |

## 口径

页面显示的每一个字段都是**展示投影**：受信端在响应里明示
`view_kind=OBSERVATION_PROJECTION`、`signed=false`、`not_evidence=true`。页面照实呈现这三点，
不把观察事件当作协议自身的签名状态或证据。
