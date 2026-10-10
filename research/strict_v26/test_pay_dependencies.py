"""Independent dependency closure and active-grant regression tests."""
import copy, unittest
from research.reference_executor.wire import Identity,ProtocolError,sortset,sid,b64,digest,envelope,rec_ref,action_hash
from .test_pay_history import bundle,rr
from .pay_dependencies import TrustedStore,required_pay_deps,verify_claimed_dependencies

ACTORS={'H':('holder',18,'HOLDER',['IssueRequest','ChallengeRequest','CommitProof','StatusQuery']),
 'G':('gateway',19,'ISSUER',['Permit','Result']),
 'X':('executor',20,'EXECUTOR',['Acceptance','Challenge','Result']),
 'U':('finance',21,'FINANCE',['Authorization']),
 'E':('source',17,'SOURCE',['SOURCE']),
 'V':('reviewer',22,'ANOMALY',['Review'])}

def setup(needs_review=False):
    b=bundle();a=b['action'];scope=b['scope'];prefix=[scope['domain'],scope['tenant'],scope['scenario']]
    store=TrustedStore(scope);store.publish_record('POLICY',prefix,1,b['policy_record'],'POLICY')
    store.publish_record('TASK',prefix+[b['task_record']['value']['task_id']],1,b['task_record'],'PAY_TASK')
    store.publish_record('ORDER',prefix+['ord','pay'],1,b['evidence_record'],'PAY_EVIDENCE')
    store.publish_record('EXPERIENCE',prefix+['main'],1,b['history_record'],'PAY_HISTORY')
    store.publish_state('BEHAVIOR',prefix+['payer'],1,{'accepted_count':'0','count_cap':'32','inflight':[]})
    actors={k:Identity(name,seed) for k,(name,seed,_,_) in ACTORS.items()}
    for k,(name,seed,role,purposes) in ACTORS.items():
        who=actors[k]
        kv={'subject':name,'public_key':b64(who.pub),'kid':who.kid,'epoch':'1',
            'purposes':sortset(purposes),'iat':'10','exp':'2000','root_generation':'1',
            'enrollment_ref':digest(['enroll',name])}
        rv={'subject':name,'role':role,'epoch':'1','iat':'10','exp':'2000',
            'tool_set':['pay-sim'],'destination_set':['pay-sim-dest'],'scope_set':[scope],
            'constraints':{'payer_set':['payer'],'max_amount_minor':'100000'}}
        store.publish_record('KEY',[who.kid],1,rr('KEY_GRANT',kv),'KEY_GRANT')
        store.publish_record('ROLE',prefix+[name,role],1,rr('ROLE_GRANT',rv),'ROLE_GRANT')
    signers={k:(v.name,v.kid) for k,v in actors.items()}
    return b,store,actors,signers

class RequiredDepTests(unittest.TestCase):
    def derived(self,store,b,signers,review=False):
        return required_pay_deps(store,b['action'],b['task_record']['value']['task_id'],signers,review,100)
    def assertReject(self,code,fn,*args):
        with self.assertRaises(ProtocolError) as ctx:fn(*args)
        self.assertEqual(ctx.exception.code,code)
    def test_base_closure_exact_namespaces(self):
        b,s,ids,sg=setup();d=self.derived(s,b,sg)
        self.assertEqual(len(d),15)
        self.assertEqual({x['namespace'] for x in d},{'POLICY','TASK','ORDER','EXPERIENCE','BEHAVIOR','KEY','ROLE'})
        self.assertTrue(verify_claimed_dependencies(copy.deepcopy(d),d))
    def test_required_review_adds_independent_grants(self):
        b,s,ids,sg=setup(True);d=self.derived(s,b,sg,True)
        self.assertEqual(len(d),17)
        self.assertTrue(any(x['key']==[ids['V'].kid] for x in d))
    def test_resigned_permit_missing_dependency_rejected(self):
        b,s,ids,sg=setup();d=self.derived(s,b,sg)
        omitted=copy.deepcopy(d[1:]);self.assertReject('DEP_CONFLICT',verify_claimed_dependencies,omitted,d)
        # A genuine G signature on a shortened list is not an authority guarantee.
        ar=digest(['authorization-ref']);ctx={
            'scope':s.scope,'operation_id':b['action']['operation_id'],
            'principal':'payer','holder':'holder','holder_kid':ids['H'].kid,
            'executor':'executor','action_hash':action_hash('PAY-1',b['action']),
            'policy_ref':rec_ref(b['policy_record']),'basis_ref':digest(['basis'])}
        signed=ids['G'].sign('PAY-1','Permit',s.scope,
               {'ctx':ctx,'review_refs':[],'authorization_ref':ar,
                'max_uses':'1','dispatch_before':'220'},
               refs=[ar],deps=omitted,aud=['holder','executor'],at=100)
        # This packet really passes v2.6 envelope structural / Ed25519 checks.
        ids['G'].purposes=frozenset(['Permit'])
        self.assertEqual(envelope(signed,{ids['G'].kid:ids['G']},100).name,'gateway')
        self.assertReject('DEP_CONFLICT',verify_claimed_dependencies,signed['body']['deps'],d)
    def test_resigned_permit_extra_dependency_rejected(self):
        b,s,ids,sg=setup();d=self.derived(s,b,sg)
        extra=sortset(d+[{'namespace':'KEY','key':[digest(['other'])],'revision':'1','ref':digest(['other-ref'])}])
        self.assertReject('DEP_CONFLICT',verify_claimed_dependencies,extra,d)
    def test_duplicate_same_key_rejected(self):
        b,s,ids,sg=setup();d=self.derived(s,b,sg)
        self.assertReject('DEP_CONFLICT',verify_claimed_dependencies,sortset(d+[copy.deepcopy(d[0])]),d)
    def test_revision_stale_rejected(self):
        b,s,ids,sg=setup();d=self.derived(s,b,sg)
        s.publish_state('BEHAVIOR',['lab','tenant-1','payment','payer'],2,
                        {'accepted_count':'1','count_cap':'32','inflight':[sid(27)]})
        self.assertReject('DEP_CONFLICT',verify_claimed_dependencies,d,self.derived(s,b,sg))
    def test_reactivate_old_content_does_not_revive_old_ref(self):
        b,s,ids,sg=setup();d=self.derived(s,b,sg);k=['lab','tenant-1','payment','payer']
        origin=copy.deepcopy(s.current('BEHAVIOR',k).value)
        s.publish_state('BEHAVIOR',k,2,{'accepted_count':'1','count_cap':'32','inflight':[]})
        s.publish_state('BEHAVIOR',k,3,origin)
        self.assertReject('DEP_CONFLICT',verify_claimed_dependencies,d,self.derived(s,b,sg))
    def test_known_revoked_role_rejected(self):
        b,s,ids,sg=setup();s.remove('ROLE',['lab','tenant-1','payment','finance','FINANCE'])
        self.assertReject('REVOKED',self.derived,s,b,sg)
    def test_holder_scope_is_bound(self):
        b,s,ids,sg=setup();b['action']['holder']='unregistered'
        self.assertReject('TASK_BINDING',self.derived,s,b,sg)
    def test_gateway_kid_fixed_to_policy(self):
        b,s,ids,sg=setup();alt=Identity('gateway',100)
        sg['G']=('gateway',alt.kid)
        self.assertReject('G_BINDING',self.derived,s,b,sg)
    def test_independent_finance_not_gateway(self):
        b,s,ids,sg=setup();sg['U']=sg['G']
        self.assertReject('SUBJECT_SEPARATION',self.derived,s,b,sg)
    def test_independent_review_not_finance(self):
        b,s,ids,sg=setup();sg['V']=sg['U']
        self.assertReject('SUBJECT_SEPARATION',self.derived,s,b,sg,True)
    def test_key_purpose_restriction(self):
        b,s,ids,sg=setup();path=['lab','tenant-1','payment','payer']
        i=ids['U'];record=rr('KEY_GRANT',{'subject':'finance','public_key':b64(i.pub),'kid':i.kid,
             'epoch':'2','purposes':['Review'],'iat':'10','exp':'2000',
             'root_generation':'1','enrollment_ref':digest(['new-enrollment'])})
        s.publish_record('KEY',[i.kid],2,record,'KEY_GRANT')
        self.assertReject('NO_ROLE',self.derived,s,b,sg)
    def test_missing_role_row_cannot_be_filled_by_client(self):
        b,s,ids,sg=setup();s._rows.pop(('ROLE',('lab','tenant-1','payment','finance','FINANCE')))
        self.assertReject('STATE_UNAVAILABLE',self.derived,s,b,sg)

    def test_revoked_key_cannot_be_reactivated(self):
        b,s,ids,sg=setup()
        original=s.current('KEY',[ids['U'].kid]).record
        s.remove('KEY',[ids['U'].kid])
        updated=copy.deepcopy(original);updated['value']['epoch']='3'
        self.assertReject('REVOKED_KEY_TOMBSTONE',s.publish_record,'KEY',[ids['U'].kid],3,updated,'KEY_GRANT')
    def test_published_policy_row_revision_must_match(self):
        b,s,ids,sg=setup()
        newer=copy.deepcopy(b['policy_record']);newer['value']['policy_revision']='9'
        self.assertReject('ROW_VERSION',s.publish_record,'POLICY',['lab','tenant-1','payment'],2,newer,'POLICY')
    def test_published_history_row_revision_must_match(self):
        b,s,ids,sg=setup()
        newer=copy.deepcopy(b['history_record']);newer['value']['publication_revision']='1'
        self.assertReject('ROW_VERSION',s.publish_record,'EXPERIENCE',['lab','tenant-1','payment','main'],2,newer,'PAY_HISTORY')

if __name__=='__main__':unittest.main()
