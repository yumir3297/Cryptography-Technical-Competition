# 复现入口

在工作区根目录（含 `competition/`）执行。依赖：

```powershell
python -m pip install -r requirements.txt
python -m pip install -r competition/agent/requirements.txt
```

## quick

验证已生成证据包和独立验证器负例，不需要重新初始化 W：

```powershell
python competition/evaluation/reproduce/run_quick.py
```

## demo

运行 GoalFloor 正常/挤占/UNKNOWN/离线审计的定向测试：

```powershell
python competition/evaluation/reproduce/run_demo.py
```

## full

完整组件/恢复回归：

```powershell
python -m unittest discover -s competition/tests -v
```

Linux 下若 127.0.0.1 被代理拦截，设置：

```bash
export NO_PROXY=127.0.0.1,localhost
```

Windows 全量存在 Linux DAC/Unix socket 环境失败；应使用 Linux/WSL。

## 证据

```powershell
python -m competition.evaluation.verify `
  competition/evaluation/evidence/20261123/IND-DEMO-1-package.json `
  competition/evaluation/evidence/20261123/anchor-three-profiles.json
```

预期 `status: PASS`, `passed: 13`, `failed: 0`。anchor 必须通过独立渠道固定。
