# Agent MCP 接入与状态回推交接

本文说明 agent 侧如何通过 MCP 提出候选、读取状态，以及受信状态如何被推回正在运行的 dsh 会话。对应代码在 `competition/agent/`，部署在 `competition/deploy/`。

## 1. 边界

agent 只有两个动作：

| 动作 | 工具 | 说明 |
|---|---|---|
| 提出 | `zjj_propose` | 提交一条业务候选；成功只表示 `SUBMITTED`，不表示接受 |
| 查询 | `zjj_status` | 读取该操作当前的状态投影和引用级证据 |

agent 不能 prepare、accept、claim、exec、settle、cancel 或签署。H 侧的 `operator` 和 worker 侧的 `executor` 是独立进程、独立角色钥、独立卷，通过 gateway 的内部队列衔接；gateway 自己只持有 H 侧 caller key，并用应用层 step 白名单把可调用步骤限制为 `status`（`competition/agent/policy.py` 的 `ALLOWED_STEPS`）。

## 2. MCP 面

入口：`POST /mcp`，Streamable HTTP，`Authorization: Bearer <ZJJ_AGENT_TOKEN>`。

### `zjj_propose(profile, intent)`

`profile` 固定为 `IND-DEMO-1`、`PAY-1`、`MED-DEMO-1` 之一；`intent` 必须恰好包含该 profile 的字段，全部为字符串：

| profile | 字段 |
|---|---|
| `IND-DEMO-1` | `line_id`, `station_id`, `unit_id`, `batch_id`, `inspection_cycle`, `phase`, `route` |
| `PAY-1` | `order_id`, `stage`, `payer`, `payee`, `amount_minor` |
| `MED-DEMO-1` | `synthetic_patient_id`, `encounter_id`, `template_id` |

返回 `operation_id`、`profile`、`state=SUBMITTED`、`deduplicated` 和一句说明。相同 intent 重复提交会返回同一个 `operation_id`，不会生成第二个操作。字段之外的角色、密钥、批准、permit、scope、tool、`operation_id` 或测试开关一律拒绝。

### `zjj_status(operation_id)`

返回标量状态和引用：

- 状态：`state`、`acceptance_state`、`dispatch_state`、`effect_state`、`receipt_state`
- 执行：`attempt_id`、`exec_consumed`、`queries`、`view_kind`
- 证据引用：`commit_record_ref`
- 读侧信息：`read_at`、`read_error`、`reason`
- 固定说明：`note`（只有引用和标量，不返回 acceptance body、COMMIT 值或业务载荷）

没有单独的 `zjj_profiles`、`zjj_list_operations`、`zjj_evidence` 或 `zjj_feedback` 工具：profile 目录写在 `zjj_propose` 的说明里，证据并进 `zjj_status`，反馈是推送通道而不是工具。

## 3. 状态回推

### 3.1 服务端事件

gateway 的后台 poller 按 `ZJJ_STATUS_POLL_MS`（默认 1000 ms）刷新所有非终态操作。`zjj_status` 的每次读取都会经过同一套 `refresh`/`_observe` 路径：状态变化写入 journal，并追加一条递增 `seq` 的事件。

agent token 可读：

```
GET /zjj/events?operation_id=<id>&since=<seq>&limit=50
Authorization: Bearer <ZJJ_AGENT_TOKEN>
```

返回 `{"events": [...], "next_seq": n}`。事件只含 `seq`、`operation_id`、`kind`、`state`、`summary`、`created_at` 和脱敏后的 `detail`，不含完整 audit。`/zjj/events` 是 agent token 的唯一读接口；`/internal/*` 只接受 internal token，operator/executor 用它领取和释放队列。

### 3.2 dsh 插件

`competition/agent/dsh-plugin/` 是零依赖的 Cordis 插件，做三件事：

1. 监听 `tools/result`，只在 `mcp__zjj__propose` 成功时把返回的 `operation_id` 绑定到发起调用的 live `Agent`。
2. 每 `pollIntervalMs`（默认 1500 ms）拉一次 `/zjj/events`，按 `seq` 去重，游标持久化在 `$DSH_HOME/zjj-feedback-state.json`。首次绑定跳过 `SUBMITTED`，因为 propose 的工具结果已经告诉 agent。
3. 把新事件拼成一条 `user` 角色的 notice（`source.kind = "zjj-feedback"`、`form = "notice"`），按 agent 状态投递：

| agent 状态 | 调用 | 行为 |
|---|---|---|
| `running` | `agent.steer(message)` | 在当前回合插入，模型下一步就能看到 |
| 空闲且 `wakeOnIdle` | `agent.followup(message)` | 排队并在空闲时唤醒新回合 |
| 空闲且不唤醒 | `agent.inject(message)` | 只进上下文，不触发新回合 |

终止事件（`SETTLED`、`HALTED`、`CANCELED`、`UNAVAILABLE`）后停止该绑定的轮询。`401/403` 直接停轮询，不反复撞网关；网络错误按 30 秒限频告警。

### 3.3 兜底

推送不是唯一事实来源。插件没装、进程重启、通知漏投时，agent 下一轮调用 `zjj_status` 重新读同一份状态。`UNKNOWN` 只表示当前没有受信最终事实，不表示失败；不要重试执行，必要时让 operator 查询原 attempt。

### 3.4 为什么是轮询

模型侧最终仍要靠 `steer`/`followup` 把文本注入会话，SSE 只省一次 HTTP 轮询，却多一套断线重连和游标恢复。当前实现用短轮询 + 持久游标，插件重启不重放，失败也不会把通知变成重复回合。

## 4. 凭据与脱敏

| 凭据 | 可访问 | 不可访问 |
|---|---|---|
| `ZJJ_AGENT_TOKEN` | `/mcp`、`/zjj/events` | `/internal/*`、角色签名 |
| `ZJJ_INTERNAL_TOKEN` | `/internal/queue/*`、`/internal/operations/*/hint` | `/mcp`、`/zjj/events` |
| gateway caller key | 只留在 gateway 进程/卷 | 不进入 dsh、不进入 operator/executor |

gateway 不把 caller key、完整 audit、acceptance body、COMMIT 值或业务载荷返回给 agent。`zjj_status` 的字段是白名单投影，`read_error` 只给错误码级信息。

## 5. 部署

默认 agent 模式：

```sh
python -m competition.deploy.up
```

它会构建/启动 `endpoints`、`trusted`、`caddy`、`agent-gateway`、`agent-operator`、`agent-executor`、`demo-agent`，然后启动固定镜像的 DeepSeek Harness。常用开关：

```sh
python -m competition.deploy.up --no-zjj        # 只跑原核心演示
python -m competition.deploy.up --local         # 不用 docker，在本机跑同一套入口
python -m competition.deploy.up --fresh         # 丢掉演示卷重新初始化
python -m competition.deploy.up --sudo          # docker daemon 需要提权
python -m competition.deploy.up --down          # 跑完收摊
```

两个 token 由 `up.py` 生成/复用，落在 `.runtime/agent-tokens.json` 和 `.runtime/agent-tokens.env`（0600，已被 Git 忽略）。compose 通过 `--env-file` 读取它们：`sudo` 会重置环境，不能依赖父进程继承。

端口：gateway `127.0.0.1:8090`，caddy `8080`，dsh `3080`。dsh 容器通过 `host.docker.internal:8090` 访问 gateway，只加入自己的网络，不加入 compose 网络。

dsh 不重建镜像。`competition/deploy/harness-entrypoint.sh` 把只读挂载的插件复制到 `/root/.dsh/plugins/dsh-zjj-agent`，再用 `dsh plugin --profile web add` 安装进持久 profile；版本标记在 `/root/.dsh/.zjj-plugin-version`，重复启动不会重复安装。没有 `ZJJ_MCP_URL`/`ZJJ_AGENT_TOKEN` 时原 entrypoint 原样执行。

## 6. 验证

针对性检查（不依赖本机已占用的 9100–9118 端口组）：

```sh
python -m unittest \
  competition.tests.test_agent_policy \
  competition.tests.test_agent_journal \
  competition.tests.test_agent_identity \
  competition.tests.test_agent_gateway \
  competition.tests.test_agent_workbench \
  competition.tests.test_deploy
node --test competition/agent/dsh-plugin/test/*.test.js
python -m competition.verify_repository --report .runtime/repository-check.json
```

容器内端到端（需要 docker 权限）：

```sh
python -m competition.deploy.up --fresh
```

`demo-agent` 应打印 `SETTLED effect=SUCCEEDED` 并以 0 退出；`agent-operator` 日志应出现 `accepted ...`，`agent-executor` 日志应出现 `settled ...`。如果 dsh 容器已经在跑，`up.py` 会跳过重建；要验证容器内插件安装，先 `docker rm -f deepseek-harness` 再跑。

## 7. 已知边界

- 受信端每次启动要求全新的 run 目录；trusted 容器重启会明确报错退出，不会悄悄重开旧 W。重跑演示用 `--fresh` 丢卷。
- operator 默认自动 accept，是演示替身；真实审批 UI 属后续。
- executor 对未知 exec 结果只查询原 attempt 再 settle，不盲重试。
- 受信端重启后，gateway 只能把旧操作标为 `UNAVAILABLE`，不恢复 op id，也不自动重提。
- dsh 插件只投递投影，不把通知当批准；agent 仍以 `zjj_status` 的受信读为准。
