"""Verify observed per-module regression logs without counting timed-out invocation."""
from pathlib import Path
import hashlib,json
HERE=Path(__file__).parent
modules={
'phase5.test_durable_w':(20,'test_durable_w.txt'),
'phase6.test_trusted_final':(28,'test_trusted_final.txt'),
'phase7.test_guarded_dispatch':(11,'test_guarded_dispatch.txt'),
'phase7.test_dispatch_gap':(1,'test_dispatch_gap.txt'),
'phase7.test_official_contract':(7,'test_official_contract.txt'),
'phase8.test_scene_authority':(54,'phase8_split.txt'),
'phase11.test_phase11':(17,'phase11_split.txt'),
'phase12.test_phase12':(7,'test_run.txt')}
entries=[]
for module,(num,filename) in modules.items():
    path=HERE/filename
    data=path.read_text(encoding='utf8')
    assert f'Ran {num} test' in data and data.strip().endswith('OK'),(module,filename)
    entries.append({'module':module,'executed':num,'passed':num,'status':'MODULE_RUN_PASS',
                    'log':'research/phase12/'+filename,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
report={'strategy':'MODULE_BY_MODULE_AFTER_COMBINED_TIMEOUT',
        'combined_run':'TIMED_OUT; NOT COUNTED','total_methods_passed':sum(x['passed'] for x in entries),
        'not_official_conformance':True,'modules':entries}
(HERE/'module_regression_summary.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
print('module_tests_verified',report['total_methods_passed'])
