"""Deterministic hand-oracle tests for PAY history-int-v2 and typed signed records."""
import copy,unittest,random
from research.reference_executor.wire import Identity,ProtocolError,canonical,b64,raw,keyid,rec_ref,action_hash,sid,digest,sortset
from .pay_history import (history_int_v2,parse_history,parse_task,parse_policy,parse_action,
    verify_pay_authoritative,verify_assessment,assessment_from,fields)

S={'domain':'lab','tenant':'tenant-1','scenario':'payment'}

def rr(kind,value):return {'version':'2.6','profile':'PAY-1','kind':kind,'scope':copy.deepcopy(S),'value':copy.deepcopy(value)}

def case(i,ratio='2000',action_class='PAY',**kw):
    c={'case_id':f'case-{i:02}','intent':f'intent-{i:02}','revision':'1',
       'scope':copy.deepcopy(S),'partition':'main','payer':'payer','stage':'pay',
       'currency':'CNY','ratio':ratio,'action_class':action_class,'event_at':'60','known_at':'70','label':'CONFIRMED_GOOD'}
    c.update(kw);return c

def bundle(cases=None,now=100):
    E=Identity('source',17);H=Identity('holder',18);G=Identity('gateway',19);X=Identity('executor',20)
    C=Identity('finance',21)
    pol=rr('POLICY',{'profile':'PAY-1','schema_version':'pay1-payload-v1','verifier_version':'pay1-verifier-v1',
       'policy_revision':'1','gateway':G.name,'gateway_kid':G.kid,'executor':X.name,
       'executor_kid':X.kid,'source':E.name,'readers':sortset([E.name,H.name,G.name,X.name,C.name]),
       'tool':'pay-sim','tool_version':'1','destination':'pay-sim-dest','currency':'CNY',
       'method':'order-match-v1','risk_method':'history-int-v2','partition':'main','count_cap':'32',
       'iat':'10','exp':'2000'})
    task=rr('PAY_TASK',{'task_id':sid(1),'task_revision':'1','principal':'payer','holder':H.name,
        'holder_kid':H.kid,'order_id':'ord','stage':'pay','payer':'payer','allowed_payees':['payee'],
        'max_amount_minor':'10000','executor':X.name,'destination':'pay-sim-dest',
        'policy_ref':rec_ref(pol),'iat':'10','exp':'300'})
    action={'scope':copy.deepcopy(S),'operation_id':sid(2),'principal':'payer',
            'holder':H.name,'holder_kid':H.kid,'executor':X.name,'tool':'pay-sim','tool_version':'1',
            'destination':'pay-sim-dest','payload':{'order_id':'ord','stage':'pay','payer':'payer',
                       'payee':'payee','amount_minor':'2000','currency':'CNY','purpose':'order-settlement'}}
    hist=rr('PAY_HISTORY',{'partition':'main','publication_revision':'1','feature_schema':'ratio-int-v1',
        'cases':sortset(cases if cases is not None else [case(1,'2000'),case(2,'1800'),case(3,'2300')]),
        'iat':'90','exp':'1200'})
    evidence={'order_id':'ord','stage':'pay','order_revision':'1','payer':'payer','payee':'payee',
         'amount_minor':'2000','currency':'CNY','accepted_goods':True,'unsettled':True,
         'beneficiary_active':True,'observed_at':'80'}
    header={'proto':'ZJJ-AAP','version':'2.5','profile':'PAY-1','alg':'Ed25519',
            'type':'Evidence','issuer':E.name,'kid':E.kid}
    body={'id':sid(3),'scope':copy.deepcopy(S),'iat':'90','exp':'400','aud':sortset([G.name,X.name,C.name]),
          'refs':[],'deps':[],'payload':evidence}
    sig=b64(E.key.sign(canonical(['ZJJ-SIG-v1',header,body])))
    legacy={'protected':header,'body':body,'sig':sig}
    ev=rr('PAY_EVIDENCE',{'source_version':'2.5','source_profile':'PAY-1','source_type':'Evidence',
        'source_ref':digest(['ZJJ-OBJ-v1',header,body]),'source_envelope':legacy})
    return {'scope':copy.deepcopy(S),'action':action,'policy_record':pol,
          'task_record':task,'history_record':hist,'evidence_record':ev,
          'source_public_key':E.pub,'source_subject':E.name,'cutoff':now,
          'policy_rev':1,'task_rev':1,'order_rev':1,'history_rev':1,'witness_authenticated':True}


def resign_source(b):
    signer=Identity('source',17);env=b['evidence_record']['value']['source_envelope']
    env['sig']=b64(signer.key.sign(canonical(['ZJJ-SIG-v1',env['protected'],env['body']])))
    b['evidence_record']['value']['source_ref']=digest(['ZJJ-OBJ-v1',env['protected'],env['body']])

def run(b,claimed=None):
    if claimed is not None:b['claimed_assessment']=claimed
    return verify_pay_authoritative(**b)

class HistoryTests(unittest.TestCase):
    def assertReject(self,code,b):
        with self.assertRaises(ProtocolError) as x:run(b)
        self.assertEqual(x.exception.code,code)

    def test_3_pay_clear(self):
        risk,a=run(bundle())
        self.assertEqual((risk.feature,risk.result,risk.required_reviews,risk.support,risk.different),('2000','CLEAR',(),'3','0'))
        self.assertEqual(a['method'],'history-int-v2')
    def test_n2_insufficient(self):
        r,_=run(bundle([case(1),case(2)]));self.assertEqual((r.result,r.required_reviews),('INSUFFICIENT',('LOW_EVIDENCE',)))
    def test_n5_d4_flag(self):
        r,_=run(bundle([case(i,action_class=('HOLD' if i<=4 else 'PAY')) for i in range(1,6)]))
        self.assertEqual((r.result,r.different,r.support,r.required_reviews),('FLAG','4','5',('ANOMALY',)))
    def test_n5_d3_clear(self):
        r,_=run(bundle([case(i,action_class=('HOLD' if i<=3 else 'PAY')) for i in range(1,6)]))
        self.assertEqual((r.result,r.different),('CLEAR','3'))
    def test_n3_d2_clear(self):
        r,_=run(bundle([case(i,action_class=('HOLD' if i<=2 else 'PAY')) for i in range(1,4)]))
        self.assertEqual(r.result,'CLEAR')
    def test_n3_d3_flag(self):
        r,_=run(bundle([case(i,action_class='HOLD') for i in range(1,4)]));self.assertEqual(r.result,'FLAG')
    def test_distance_equal_1000_included(self):
        r,_=run(bundle([case(1,'1000'),case(2,'3000'),case(3,'2000')]));self.assertEqual(r.support,'3')
    def test_distance_1001_excluded(self):
        r,_=run(bundle([case(1,'999'),case(2,'3001'),case(3,'2000')]));self.assertEqual((r.support,r.selected_cases),('1',('case-03',)))
    def test_order_by_distance_then_ascii_case_id(self):
        v=[case(3,'2100'),case(2,'1900'),case(1,'2000'),case(4,'2100'),case(5,'1900'),case(6,'2000')]
        r,_=run(bundle(v));self.assertEqual(r.selected_cases,('case-01','case-06','case-02','case-03','case-04'))
    def test_time_known_at_at_cutoff_included(self):
        b=bundle([case(1,known_at='100'),case(2),case(3)]);b['history_record']['value']['iat']='101'
        # Selection predicate independently handles cutoff equality; publication at t=101
        # cannot be current at t=100, so do not use the authoritative wrapper here.
        r=history_int_v2(b['action'],b['task_record']['value'],b['policy_record']['value'],b['history_record']['value'],'100')
        self.assertEqual(r.support,'3')
    def test_time_known_at_after_cutoff_excluded(self):
        b=bundle([case(1,known_at='101'),case(2),case(3)]);b['history_record']['value']['iat']='102'
        r=history_int_v2(b['action'],b['task_record']['value'],b['policy_record']['value'],b['history_record']['value'],'100')
        self.assertEqual(r.support,'2')
    def test_event_after_cutoff_excluded(self):
        # Publication says known_at>=event_at, so prepare a later publication, then cutoff earlier than event.
        b=bundle([case(1,event_at='101',known_at='101'),case(2),case(3)])
        b['history_record']['value']['iat']='110';b['cutoff']=110
        r,_=run(b);self.assertEqual(r.support,'3')
    def test_different_payer_excluded(self):
        r,_=run(bundle([case(1,payer='other'),case(2),case(3)]));self.assertEqual(r.support,'2')
    def test_different_scope_excluded(self):
        v=copy.deepcopy(S);v['tenant']='another';r,_=run(bundle([case(1,scope=v),case(2),case(3)]));self.assertEqual(r.support,'2')
    def test_different_partition_excluded(self):
        r,_=run(bundle([case(1,partition='another'),case(2),case(3)]));self.assertEqual(r.support,'2')
    def test_case_set_order_required(self):
        b=bundle();b['history_record']['value']['cases'].reverse();self.assertReject('CASES',b)
    def test_duplicate_case_id_reject_before_filter(self):
        z=case(1,partition='other');z2=case(1,partition='third',intent='unique')
        self.assertReject('DUPLICATE_CASE',bundle([z,z2]))
    def test_duplicate_intent_reject_before_filter(self):
        z=case(1,partition='other');z2=case(2,partition='third',intent=z['intent'])
        self.assertReject('DUPLICATE_CASE',bundle([z,z2]))
    def test_unknown_case_field_rejected_even_if_filtered(self):
        z=case(1,partition='other');z['unused']='evil';self.assertReject('CASE_FIELDS',bundle([z]))
    def test_ratio_above_10000_rejected(self):self.assertReject('RATIO',bundle([case(1,'10001')]))
    def test_noncanonical_n_rejected(self):self.assertReject('NUMBER',bundle([case(1,revision='01')]))
    def test_more_than_128_rejected(self):self.assertReject('CASES',bundle([case(i) for i in range(129)]))
    def test_unsigned_claimed_clear_rejected_on_flag(self):
        b=bundle([case(i,action_class='HOLD') for i in range(1,4)]);r,a=run(b)
        bogus=dict(a,result='CLEAR');b['claimed_assessment']=bogus
        self.assertReject('ASSESSMENT_MISMATCH',b)
    def test_claimed_feature_tamper_rejected(self):
        b=bundle();r,a=run(b);b['claimed_assessment']=dict(a,feature='1999')
        self.assertReject('ASSESSMENT_MISMATCH',b)
    def test_claimed_cutoff_tamper_rejected(self):
        b=bundle();r,a=run(b);b['claimed_assessment']=dict(a,cutoff='50')
        self.assertReject('ASSESSMENT_MISMATCH',b)
    def test_assessment_not_valid_without_exact_records(self):
        b=bundle();b['task_record']['value']['wrong']='1';self.assertReject('FIELDS',b)
    def test_known_false_hard_reject(self):
        for f in ('accepted_goods','unsettled','beneficiary_active'):
            b=bundle();b['evidence_record']['value']['source_envelope']['body']['payload'][f]=False
            resign_source(b);self.assertReject('CLAIM_FALSE',b)
    def test_bad_signed_source(self):
        b=bundle();b['evidence_record']['value']['source_envelope']['sig']=b64(bytes(64))
        self.assertReject('SIGNATURE_ENCODING',b)
    def test_wrong_source_version_rejected(self):
        b=bundle();b['evidence_record']['value']['source_version']='2.6';self.assertReject('SOURCE_TYPE',b)
    def test_wrong_source_ref_rejected(self):
        b=bundle();b['evidence_record']['value']['source_ref']=b64(bytes(32));self.assertReject('SOURCE_REF',b)
    def test_expired_history_rejected(self):
        b=bundle();b['history_record']['value']['exp']='99';self.assertReject('EXPIRED',b)
    def test_untrusted_publish_rejected(self):
        b=bundle();b['witness_authenticated']=False;self.assertReject('AUTHORITY_UNKNOWN',b)
    def test_stale_history_revision(self):
        b=bundle();b['history_rev']=2;self.assertReject('STALE',b)
    def test_policy_binding_reject(self):
        b=bundle();b['task_record']['value']['policy_ref']=b64(bytes(32));self.assertReject('POLICY_BINDING',b)
    def test_amount_over_cap(self):
        b=bundle();b['action']['payload']['amount_minor']='10001'
        b['evidence_record']['value']['source_envelope']['body']['payload']['amount_minor']='10001'
        resign_source(b);self.assertReject('TASK_BINDING',b)
    def test_payee_outside_allowlist(self):
        b=bundle();b['action']['payload']['payee']='outsider';self.assertReject('CLAIM_FALSE',b)
    def test_action_unknown_field(self):
        b=bundle();b['action']['debug']=True;self.assertReject('ACTION_FIELDS',b)
    def test_big_integer_feature_precise(self):
        b=bundle();N='9223372036854775807';b['action']['payload']['amount_minor']=N
        b['task_record']['value']['max_amount_minor']=N;b['evidence_record']['value']['source_envelope']['body']['payload']['amount_minor']=N
        # regenerate source signature and ref with public fixture private key
        signer=Identity('source',17);env=b['evidence_record']['value']['source_envelope']
        env['sig']=b64(signer.key.sign(canonical(['ZJJ-SIG-v1',env['protected'],env['body']])))
        b['evidence_record']['value']['source_ref']=digest(['ZJJ-OBJ-v1',env['protected'],env['body']])
        r,_=run(b);self.assertEqual((r.feature,r.result),('10000','INSUFFICIENT'))

    def test_reader_whitelist_must_include_fixed_sources(self):
        b=bundle();b['policy_record']['value']['readers'].remove('source')
        self.assertReject('READERS',b)
    def test_history_known_after_publication_rejected(self):
        b=bundle([case(1,known_at='101'),case(2),case(3)])
        self.assertReject('HISTORY_TIME',b)
    def test_wrong_record_kind_rejected(self):
        b=bundle();b['history_record']['kind']='PAY_EVIDENCE'
        self.assertReject('OBJECT_KIND',b)
    def test_v25_signature_tamper_even_with_recomputed_ref(self):
        b=bundle();env=b['evidence_record']['value']['source_envelope']
        env['body']['payload']['amount_minor']='2001'
        b['evidence_record']['value']['source_ref']=digest(['ZJJ-OBJ-v1',env['protected'],env['body']])
        self.assertReject('BAD_SIGNATURE',b)
    def test_seeded_differential_oracle_350_trials(self):
        rng=random.Random(20261009)
        for iteration in range(350):
            b=bundle();a=b['action'];t=b['task_record']['value'];pol=b['policy_record']['value']
            amount=rng.randint(1,10000);cap=rng.randint(amount,20000)
            a['payload']['amount_minor']=str(amount);t['max_amount_minor']=str(cap)
            cutoff=100
            scenarios=[]
            for j in range(rng.randint(0,80)):
                c=case(j,ratio=str(rng.randint(0,10000)),action_class=rng.choice(('PAY','HOLD')))
                c['payer']=rng.choice(('payer','unrelated'))
                c['stage']=rng.choice(('pay','another'))
                c['event_at']=str(rng.randint(1,120))
                c['known_at']=str(max(int(c['event_at']),rng.randint(1,120)))
                c['partition']=rng.choice(('main','other'))
                scenarios.append(c)
            b['history_record']['value']['cases']=scenarios
            # Separate oracle: Python integer filtering + full tuple-sort, no reused helper.
            wanted=(amount*10000)//cap
            relevant=[c for c in scenarios if c['payer']=='payer' and c['stage']=='pay' and c['partition']=='main'
                       and int(c['event_at'])<=cutoff and int(c['known_at'])<=cutoff
                       and abs(int(c['ratio'])-wanted)<=1000]
            relevant.sort(key=lambda item:(abs(int(item['ratio'])-wanted),item['case_id']))
            top=relevant[:5];count=len(top);hold=sum(item['action_class']=='HOLD' for item in top)
            expected='INSUFFICIENT' if count<3 else 'FLAG' if hold/count>=0.8 else 'CLEAR'
            got=history_int_v2(a,t,pol,b['history_record']['value'],str(cutoff))
            self.assertEqual((got.feature,list(got.selected_cases),got.support,got.different,got.result),
                             (str(wanted),[item['case_id'] for item in top],str(count),str(hold),expected),
                             f'iteration {iteration}')

    def test_legacy_evidence_rejects_nonempty_payload_refs(self):
        b=bundle();env=b['evidence_record']['value']['source_envelope']
        env['body']['refs']=[digest(['invented-record'])]
        resign_source(b)
        self.assertReject('SOURCE_REFS',b)
    def test_legacy_deps_reject_malformed_key(self):
        b=bundle();env=b['evidence_record']['value']['source_envelope']
        env['body']['deps']=[{'namespace':'TASK','key':['lab','tenant-1','payment','NOT_B16'],
                              'revision':'1','ref':digest(['ref'])}]
        resign_source(b)
        self.assertReject('BASE64',b)
    def test_legacy_deps_accept_typed_payload_shape_not_authority(self):
        b=bundle();env=b['evidence_record']['value']['source_envelope']
        env['body']['deps']=[{'namespace':'ORDER','key':['lab','tenant-1','payment','ord','pay'],
                              'revision':'1','ref':digest(['row-ref'])}]
        resign_source(b)
        self.assertEqual(run(b)[0].result,'CLEAR')

if __name__=='__main__':unittest.main()
