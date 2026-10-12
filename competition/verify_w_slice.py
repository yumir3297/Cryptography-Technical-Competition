"""Read-only independent public artifact verifier. No service or tool calls."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from competition.support.wire import require, raw, b64, canonical, digest, rec_ref, msgref, strict_verify, action_hash
from competition.support.tool_final import final_fact_id, final_sign_bytes, verify_certificate
from competition.tools.common_tool import ledger_head, request_hash
from competition.run_authorization_slice import write

ROOT=Path(__file__).resolve().parents[1]
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def decode(v):
    if isinstance(v,str) and v[:1] in ('{','['):
        try:return json.loads(v)
        except json.JSONDecodeError:pass
    return v

def verify(output,*,expected_root_manifest=None,expected_case_count=22,historical_source=False):
    report=read(output/'report.json');manifest=read(output/'manifest.json');checks=[];sig_count=0;clock_count=0
    def check(label,ok):
        require(bool(ok),'AUDIT_'+label);checks.append(label)
    check('manifest_hashes',all(sha(output/f['path'])==f['sha256'] and (output/f['path']).stat().st_size==f['size'] for f in manifest['files']))
    recorded_commit=report['build']['commit']
    checkout_crlf_paths=[]
    if historical_source:
        def recorded_source_matches(row):
            path=row['path']
            content=subprocess.check_output(['git','show',recorded_commit+':'+path],cwd=ROOT)
            if hashlib.sha256(content).hexdigest()==row['sha256']:
                return True
            checkout=content.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
            matched=hashlib.sha256(checkout).hexdigest()==row['sha256']
            if matched:checkout_crlf_paths.append(path)
            return matched
        check('historical_source_hashes',all(recorded_source_matches(f) for f in report['build']['source_files']))
    else:
        check('source_hashes',all(sha(ROOT/f['path'])==f['sha256'] for f in report['build']['source_files']))
    check('source_digest',hashlib.sha256(json.dumps(report['build']['source_files'],sort_keys=True).encode()).hexdigest()==report['build']['source_digest'])
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    if historical_source:
        check('recorded_commit_exists',subprocess.check_output(['git','rev-parse',recorded_commit+'^{commit}'],cwd=ROOT,text=True).strip()==recorded_commit)
    else:
        check('build_commit',head==recorded_commit)
    check('all_declared_cases',len(report['cases'])==expected_case_count and report['passed'] and all(c['status']=='PASS' for c in report['cases']))
    if expected_case_count==22:
        expected={(p,n) for p in ('PAY-1','IND-DEMO-1','MED-DEMO-1') for n in ('normal','lost_ack','unknown_query','concurrent_claim_settle','conflicting_final','w_commit_crash')}
        expected|={('IND-DEMO-1',n) for n in ('same_intent8','last_resource','claim_cancel_revoked','claimed_cancel8')}
        check('unique_required_scenarios',{(c['profile'],c['scenario']) for c in report['cases']}==expected and len({c['evidence'] for c in report['cases']})==22)
    # The fixed external run manifest may be pinned by a caller. Embedded keys
    # alone prove internal consistency, not an independently trusted authority.
    if expected_root_manifest:check('external_manifest_pin',sha(output/'manifest.json')==expected_root_manifest)
    for case in report['cases']:
        data=read(output/case['evidence']);public=data['public_ledgers'];root=raw(public['root_public'],32);tables=public['tables']
        check('case_run_binding',data['run_id']==report['run_id'] and data['case']==case['scenario'] and data['profile']==case['profile'] and data['status']==case['status'])
        pubs={w['kid']:raw(w['public_key'],32) for r in public['roster'].values() for w in r.values()}
        worker=public['worker_certificate']['claim'];wp=raw(worker['public_key'],32)
        boot=json.loads(next(r['blob'] for r in tables['a_journal'] if r['kind']=='W_BOOTSTRAP'));delivery=raw(boot['delivery_public'],32)
        check('worker_delivery_separation',wp!=delivery)
        trusts={}
        for row in tables['w_tool']:
            cert=json.loads(row['certificate']);r=verify_certificate(cert,root,row['profile']);trusts[row['profile']]=r
            pubs[r['value']['kid']]=raw(r['value']['public_key'],32)
        seen=set()
        def walk(value):
            nonlocal sig_count,clock_count
            value=decode(value)
            if isinstance(value,list):
                for x in value:walk(x)
                return
            if not isinstance(value,dict):return
            if 'protected' in value and 'body' in value and 'sig' in value:
                token=('msg',value['sig'])
                if token not in seen:
                    strict_verify(pubs[value['protected']['kid']],raw(value['sig'],64),canonical(['ZJJ-SIG-v1',value['protected'],value['body']]));seen.add(token);sig_count+=1
            if value.get('kind') in ('IND_EVIDENCE','MED_EVIDENCE'):
                att=value['value']['attestation'];token=('source',att['sig'])
                if token not in seen:
                    header={k:att[k] for k in ('issuer','kid','iat','exp')};strict_verify(pubs[att['kid']],raw(att['sig'],64),canonical(['ZJJ-SOURCE-v1','2.6',value['profile'],value['kind'],value['scope'],value['value']['data'],header]));seen.add(token);sig_count+=1
            if value.get('kind')=='TOOL_FINAL':
                att=value['value']['attestation'];token=('final',att['sig'])
                if token not in seen:strict_verify(pubs[att['kid']],raw(att['sig'],64),final_sign_bytes(value));seen.add(token);sig_count+=1
            if 'claim' in value and 'signature' in value:
                cl=value['claim'];token=('cert',value['signature'])
                if token not in seen:
                    signer=root;domain=None
                    if 'provider_id' in cl:domain='ZJJ-COMP-EVENT-CLOCK-v1';clock_count+=1
                    elif 'namespace' in cl and 'previous_revision' in cl:domain='COMP-APP-C-PUBLISH-v1'
                    elif 'complete' in cl and 'purposes' in cl:domain='COMP-APP-DENY-COVERAGE-v1'
                    elif 'capacity' in cl:domain='COMP-W-RESOURCE-v1'
                    elif 'public_key' in cl and 'profiles' in cl:domain='COMP-W-WORKER-GRANT-v1'
                    elif 'ledger_origin' in cl and 'record' in cl:domain='ZJJ-CONTROL-TOOL-v1'
                    elif 'ledger_head' in cl and 'request_hash' in cl:domain='COMP-TOOL-CHECKPOINT-v1';signer=raw(trusts[cl['profile']]['value']['public_key'],32)
                    elif 'action' in cl and 'attempt_id' in cl:domain='COMP-W-TOOL-QUERY-v1' if 'query_id' in cl else 'COMP-W-TOOL-EXEC-v1';signer=delivery
                    elif 'purpose' in cl and 'commit_ref' in cl:
                        signer=wp if cl['purpose'] not in ('STATUS','AUDIT') else raw(public['roster'][cl['profile']]['H']['public_key'],32);domain='COMP-W-WORKER-v1' if signer==wp else 'COMP-W-READ-v1'
                    elif 'ticket_id' in cl:domain='COMP-APP-ACCEPT-v1';signer=raw(public['roster'][cl['profile']]['H']['public_key'],32)
                    elif 'stage' in cl and 'nonce' in cl:domain='COMP-APP-AUTHZ-IDENTITY-v1';signer=raw(public['roster'][cl['profile']]['H']['public_key'],32)
                    check('recognized_signature_domain',domain is not None);strict_verify(signer,raw(value['signature'],64),canonical([domain,cl]));seen.add(token);sig_count+=1
            for v in value.values():walk(v)
        walk(data)
        for row in tables['a_current']:
            cert=json.loads(row['certificate']);check('C_current_bound',cert['claim']['record']==json.loads(row['record']) and int(cert['claim']['previous_revision'])+1==row['revision'])
        ops={(r['profile'],r['oid']):r for r in tables['w_operation']}
        for key,row in ops.items():
            frozen=json.loads(row['frozen']);commit=frozen['commit'];cv=commit['value'];core=frozen['acceptance_core']
            check('frozen_COMMIT_ref',rec_ref(commit)==frozen['commit_ref']==core['body']['payload']['commit_record_ref'])
            check('frozen_Action',cv['action']==frozen['op']['action'] and cv['ctx']['action_hash']==action_hash(key[0],cv['action']))
            if row['receipt']:check('exact_receipt_core',{k:v for k,v in json.loads(row['receipt']).items() if k!='sig'}==core)
            out=next(o for o in tables['w_outbox'] if (o['profile'],o['oid'])==key)
            if out['packet']:
                packet=json.loads(out['packet']);cl=packet['claim'];check('dispatch_binding',cl['commit_ref']==frozen['commit_ref'] and cl['action']==cv['action'] and cl['operation_id']==key[1] and cl['attempt_id']==out['attempt_id'] and cl['acceptance_ref']==msgref(json.loads(row['receipt'])))
            reservations=[r for r in tables['w_reservation'] if (r['profile'],r['oid'])==key]
            check('reservation_owner',len(reservations)==1 and [r['id'] for r in reservations]==cv['reservation_ids'] and reservations[0]['amount']==int(cv['reservation_plan'][0]['amount']))
            flight=next(f for f in tables['w_flight'] if (f['profile'],f['oid'])==key)
            check('flight_matches_reservation',bool(flight['active'])==(reservations[0]['state']=='RESERVED'))
        for r in tables['w_resource']:
            owned=[x for x in tables['w_reservation'] if x['profile']==r['profile'] and x['key']==r['key']]
            check('resource_reconciles',r['reserved']==sum(x['amount'] for x in owned if x['state']=='RESERVED') and r['spent']==sum(x['amount'] for x in owned if x['state']=='SPENT') and 0<=r['spent']+r['reserved']<=r['capacity'])
        for row in tables['w_mutable']:
            r=json.loads(row['record']);key=json.loads(row['key']);check('mutable_StateRef',row['ref']==digest(['ZJJ-STATE-v1',row['namespace'],key,str(row['revision']),r['value']]))
            genesis=next(g for g in tables['a_current'] if (g['profile'],g['namespace'],g['key'])==(row['profile'],row['namespace'],row['key']))
            check('genesis_unchanged',genesis['ref']==row['genesis_ref'] and genesis['revision']==row['genesis_revision'])
        effects_by_key={}
        for p,tool in public['tools'].items():
            facts=[f['fact'] for f in tool['finalfacts']];check('independent_ledger_head',tool['meta']['ledger_head']==ledger_head(tool['meta']['ledger_id'],facts) and tool['meta']['high_water']==len(facts))
            effects=[e for es in tool['effects'].values() for e in es];check('effect_fact_bijection',len(effects)==len(facts)==len(tool['requests']))
            for f in tool['finalfacts']:
                record={'profile':p,'scope':trusts[p]['scope'],'value':f['fact']};check('immutable_fact_identity',f['final_fact_id']==final_fact_id(record))
                request=next(r for r in tool['requests'] if r['operation_id']==f['operation_id']);check('tool_request_dedup',request['request_hash']==request_hash(request['claim']) and request['attempt_id']==f['attempt_id'])
                effect=next(e for e in effects if e['operation_id']==f['operation_id']);check('original_sim_effect',effect['attempt_id']==f['attempt_id'] and effect['effect_id']==f['effect_id'] and effect['payload']==request['claim']['action']['payload']);effects_by_key[(p,f['operation_id'])]=f
        for s in tables['w_settlement']:
            f=effects_by_key[(s['profile'],s['oid'])];check('independent_once_settlement',s['fact_id']==f['final_fact_id'] and s['effect_id']==f['effect_id'] and s['final_seq']==str(f['final_seq']))
        counts=data['counts'];outboxes=tables['w_outbox']
        check('independent_W_counts',counts['accepts']==len(ops) and counts['outbox']==len(outboxes) and counts['attempts']==sum(o['attempt_id'] is not None for o in outboxes) and counts['exec_invocations']==sum(o['exec_marker'] for o in outboxes) and counts['execution_sends_observed']==sum(o['send_observed'] or 0 for o in outboxes) and counts['queries']==sum(o['queries'] for o in outboxes) and counts['settlements']==len(tables['w_settlement']))
    result={'kind':'independent_readonly_scoped_W_simulator_verification','passed':True,'build_commit':recorded_commit,'verifier_checkout_commit':head,'source_mode':'git_recorded_commit' if historical_source else 'current_checkout','source_digest':report['build']['source_digest'],'run_id':report['run_id'],'case_count':len(report['cases']),'checks':len(checks),'verified_signatures':sig_count,'verified_C_time_packets':clock_count,'external_manifest_pin_verified':bool(expected_root_manifest),'limits':['Historical signatures, references and independent ledger equality; no current-time authorization re-created by audit.','Run trust roots must be pinned externally for adversarial audit; embedded roots alone prove package consistency.','No complete R2 AUDITBundle or whole-disk rollback guarantee.']}
    result['source_checkout_crlf_paths']=checkout_crlf_paths
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);parser.add_argument('--manifest-sha256');parser.add_argument('--report',type=Path,required=True);parser.add_argument('--historical-source',action='store_true');args=parser.parse_args();result=verify(args.output,expected_root_manifest=args.manifest_sha256,historical_source=args.historical_source);write(args.report,result);print(json.dumps(result))
