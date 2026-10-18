# 工业场景本机部署（竞赛模拟器）

本入口是统一比赛交付的**工业全流程主展示**；工业、付款、医疗本地 CLI 是独立的补充演示。统一范围及开发问题对应关系见[统一交付说明](../docs/final/unified-competition-delivery-20261018.md)。

范围：IND-DEMO-1、真实回环 HTTP、可选 MCP stdio、SQLite 工业工具模拟效果。沿用统一生命周期方案；不接实体设备，不宣称独立 OS 角色/KMS 密钥托管。

## 1. 环境与一次性配置

使用能运行本仓库的 Python 环境。本轮核验版本为 Python 3.14.7、cryptography 50.0.2、jsonschema 4.26.0。清除错误的 PYTHONHOME；所有子进程继承同一解释器。

从仓库根执行，ZJJ_PYTHON 替换为已安装依赖的解释器绝对路径：

```sh
export ZJJ_PYTHON=/path/to/venv/bin/python
env -u PYTHONHOME "$ZJJ_PYTHON" -m competition.deployment.provision_demo /absolute/new-installation --port 18765
sh competition/run_industrial_local.sh /absolute/new-installation/service.json --check
sh competition/run_industrial_local.sh /absolute/new-installation/service.json
```

provision_demo 是明确的本地模拟数据/密钥引导程序，只有目标目录不存在时才初始化。不要用它恢复旧操作。已有安装只运行 local_runtime；启动器不会清库、覆盖操作或重新生成授权。

目录为 0700，配置、token、密钥和数据库为 0600。service.json 记录固定 IND Task、公开 roster、根公钥、worker 公开证书、派发公钥及本机端口。默认监听 127.0.0.1:18765。启动后 service-ready.json 提供实际 URL、服务 PID、C 与 X 子进程 PID；它不包含 token。

## 2. 边界与启动检查

- 公开业务服务只加载公开身份和 W 派发私钥；C 时钟、X 冻结回执签署和工具仍使用原受限子进程。服务不会加载 H/U/V/G/E 或 worker 私钥。
- 受控演示操作端 acceptance.py 会加载模拟参与方密钥并显式生成真实批准；它不是生产审批服务，不注册成 Agent 工具。lab-metadata.json 仅供该受控操作端使用。
- 同 OS 用户仍可读所属私有目录，不能把进程/API 分离表述成恶意本机用户隔离；初始引导者拥有模拟身份。
- 在监听前检查私有目录/文件权限、数据库存在及完整性、必要 W/应用/来源/工具账表和单例行、W_BOOTSTRAP、根签名 worker 证书、工具登记/账本 origin、配置路径和 W 派发绑定；C 公钥与根、X 子进程公钥与登记身份分别核对。应用表在一次性引导阶段建立，启动不接受缺表并静默建回空账。
- 拒绝远程监听、额外配置字段、工具故障注入字段、缺失账、错误身份绑定和重复运行同一安装的服务。工具预检子进程只读取自身密钥并报告核对后的公开绑定，不执行动作、不提供签名接口；实际签署由真实执行/回执验收再次验证。
- --check 会短暂启动原 C/X 客户端及工具预检并核对绑定，随后关闭，不监听 HTTP；应在同一安装的服务停止时执行。它不是数据库修复或授权续期命令，也不替代每次业务调用的当前资格、来源与窗口守卫。
- HTTP 继续采用既有十项白名单和 H 密码学认证；token 只证明传输访问。worker、任意签名、登记发布、回执补签不新增公开接口。

本机时钟不可确定仍返回 CLOCK_UNKNOWN。macOS 启动包装器只在服务运行期间防空闲休眠；不修改时间阈值，也不能阻止合盖或人工休眠。

## 3. 验收与恢复

对全新且尚未接受操作的自有模拟安装执行：

```sh
env -u PYTHONHOME "$ZJJ_PYTHON" -m competition.deployment.acceptance --config /absolute/new-installation/service.json --evidence /absolute/new-public-evidence
```

执行端主动启停实际服务并在完成后关闭服务，保留私有运行账。证据目录必须不存在；不覆盖旧结果。它验证请求映射、坏认证、接口拒绝、短期更新/旧 ticket、待接受恢复、丢弃接受响应后重启、内部 worker 一次效果/结算、终态恢复和真实 MCP 桥接。

正常恢复：用同一个 service.json、原私有目录和原数据库重新启动，认证调用 recover/status。响应超时先读原 W；更新短期证明不更新原 Permit。已消费 EXEC 或无法确认时不得重新执行，查询原 attempt。不得重新运行 provision_demo 清除原状态。

初始 KEY/ROLE、worker 和工具信任窗口约 30 分钟，当前引导的 E 来源证明为 120 秒，Task 等仍遵循各自原窗口；每个新 Assessment 最多 90 秒，短期证明最多 30 秒。新模拟完整演示应把 provision 和 acceptance 连续执行，避免手工等待耗尽来源窗口。启动和重启不会续期。超过原窗口的授权/来源必须失败关闭，正式受控更新登记/重新审批不由本启动器自动完成。已通过验收的安装主要用于恢复已有记录；再次完整验收使用明确独立的新模拟安装，不冒充旧业务的重试。

## 4. 保留与交接

公开证据：results.json、public-evidence.json、host 日志、执行日志及源码摘要。私钥、token、运行 SQLite 和 lab-metadata.json 不加入公开证据或 Git。

部署专用代码为 application/local_runtime.py（启动/检查）与本目录的 provision_demo.py / acceptance.py。原核心、Action Schema、签名域、时间守卫和工具执行规则不变。验证计划见[部署验收计划](../docs/plans/2026-10-18-ind-local-deployment.md)。

本次GitHub交付只提供脱敏结果与日志，不包含本机完整签名/身份/账本包。上述命令在新安装生成自己的完整实验材料；核验步骤与公开范围见[四项交付说明](../docs/final/ind-complete-delivery-20261018.md)。
