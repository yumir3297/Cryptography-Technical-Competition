"""Run all probes; append-only evidence directory, public observations only."""
import datetime
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
import unittest
from pathlib import Path
from competition.w_cases import public_snapshot
from experiments.interface_feasibility_20261017 import test_probe

def observe(test):
    observation=dict(getattr(test,'notes',{}))
    if hasattr(test,'adapter'):
        with test.run.store.db() as c:
            rows=c.execute('SELECT * FROM exp_proposal ORDER BY request_key').fetchall()
        observation['requests']=[{'key':r['request_key'],'operation_id':r['oid'],
            'construction':json.loads(r['construction']),'request_ref':r['request_ref'],
            'full_op_sha256':hashlib.sha256(r['full_op'].encode()).hexdigest() if r['full_op'] else None} for r in rows]
        observation['w_counts']=test.run.w.counts()
        observation['commits']=[]
        for r in rows:
            with test.run.store.db() as c:
                committed=c.execute('SELECT 1 FROM w_operation WHERE profile=? AND oid=?',(test_probe.P,r['oid'])).fetchone()
            if committed:observation['commits'].append(public_snapshot(test.run,test_probe.P,r['oid']))
    test.observation=observation

test_probe.Probe.tearDown=observe

class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.records=[]
    def startTest(self,test):
        self.started=time.monotonic();super().startTest(test)
    def addSuccess(self,test):
        observation={'test':test.id(),'outcome':'PASS','seconds':round(time.monotonic()-self.started,3)}
        observation.update(getattr(test,'observation',{}))
        self.records.append(observation);super().addSuccess(test)
    def addFailure(self,test,err):
        self.records.append({'test':test.id(),'outcome':'FAIL','detail':self._exc_info_to_string(err,test)})
        super().addFailure(test,err)
    def addError(self,test,err):
        self.records.append({'test':test.id(),'outcome':'ERROR','detail':self._exc_info_to_string(err,test)})
        super().addError(test,err)

if __name__=='__main__':
    target=Path(sys.argv[1]);target.mkdir(parents=True,exist_ok=False)
    metadata={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'python':sys.version,
        'platform':platform.platform(),'argv':sys.argv,
        'baseline':'cc4e36b4e302fcdc53cc809a012c77d8464182af',
        'dependencies':{p:importlib.metadata.version(p) for p in ('cryptography','jsonschema')}}
    metadata['head']=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    with (target/'tests.log').open('x') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Result).run(unittest.defaultTestLoader.loadTestsFromModule(test_probe))
    metadata.update(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),results=result.records)
    (target/'results.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:metadata[k] for k in ('tests','failures','errors')}))
    raise SystemExit(not result.wasSuccessful())
