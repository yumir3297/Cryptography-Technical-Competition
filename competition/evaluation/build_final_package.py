"""Build ZJJ-CORE-Final-Acceptance-20261124.zip from the actual results."""
from __future__ import annotations
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT.parents[2] / 'outputs'
STAGE = OUT / 'ZJJ-CORE-Final-Acceptance-20261124'
ZIP = OUT / 'ZJJ-CORE-Final-Acceptance-20261124.zip'

DOCS = {
    'research-status.md': 'research-status.md',
    'protocol-boundary.md': 'protocol-boundary.md',
    'core-contributions.md': 'core-contributions.md',
    'invariant-spec.md': 'invariant_spec.md',
    'threat-model.md': 'threat_model.md',
    'experiment-matrix.md': 'experiment_matrix.md',
    'experiment-conclusions.md': 'experiment_conclusions.md',
    'conformance-39.md': 'conformance_39.md',
    'final-acceptance.md': 'final-acceptance.md',
    'judge-replay.md': 'judge_replay.md',
    'remaining-limitations.md': 'remaining-limitations.md',
}
APPENDICES = ['protocol_audit.md', 'baseline_comparison.md', 'crypto_attack_results.md',
              'concurrency_results.md', 'crash_recovery_results.md', 'goalcommit_ablation.md',
              'performance_results.md', 'innovation_summary.md', 'open_issues.md']
LOGS = {
    '.runtime/long-sequence-final2.log': 'long-sequence.log',
    '.runtime/concurrency-bulk-final.log': 'concurrency-bulk.log',
    '.runtime/goal-cross-final.log': 'goal-cross.log',
    '.runtime/crash-report.log': 'crash-report.log',
    '.runtime/performance-final.log': 'performance.json.log',
    '.runtime/performance-bulk-final.log': 'performance-bulk.log',
    '.runtime/model-check.log': 'model-check.log',
    '.runtime/linux-full-526.log': 'linux-full-526.log',
    '.runtime/final-new-suite.log': 'final-new-suite.log',
    '.runtime/ablation-final.log': 'ablation.log',
    '.runtime/crypto-attacks.log': 'crypto-attacks.log',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def main():
    if STAGE.exists():
        shutil.rmtree(STAGE)
    if ZIP.exists():
        ZIP.unlink()
    STAGE.mkdir(parents=True)

    copy(ROOT / 'FINAL_VERDICT.md', STAGE / 'FINAL_VERDICT.md')
    for name, src in DOCS.items():
        copy(ROOT / 'competition/evaluation' / src, STAGE / 'docs' / name)
    for name in APPENDICES:
        copy(ROOT / 'competition/evaluation' / name, STAGE / 'docs' / 'appendices' / name)

    results = ROOT / 'competition/evaluation/results'
    for path in sorted(results.glob('*.json')):
        copy(path, STAGE / 'results' / path.name)
    for name in ('README.md',):
        if (results / name).exists():
            copy(results / name, STAGE / 'results' / name)

    for src, name in LOGS.items():
        path = ROOT / src
        if path.exists():
            copy(path, STAGE / 'logs' / name)

    evidence = ROOT / 'competition/evaluation/evidence'
    for folder in ('20261123', 'incident-20261123'):
        for path in sorted((evidence / folder).iterdir()):
            if path.is_file():
                copy(path, STAGE / 'evidence' / folder / path.name)

    counter = ROOT / 'competition/evaluation/counterexamples'
    for path in sorted(counter.glob('*.json')):
        copy(path, STAGE / 'counterexamples' / path.name)

    figures = ROOT / 'competition/evaluation/figures'
    for path in sorted(figures.glob('*')):
        copy(path, STAGE / 'figures' / path.name)

    reproduce = ROOT / 'competition/evaluation/reproduce'
    for path in sorted(reproduce.glob('*')):
        copy(path, STAGE / 'reproduce' / path.name)

    readme = '''# ZJJ-CORE Final Acceptance — GoalFloor（2026-11-24）

## 结论

**CONDITIONAL_READY**。核心创新获得真实 CommonW 长序列差分、40 条真实并发历史、15+ 项密码学关系负例、3 个崩溃边界、跨 Profile GoalFloor 和 4,363 状态有界模型支持；但正式 39 项未闭合、样本量未达目标、工具换钥/账丢失未跑、Linux 全量仍有环境性尾项。

## 构建身份

- 原协议基线：`7604d6b5b902f38d950234dec53d9375429f1e7f`
- 本轮代码/证据生成：`7f5dd03c404a9320dfebd4bcf0d87c8cd53e8a7c`
- 最终文档/证据提交：以 Git 分支 HEAD 为准
- 分支：`integration/goalcommit-shadow-20261123`

## 实际结果

| 实验 | 结果 |
|---|---|
| E1 长序列 | 20 条真实配对、112 动作、off 84 / enforce 76、20 个真实反例、Oracle mismatch 0；10,000 条四类模型序列 |
| E2 并发 | 40 条真实 W 历史全部线性化；10,000 条参考模型、240,000 转移、0 违反 |
| E3 绑定 | 15/15 篡改/重放拒绝；新增容量/Profile/资源/epoch 关系测试 |
| E4 恢复 | 3/3 崩溃边界；UNKNOWN 保留；停用有 PENDING 时 `GOAL_INACTIVE_PENDING`；enforce 唯一索引 |
| E5 跨场景 | IND/PAY/MED/事件响应；PAY/MED 正常 GoalFloor 审计 PASS，挤占动作 `GOAL_CAPACITY_FLOOR` |
| E6 性能 | 纯 GoalFloor p50 98.2µs；8 单元 40 次/模式；off p50 1324.9ms，enforce 1338.4ms；证据 +6.5KB |
| E7 模型 | 4,363 状态、67,746 转移、0 违反 |
| 39 项 | 2 PASS / 0 FAIL / 22 PARTIAL / 15 NOT_RUN |
| Linux | 526 tests，1 failure / 3 errors，均为环境；隔离复跑通过，未宣称单一进程全绿 |

## 目录

- `docs/`：研究状态、边界、贡献、不变量、威胁模型、实验矩阵/结论、39 项、验收矩阵、评委复验、剩余限制；`docs/appendices/` 为详细审计与专项报告。
- `results/`：机器可读结果 JSON（长序列、并发、篡改、崩溃、跨场景、性能、模型、39 项、Linux 回归）。
- `logs/`：真实运行日志。
- `evidence/`：三 Profile + Goal + 事件响应证据包、anchor、审计、manifest。
- `counterexamples/`：E1 真实 off 接受/Proposed 拒绝反例包。
- `figures/`：SVG/PNG/CSV 图表。
- `reproduce/`：quick/demo/full 复现入口。

## 一键复验

在分支 checkout 中：

```powershell
python competition/evaluation/reproduce/run_quick.py
```

或只验证一个包：

```powershell
python -m competition.evaluation.verify `
  competition/evaluation/evidence/20261123/IND-DEMO-1-package.json `
  competition/evaluation/evidence/20261123/anchor-three-profiles.json
```

预期 `status: PASS`, `passed: 13`, `failed: 0`。

## 不声称

不证明目标最终可达；不提供跨 Profile 原子性；不证明 W 账本现实真实性、证据当期性、真实设备效果；不宣称 39/39 全部通过；不把模拟支付/医疗/工业/隔离当生产效果。
'''
    (STAGE / '00_README.md').write_text(readme, encoding='utf-8')

    rows = []
    for path in sorted(STAGE.rglob('*')):
        if path.is_file() and path.name != 'MANIFEST-SHA256.txt':
            rows.append(f'{sha(path)}  {path.relative_to(STAGE).as_posix()}')
    (STAGE / 'MANIFEST-SHA256.txt').write_text('\n'.join(rows) + '\n', encoding='utf-8')

    with zipfile.ZipFile(ZIP, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(STAGE.rglob('*')):
            if path.is_file():
                zf.write(path, arcname=path.relative_to(STAGE.parent).as_posix())
    print('STAGE', STAGE)
    print('ZIP', ZIP)
    print('FILES', len(rows) + 1)
    print('ZIP_BYTES', ZIP.stat().st_size)


if __name__ == '__main__':
    main()
