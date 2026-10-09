"""Export the exact latest run's per-case evidence into readable CSV/Markdown."""
from __future__ import annotations
import csv,json
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main():
 src=ROOT/'official39_evidence_report.json';report=json.loads(src.read_text(encoding='utf-8'))
 dest=ROOT/'official39_evidence_matrix.csv'
 with dest.open('w',newline='',encoding='utf-8-sig') as f:
  cols=['id','profile','status','official_full_conformance','run','passed','seconds','expected','executed_tests','missing_full_requirements']
  w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
  for x in report['cases']:
   w.writerow({'id':x['id'],'profile':x['profile'],'status':x['status'],
               'official_full_conformance':x['official_full_conformance'],
               'run':x.get('run',0),'passed':x.get('passed',0),'seconds':x.get('seconds',0),
               'expected':x['expected'],'executed_tests':' | '.join(x.get('test_ids',[])),
               'missing_full_requirements':' | '.join(x['missing_full_requirements'])})
 out=['# ZJJ-CORE-2.6-R2 — 39项正式语义符合性验收：独立执行证据报告',
      '', '**注意：这是39项对应的局部执行证据，不是39项官方完整通过。**', '',
      f"- 按用例独立运行：{report['summary']['cases_selected']} 项",
      f"- 具有通过的局部见证：{report['summary']['local_witness_passed_cases']} 项",
      f"- 实际运行关联测试：{sum(x.get('run',0) for x in report['cases'])} 次",
      f"- 官方完整符合性通过：{report['summary']['official_complete_pass']} 项",
      f"- 官方清单原件：{report['original_manifest']['status']}",
      f"- PAY Schema：{report['official_schema_gates']['PAY-1']['status']}",
      f"- IND Schema：{report['official_schema_gates']['IND-DEMO-1']['status']}",
      f"- MED Schema：{report['official_schema_gates']['MED-DEMO-1']['status']}", '',
      '| 官方用例 | 当前局部测试 | 测试数 | 尚缺的重要条件 |', '|---|---|---:|---|']
 for x in report['cases']:
  cond='；'.join(x['missing_full_requirements'])
  out.append(f"| {x['id']} | {x['status']} | {x.get('run',0)} | {cond.replace('|','/')} |")
 out+=['', '## 关键边界', '',
       '1. `CORE-19` 的 C 控制主体是本地可信实验夹具，尚无真实跨服务认证。',
       '2. `IND-04` 的工具最终事实使用实验室固定钥，而非外部受控 TOOL_TRUST 与完整账连续性。',
       '3. `CORE-13` 在旧 FinalW 领取逻辑存在已复现的撤销安全缺口；受控 GuardedFinalW 是局部补丁，尚未全链路接入。',
       '4. 原仓库官方 Schema 与用例清单需要与本 ZIP 合并后验证固定 Git blob，单元测试通过不自动满足官方要求。',
       '', '运行方式：`python -m research.conformance39.run39 --upstream-root .`',
       '']
 (ROOT/'official39_summary.md').write_text('\n'.join(out),encoding='utf-8')
 print(str(dest));print(str(ROOT/'official39_summary.md'))

if __name__=='__main__':main()
