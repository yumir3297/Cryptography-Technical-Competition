# 实际命令与执行顺序（2026-10-17，Asia/Shanghai）

仓库工作目录：`/private/tmp/zjj-interface-feasibility-20261017`。
运行数据：每用例 `tempfile.TemporaryDirectory(prefix='zjj-probe-')`，结束后清理；不提交私钥或运行数据库。

## 网络及环境失败（保留，不计为协议失败）

- 沙箱内 `git ls-remote https://github.com/yumir3297/Cryptography-Technical-Competition.git refs/heads/competition/zjj-core-final-20261010` 及清除代理变量的尝试均报 `127.0.0.1:7890` 无法连接；经允许的联网执行克隆成功。
- `python3 -c 'import cryptography,jsonschema; ...'` 遭遇 `PYTHONHOME` 指向 3.12、实际系统解释器为 3.14，不能导入 encodings。
- `env -u PYTHONHOME python3 ...` / 捆绑 Python 缺 `jsonschema`。首次 discover 产生 79 项、36 failures、23 errors；见 `baseline.log`。缺模块导致多数测试未正常加载，不能称为完整回归。
- 由默认 Python 创建的首个临时 venv 在联网环境遭遇 3.12 framework 动态库缺失。改用明确的 Homebrew Python 3.14 路径；未改仓库依赖文件。

## 成功建立环境及基线

```sh
git clone --single-branch --branch competition/zjj-core-final-20261010 https://github.com/yumir3297/Cryptography-Technical-Competition.git /private/tmp/zjj-interface-feasibility-20261017
cd /private/tmp/zjj-interface-feasibility-20261017
git rev-parse HEAD
git log -1 --format=fuller
git switch -c experiment/trusted-action-feasibility-20261017
env -u PYTHONHOME /opt/homebrew/bin/python3.14 -m venv /private/tmp/zjj-interface-py314-20261017
env -u PYTHONHOME /private/tmp/zjj-interface-py314-20261017/bin/python -m pip install -r /private/tmp/zjj-interface-feasibility-20261017/requirements.txt
env -u PYTHONHOME /private/tmp/zjj-interface-py314-20261017/bin/python -m unittest discover -s competition/tests -v > /private/tmp/zjj-interface-feasibility-evidence-20261017/baseline-ready.log 2>&1
```

## 实验失败、诊断及复测

```sh
env -u PYTHONHOME /private/tmp/zjj-interface-py314-20261017/bin/python -m unittest experiments.interface_feasibility_20261017.test_probe.Probe.test_E1_sources_and_original_schema -v > /private/tmp/zjj-interface-feasibility-evidence-20261017/red.log 2>&1
env -u PYTHONHOME /private/tmp/zjj-interface-py314-20261017/bin/python -m unittest experiments.interface_feasibility_20261017.test_probe -v > /private/tmp/zjj-interface-feasibility-evidence-20261017/probe-first.log 2>&1
env -u PYTHONHOME /private/tmp/zjj-interface-py314-20261017/bin/python -m unittest experiments.interface_feasibility_20261017.test_probe.Probe.test_E3_frozen_full_request_replay_and_resign_conflict -v > /private/tmp/zjj-interface-feasibility-evidence-20261017/resign-diagnostic.log 2>&1
env -u PYTHONHOME /private/tmp/zjj-interface-py314-20261017/bin/python -m experiments.interface_feasibility_20261017.run_probe /private/tmp/zjj-interface-feasibility-evidence-20261017/probe-final
env -u PYTHONHOME /private/tmp/zjj-interface-py314-20261017/bin/python -m experiments.interface_feasibility_20261017.run_probe /private/tmp/zjj-interface-feasibility-evidence-20261017/probe-verified
```

- red.log：1 项失败，缺少待实现适配器，预期红灯。
- probe-first.log：15 项，1 error，重签实验误用基线 seed 的旧 Action 上下文，真实 broker 拒绝 `BROKER_ACTION_BINDING`。
- resign-diagnostic.log：单独复现该错误；修正为受信模拟端独立 operations map，未修改 broker 或核心。
- probe-final：增加至 19 项，均通过。随后加强首次 full_op 持久化崩溃用例（此前父进程已先冻结，覆盖不足），并在最终版保存公开证据。
- probe-verified：最终代码对应结果；其 tests.log/results.json 为最终实验依据。

## 基线与原文件不变性

```sh
git ls-remote --heads origin competition/zjj-core-final-20261010
git diff --exit-code cc4e36b4e302fcdc53cc809a012c77d8464182af -- competition system_dev requirements.txt
env -u PYTHONHOME /private/tmp/zjj-interface-py314-20261017/bin/python -m pip freeze > /private/tmp/zjj-interface-feasibility-evidence-20261017/requirements-lock.txt
env -u PYTHONHOME /opt/homebrew/bin/python3.14 /private/tmp/package_zjj_evidence.py
```

最后一个脚本逐一比较 `git ls-tree -r --name-only BASE` 中所有文件的磁盘字节与 `git show BASE:path`，结果见 integrity.json；交付前还会用 Git 再核对改动范围。

可复现时使用任意新 venv 安装 requirements-lock.txt，在该实验分支执行 run_probe，并为每次结果指定不存在的新目录；运行器拒绝覆盖旧结果。

## 收尾新增读取边界回归

```sh
env -u PYTHONHOME /private/tmp/zjj-interface-py314-20261017/bin/python -m unittest experiments.interface_feasibility_20261017.test_probe.Probe.test_E1_reader_revocation_precedes_evidence_access -v > /private/tmp/zjj-interface-feasibility-evidence-20261017/reader-red.log 2>&1
env -u PYTHONHOME /private/tmp/zjj-interface-py314-20261017/bin/python -m experiments.interface_feasibility_20261017.run_probe /private/tmp/zjj-interface-feasibility-evidence-20261017/probe-final-20
```

reader-red.log 复现撤销 READER 后仍先读取 EVIDENCE 再拒绝的问题。仅在实验适配器中提前校验读取角色及 ACL。**最终实验依据更新为 probe-final-20/tests.log 与 results.json**；保留之前的全部运行，不覆盖。


## 可信时钟拒绝与最终完整复核

```sh
env -u PYTHONHOME /private/tmp/zjj-interface-py314-20261017/bin/python -m unittest experiments.interface_feasibility_20261017.test_probe.Probe.test_E3_real_process_exit_after_full_op_persist_restores_exact_request -v > /private/tmp/zjj-interface-feasibility-evidence-20261017/freeze-diagnostic.log 2>&1
env -u PYTHONHOME /private/tmp/zjj-interface-py314-20261017/bin/python -m experiments.interface_feasibility_20261017.run_probe /private/tmp/zjj-interface-feasibility-evidence-20261017/probe-final-20-recheck
```

probe-final-20：20 项中 1 error，签名时钟 healthy=false → CLOCK_UNKNOWN，发生在分配 ID 前。同一用例独立重跑通过；完整重跑 20 项通过，最终依据为 **probe-final-20-recheck**。该瞬时故障根因尚未证实；不放宽原时钟阈值，不在测试中增加吞错重试。


## 独立审查修正与最终 22 项结果

```sh
env -u PYTHONHOME /private/tmp/zjj-interface-py314-20261017/bin/python -m unittest experiments.interface_feasibility_20261017.test_probe.Probe.test_E1_cached_retry_rechecks_current_policy_read_acl experiments.interface_feasibility_20261017.test_probe.Probe.test_E1_cached_retry_rechecks_reader_action_constraints -v > /private/tmp/zjj-interface-feasibility-evidence-20261017/cached-acl-red.log 2>&1
env -u PYTHONHOME /private/tmp/zjj-interface-py314-20261017/bin/python -m experiments.interface_feasibility_20261017.run_probe /private/tmp/zjj-interface-feasibility-evidence-20261017/probe-final-22
git diff --cached --check -- '*.py' '*.md' '*.json' '*.txt'
git diff --exit-code cc4e36b4e302fcdc53cc809a012c77d8464182af -- competition system_dev requirements.txt
```

缓存 ACL 和动作范围回归先得到 2 failures；适配器对缓存 Action 重新调用原 read_permission 后，**最终 22 项完整通过**，最终证据更新为 probe-final-22。保留其前所有运行。
原始 baseline.log 含 unittest 输出的行尾空格，普通 diff --check 会报告该行；为保留原始日志字节，格式检查仅对源代码、文档、JSON 和依赖锁定文本运行。

交付提交只添加 experiments/interface_feasibility_20261017，发布命令为：
```sh
git add experiments/interface_feasibility_20261017
git commit -m "experiment: validate trusted IND proposal adapter without core changes"
git push -u origin HEAD:refs/heads/experiment/trusted-action-feasibility-20261017
```
