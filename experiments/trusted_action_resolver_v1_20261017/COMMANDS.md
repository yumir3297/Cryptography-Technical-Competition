# 实际复现命令与版本

工作目录 `/private/tmp/zjj-interface-feasibility-20261017`，独立 Python `/private/tmp/zjj-interface-py314-20261017/bin/python`。
依赖与原实验相同：cryptography 50.0.2、jsonschema 4.26.0；完整锁定文件保留于上轮 evidence/requirements-lock.txt。

```sh
git fetch origin refs/heads/experiment/trusted-action-feasibility-20261017:refs/remotes/origin/experiment/trusted-action-feasibility-20261017 refs/heads/competition/zjj-core-final-20261010:refs/remotes/origin/competition/zjj-core-final-20261010
git switch -c experiment/trusted-action-resolver-v1-20261017 origin/experiment/trusted-action-feasibility-20261017
git rev-parse HEAD origin/competition/zjj-core-final-20261010
mkdir -p /private/tmp/zjj-resolver-v1-evidence-20261017
env -u PYTHONHOME /private/tmp/zjj-interface-py314-20261017/bin/python -m unittest discover -s competition/tests -v > /private/tmp/zjj-resolver-v1-evidence-20261017/core-regression.log 2>&1
env -u PYTHONHOME /private/tmp/zjj-interface-py314-20261017/bin/python -m experiments.trusted_action_resolver_v1_20261017.run_validation /private/tmp/zjj-resolver-v1-evidence-20261017/run-01
env -u PYTHONHOME /private/tmp/zjj-interface-py314-20261017/bin/python -m unittest experiments.trusted_action_resolver_v1_20261017.test_resolver.ResolverCases.test_signed_task_cannot_override_policy_destination experiments.trusted_action_resolver_v1_20261017.test_resolver.ResolverCases.test_unapproved_frozen_op_still_cannot_execute -v > /private/tmp/zjj-resolver-v1-evidence-20261017/diagnostic-01.log 2>&1
env -u PYTHONHOME /private/tmp/zjj-interface-py314-20261017/bin/python -m experiments.trusted_action_resolver_v1_20261017.run_validation /private/tmp/zjj-resolver-v1-evidence-20261017/run-02
git diff --exit-code 4b301f9cbdc61440a9f5ee7e79b7e0af70628f8c -- competition system_dev experiments/interface_feasibility_20261017
```

核心回归和实验各自使用独立随机临时运行目录，二者并行运行，不共享运行数据库或密钥。run-01/diagnostic-01 保留失败；run-02 是修正测试后的完整复测。无吞错重试或放宽安全校验。

结果 JSON 因包含完整公开 COMMIT/工具事实而较大，仓库中以标准 gzip 无损压缩保存：

```sh
python -c "import gzip,json; p='experiments/trusted_action_resolver_v1_20261017/evidence/run-02/results.json.gz'; d=json.loads(gzip.open(p,'rt').read()); print(d['tests'],d['failures'],d['errors'])"
```

运行器本身始终写原始 results.json；本地交付包附未压缩原件。源代码摘要在结果内保存，原文件逐字节核对及实验源代码匹配结果在 evidence/integrity.json。

原文件整体差异与提交前格式核对：

```sh
git diff --exit-code 4b301f9cbdc61440a9f5ee7e79b7e0af70628f8c -- . ':(exclude)experiments/trusted_action_resolver_v1_20261017'
git add experiments/trusted_action_resolver_v1_20261017
git diff --cached --check -- '*.py' '*.md' '*.json' '*.txt'
git commit -m "experiment: verify Trusted Action Resolver v1 six-field contract"
```

发布使用既有 GitHub 连接器的 create_blob/create_tree/create_commit/update_ref，目标仅新隔离分支 experiment/trusted-action-resolver-v1-20261017。逐文件 Git blob SHA 与完整 tree SHA 均与本地验证版本比对，拒绝不一致的发布；不合并 main。远端与本地提交元数据可能不同，文件树应完全相同，实际 SHA 记于本地 DELIVERY.json。
