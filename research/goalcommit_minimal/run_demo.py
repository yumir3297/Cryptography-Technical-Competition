"""Reproducible examples and bounded exhaustive invariant check for GoalCommit."""
from itertools import product
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from goal_commit import (GoalCommitHarness, Reject, evaluate_goal, fixture_key,
                         issue_goal, issue_final, get_commit_ref)
from offline_verify import verify_bundle


def goal(group='cross-task'):
    return {
        'model':'goal-floor-v1','group':group,'epoch':'1',
        'capacity':'3','resource':'w-shared-budget',
        'deps':{'TaskRef':'task-a:1|task-b:1','PolicyRef':'policy:1'},
        'actions':[
            {'name':'mandatory_a','profile':'IND-DEMO-1','obligation':'required:a','cost':'1'},
            {'name':'mandatory_b','profile':'PAY-1','obligation':'required:b','cost':'1'},
            {'name':'optional_diagnostic','profile':'IND-DEMO-1','obligation':'','cost':'1'},
        ],
    }


def exhaustive_invariant():
    """Bounded exhaustive consistency check, not formal verification of real W."""
    count=0;allowed=0;fail=0
    for cap in range(2,8):
        for c1,c2 in product(range(1,4),repeat=2):
            if c1+c2>cap:continue
            g=goal('exhaustive');g['capacity']=str(cap)
            g['actions'][0]['cost']=str(c1);g['actions'][1]['cost']=str(c2)
            for a,b in product(('OPEN','DONE'),repeat=2):
                if a==b=='DONE':continue
                for spent in range(cap+1):
                    for reserved in range(cap-spent+1):
                        ledger={'spent':spent,'reserved':reserved,
                                'status':{'required:a':a,'required:b':b}}
                        for action in g['actions']:
                            count+=1
                            try:
                                result=evaluate_goal(g,ledger,action['name'],action['profile'])
                            except Reject:
                                continue
                            allowed+=1
                            next_status=dict(ledger['status'])
                            if result['obligation']:next_status[result['obligation']]='PENDING'
                            remaining=sum(int(t['cost']) for t in g['actions'] if t['obligation'] and next_status[t['obligation']]=='OPEN')
                            if spent+reserved+int(result['cost'])+remaining>cap:fail+=1
    return {'enumerated_state_action_combinations':count,
            'accepted':allowed,'violations_of_resource_floor_after_accept':fail}


def main():
    c=fixture_key('C');x=fixture_key('X');e=fixture_key('E')
    with TemporaryDirectory() as t:
        w=GoalCommitHarness(Path(t)/'db.sqlite',c.public_key(),x,e.public_key())
        cert=issue_goal(c,goal())
        w.publish(cert)
        before=w.snapshot('cross-task')
        decision=evaluate_goal(goal(),{'spent':int(before['spent']),'reserved':int(before['reserved']),
                         'status':before['status']},'optional_diagnostic','IND-DEMO-1')
        first=w.accept('cross-task','op-1','optional_diagnostic','IND-DEMO-1','0')
        with w.db() as conn:
            commit=json.loads(conn.execute('SELECT commit_body FROM w_operation WHERE oid=?',('op-1',)).fetchone()[0])
        evidence={'c_certificate':cert,'before':before,'decision':decision,'w_commit':commit,
                  'action':{'name':'optional_diagnostic','profile':'IND-DEMO-1','oid':'op-1'},
                  'x_receipt':first}
        # The original single-step capacity-only guard would accept both: 2 <= 3.
        baseline_allows_second=True
        try:
            w.accept('cross-task','op-2','optional_diagnostic','IND-DEMO-1','0')
            stale='ACCEPTED'
        except Reject as err:stale=str(err)
        final=issue_final(e,'op-1',get_commit_ref(w,'op-1'),'SUCCEEDED','fact-op-1')
        evidence['e_final']=final
        w.settle('op-1',final)
        verified=verify_bundle(evidence,c.public_key(),x.public_key(),e.public_key())
        Path(__file__).with_name('sample_evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
        def key_b64(k):
            import base64
            return base64.urlsafe_b64encode(k.public_key().public_bytes_raw()).decode().rstrip('=')
        keys={'c_public':key_b64(c),'x_public':key_b64(x),'e_public':key_b64(e)}
        Path(__file__).with_name('fixture_public_keys.json').write_text(json.dumps(keys,indent=2),encoding='utf-8')
        try:
            w.accept('cross-task','op-2','optional_diagnostic','IND-DEMO-1',w.snapshot('cross-task')['revision'])
            corrected='ACCEPTED'
        except Reject as err:corrected=str(err)
        ref=first['claim']['commit_ref']
        # A and B remain open and require one unit each.
        demonstration={'single_step_baseline_would_allow_second':baseline_allows_second,
                       'second_with_stale_version':stale,
                       'second_after_current_version':corrected,
                       'x_receipt_ref':ref,'final_state':w.snapshot('cross-task')}
    return {'demonstration':demonstration,'offline_evidence_check':verified,
            'exhaustive_floor_check':exhaustive_invariant(),
            'limits':'Finite necessary-condition resource floor; no general reachability or real CommonW integration'}

if __name__=='__main__':
    data=main();Path(__file__).with_name('results.json').write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(data,indent=2,ensure_ascii=False))
