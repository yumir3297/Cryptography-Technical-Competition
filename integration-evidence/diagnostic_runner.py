"""Observe original failures before unittest cleanup; never change guard outcomes.

Run from repository root with this directory on PYTHONPATH. Only public DB tables
and signed samples are exported. Runtime private keys and raw DBs are excluded.
"""
import collections
import hashlib
import importlib.metadata
import json
import os
import sys
import time
import unittest
import subprocess
import platform
from pathlib import Path

ROOT=Path.cwd()
sys.path.insert(0,str(ROOT))

def run(output, names=None):
    target=Path(output);target.mkdir(parents=True,exist_ok=False)
    def source_hashes():
        files=sorted(Path('competition').rglob('*.py'))+sorted(Path('system_dev').rglob('*.py'))
        files += [Path(__file__),Path(__file__).with_name('observed_clock_worker.py'),Path('competition/run_unified_checks.sh')]
        return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.exists()}
    before_sources=source_hashes()
    (target/'source-before.json').write_text(json.dumps(before_sources,indent=2))
    (target/'environment.json').write_text(json.dumps({'python':sys.version,'platform':platform.platform(),
        'cryptography':importlib.metadata.version('cryptography'),'jsonschema':importlib.metadata.version('jsonschema'),
        'PYTHONHOME_unset':'PYTHONHOME' not in os.environ,'monotonic':vars(time.get_clock_info('monotonic'))},indent=2))
    previous_test_env=os.environ.get('ZJJ_DIAGNOSTIC_TEST')
    context={'test':'bootstrap'}
    samples=collections.deque(maxlen=24)
    observations=[]
    from competition.core.signing import ClockClient
    from competition.core.trusted_state import TrustedState
    original_sample=ClockClient.sample
    original_db=TrustedState.db
    original_popen=subprocess.Popen
    diagnostic_child=Path(__file__).with_name('observed_clock_worker.py').resolve()
    observation_file=(target/'child-clock-observations.jsonl').resolve()
    def observed_popen(command,*args,**kwargs):
        if type(command) is list and len(command)>=4 and command[1]=='-m':
            role=None
            if command[2]=='competition.core.signing' and command[3]=='C':role='C';tail=command[4:]
            elif command[2]=='competition.core.common_receipt':role='X';tail=command[3:]
            elif command[2] in ('competition.tests.transport_fixture','competition.w_cases'):
                role='runtime';tail=command[2:]
            if role:
                command=[command[0],str(diagnostic_child),role,*tail]
                kwargs['env']={**os.environ,**kwargs.get('env',{}),
                    'ZJJ_CLOCK_OBSERVATION_FILE':str(observation_file)}
        return original_popen(command,*args,**kwargs)
    subprocess.Popen=observed_popen
    paths=set()
    def observed_sample(self,*args):
        before=time.monotonic_ns()
        try:
            result=original_sample(self,*args)
            samples.append({'test':context['test'],'packet':result,
                'received_monotonic_ns':str(time.monotonic_ns()),
                'rpc_elapsed_ns':str(time.monotonic_ns()-before)})
            if not result['claim']['healthy']:
                observations.append({'kind':'UNHEALTHY_SAMPLE','test':context['test'],
                    'samples':list(samples)})
            return result
        except BaseException as exc:
            observations.append({'kind':'CLOCK_SAMPLE_ERROR','test':context['test'],
                'code':getattr(exc,'code',type(exc).__name__),'samples':list(samples)})
            raise
    def observed_db(self):
        paths.add(self.path)
        return original_db(self)
    ClockClient.sample=observed_sample
    TrustedState.db=observed_db

    def snapshot(test,error):
        import sqlite3
        from contextlib import closing
        states=[]
        for path in paths:
            if not Path(path).exists():continue
            try:
                with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as c:
                    c.row_factory=sqlite3.Row
                    tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    data={}
                    for table in ('w_operation','w_outbox','w_reservation','w_consumed','app_request','comp_event_clock'):
                        if table in tables:data[table]=[dict(r) for r in c.execute('SELECT * FROM '+table)]
                    if 'a_journal' in tables:
                        data['receipt_pending']=[dict(r) for r in c.execute("SELECT * FROM a_journal WHERE kind='W_RECEIPT_PENDING'")]
                    states.append({'database':Path(path).name,'tables':data})
            except sqlite3.Error as exc:states.append({'snapshot_error':str(exc)})
        observations.append({'kind':'TEST_FAILURE','test':test.id(),'traceback':error,
            'samples':list(samples),'persistent_state_before_cleanup':states})

    class Result(unittest.TextTestResult):
        def startTest(self,test):
            context['test']=test.id();os.environ['ZJJ_DIAGNOSTIC_TEST']=test.id()
            samples.clear();paths.clear();super().startTest(test)
        def addError(self,test,err):
            snapshot(test,self._exc_info_to_string(err,test));super().addError(test,err)
        def addFailure(self,test,err):
            snapshot(test,self._exc_info_to_string(err,test));super().addFailure(test,err)
        def addSubTest(self,test,subtest,err):
            if err:snapshot(subtest,self._exc_info_to_string(err,test))
            super().addSubTest(test,subtest,err)

    suite=unittest.defaultTestLoader.loadTestsFromNames(names) if names else unittest.defaultTestLoader.discover('competition/tests')
    try:
        with (target/'tests.log').open('x') as log:
            result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Result).run(suite)
        after_sources=source_hashes()
        (target/'source-after.json').write_text(json.dumps(after_sources,indent=2))
        summary={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
                 'successful':result.wasSuccessful(),'observations':observations,
                 'sources_unchanged':before_sources==after_sources,
                 'guard_semantics_modified':False}
        (target/'results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
        print(json.dumps({k:v for k,v in summary.items() if k!='observations'}),flush=True)
        return 0 if result.wasSuccessful() and before_sources==after_sources else 1
    finally:
        ClockClient.sample=original_sample;TrustedState.db=original_db
        subprocess.Popen=original_popen
        if previous_test_env is None:os.environ.pop('ZJJ_DIAGNOSTIC_TEST',None)
        else:os.environ['ZJJ_DIAGNOSTIC_TEST']=previous_test_env

if __name__=='__main__':sys.exit(run(sys.argv[1],sys.argv[2:] or None))
