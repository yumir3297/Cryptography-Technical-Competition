"""Selected actual W lifecycle checks for protocol 1.1 wording, no W changes."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from competition.profiles.w_seed import initialize
from competition.w_cases import accept_operation,tool_snapshot,public_snapshot,_test_sign_final
from competition.support.wire import digest

def main():
    output=ROOT/'competition/evidence/protocol-optimization-20261012'
    output.mkdir(parents=True,exist_ok=True)
    target=output/'runtime-semantics.json'
    if target.exists():raise ValueError('Preserve existing evidence; use a new report path for a new run')
    run=initialize(ROOT/'.runtime'/('protocol-optimization-'+time.strftime('%Y%m%d-%H%M%S')))
    try:
        p='IND-DEMO-1';oid,_=accept_operation(run,p)
        run.w.claim(p,oid,run.worker_proof(p,oid,'CLAIM'))
        view=lambda:run.w.status(p,oid,run.read_proof(p,oid))
        before=view()
        assert before['dispatch_state']=='STARTED' and before['effect_state']=='UNKNOWN'
        assert before['exec_consumed'] is False
        response=run.w.execute_once(p,oid,run.worker_proof(p,oid,'EXECUTE'))
        after=view()
        assert response['state']=='SUCCEEDED' and after['effect_state']=='SUCCEEDED'
        assert after['dispatch_state']=='STARTED' and after['exec_consumed'] is True
        assert run.w.counts()['settlements']==0 and tool_snapshot(run,p)['effect_count']==1
        counts=run.w.counts()
        repeated=run.w.execute_once(p,oid,run.worker_proof(p,oid,'EXECUTE'))
        assert repeated['state']=='UNKNOWN' and repeated['reason']=='EXEC_ALREADY_CONSUMED'
        assert run.w.counts()==counts
        settled=run.w.settle(p,oid,response,run.worker_proof(p,oid,'SETTLE'))
        settled_view=view();assert settled_view['dispatch_state']=='SETTLED'
        # Controlled trusted contradiction after settlement: retain history, stop operation.
        conflict=copy.deepcopy(response)
        conflict['record']['value']['effect_id']='controlled-post-settlement-conflict'
        conflict['checkpoint']['claim']['ledger_head']=digest(['CONTROLLED-POST-SETTLEMENT',oid])
        conflict=_test_sign_final(run,p,conflict)
        stopped=run.w.settle(p,oid,conflict,run.worker_proof(p,oid,'SETTLE'))
        halted=view()
        assert stopped['state']=='HALTED' and halted['dispatch_state']=='HALTED'
        assert halted['effect_state']=='SUCCEEDED' and run.w.counts()['settlements']==1
        assert tool_snapshot(run,p)['effect_count']==1
        cases=[{'name':'UNKNOWN-with-unconsumed-first-EXEC','passed':True},
               {'name':'confirmed-effect-before-settlement','passed':True},
               {'name':'consumed-EXEC-no-repeat','passed':True},
               {'name':'HALTED-retains-prior-settlement-and-effect','passed':True}]
        result={'kind':'selected_protocol_wording_semantics','passed':True,'case_count':4,'cases':cases,
                'build_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                'common_w_sha256':hashlib.sha256((ROOT/'competition/core/common_w.py').read_bytes()).hexdigest(),
                'profile':p,'operation_id':oid,'before_first_EXEC':before,'after_first_EXEC':after,
                'original_response':response,'repeated_EXEC':repeated,'counts_before_repeat':counts,
                'settlement':settled,'settled_view':settled_view,'controlled_contradiction':conflict,
                'stop_response':stopped,'halted_view':halted,'snapshot':public_snapshot(run,p,oid),
                'limits':['One selected real industrial simulator lifecycle, not full regression.',
                          'Contradiction signed by controlled trusted fixture; no second actual tool effect.',
                          'No application wrapper, logging service or new HALTED rule implemented.']}
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'passed':True,'cases':4,'effects':1,'settlements':1}),flush=True)
    finally:run.close()

if __name__=='__main__':main()
