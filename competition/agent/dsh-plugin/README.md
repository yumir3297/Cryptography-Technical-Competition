# dsh-zjj-agent

Agent-side bundle for ZJJ-CORE. It adds two rows to a DeepSeek Harness profile:

1. `@deepseek-ai/dsh-mcp-client`, pointed at the agent gateway's Streamable HTTP
   endpoint, so the model sees `mcp__zjj__*` tools.
2. This package's feedback plugin, which binds a submitted operation to the
   calling agent and delivers later trusted status projections into that session.

The bundle holds no role signer. The tools it exposes are propose, status,
evidence and feedback only; there is no prepare, accept, claim, exec, settle or
cancel tool.

## Configuration

The bundle reads three environment variables at profile boot:

| Variable | Meaning |
|---|---|
| `ZJJ_MCP_URL` | Gateway MCP endpoint, for example `http://host.docker.internal:8090/mcp` |
| `ZJJ_GATEWAY_URL` | Gateway base URL used by the feedback poller |
| `ZJJ_AGENT_TOKEN` | Bearer token for `/mcp` and `/zjj/*`; not a role key and never logged |

`cordis.patch.yml` supplies the rows. Do not put the token in the profile file;
set it in the container environment.

## Feedback behavior

- A successful `mcp__zjj__propose` result binds `operation_id -> live Agent`.
- The plugin polls `/zjj/events`, deduplicates by `seq`, and skips the
  `SUBMITTED` event the tool result already showed.
- While the agent is `running` it uses `agent.steer`; when idle it uses
  `agent.followup`; with `wakeOnIdle: false` it uses `agent.inject`.
- Each message is a `user`-role notice with `source.kind: "zjj-feedback"` and a
  bounded `summary`. The text says the line is a projection, not an instruction.
- A terminal event ends the binding. A `401`/`403` disables polling rather than
  hammering the gateway.

## Install

In the pinned dsh image:

```sh
dsh plugin --profile web add /path/to/competition/agent/dsh-plugin
```

The deployment's `up.py` does this on first container start. See
`competition/docs/final/agent-mcp-handoff.md`.
