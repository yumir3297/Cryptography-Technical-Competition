"""Append-only six-field conformance and existing 22-probe regression runner."""
import datetime
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import unittest
from pathlib import Path
from experiments.interface_feasibility_20261017 import test_probe, run_probe
from experiments.trusted_action_resolver_v1_20261017 import test_resolver

test_resolver.ResolverCases.tearDown=run_probe.observe

if __name__=='__main__':
    target=Path(sys.argv[1]);target.mkdir(parents=True,exist_ok=False)
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(test_resolver.ResolverCases),
                             unittest.defaultTestLoader.loadTestsFromTestCase(test_probe.Probe)])
    root=Path(__file__).resolve().parents[2]
    paths=[Path(__file__),Path(test_resolver.__file__),root/'experiments/interface_feasibility_20261017/adapter.py',root/'experiments/interface_feasibility_20261017/lab.py']
    meta={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'python':sys.version,'platform':platform.platform(),
          'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
          'argv':sys.argv,'suite':'Trusted Action Resolver V1.0 six-field conformance + prior E1-E4',
          'source_sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
          'dependencies':{p:importlib.metadata.version(p) for p in ('cryptography','jsonschema')}}
    with (target/'tests.log').open('x') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=run_probe.Result).run(suite)
    meta.update(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),results=result.records)
    (target/'results.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:meta[k] for k in ('tests','failures','errors')}))
    raise SystemExit(not result.wasSuccessful())
