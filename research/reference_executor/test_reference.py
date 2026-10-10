"""Real signed-envelope, in-memory W reference-slice regression tests.

Do NOT map any of these to full upstream semantic PASS: no official profile
schemas, ledger durability, real authenticated W/C service, or full PAY algorithm.
"""
import copy, json, threading, unittest
from .wire import (ProtocolError, Identity, canonical,load_canonical,raw,b64,strict_verify,
                   point_decode,good_point,sid,digest,rec_ref,msgref,action_hash,envelope)
from .engine import ReferenceW

PAY={'order_id':'ord1','stage':'initial','payer':'payer1','payee':'payee1','amount_minor':'1000','currency':'CNY','purpose':'order-settlement'}
IND={'line_id':'linea','unit_id':'unit1','station_id':'station1','inspection_cycle':'1','phase':'INITIAL','route':'RELEASE'}
MED={'synthetic_patient_id':'patient1','encounter_id':'visit1','order_group_id':sid(44),'phase':'SUBMIT','template_id':'DEMO-ORDER-A','record_ref':digest(['evidence']),'destination_system':'med-demo-ledger'}

def sample(profile='PAY-1',risk='CLEAR',label=None):
 w=ReferenceW(profile)
 if profile=='PAY-1':op=w.prepare(PAY,{'risk':risk})
 elif profile=='IND-DEMO-1':
  p=dict(IND)
  if label=='DEMO_UNCERTAIN':p['route']='INSPECT'
  if label=='DEMO_DEFECT':p['route']='QUARANTINE'
  op=w.prepare(p,{'label':label or 'DEMO_NORMAL'})
 else:op=w.prepare(MED,{'available':True,'complete':True,'label':'DEMO_A'})
 return w,op

def authorize(w,op):
 if op.required:w.review(op)
 w.authorize(op);w.issue(op);w.challenge(op)
 return w.make_proof(op)

def accepted(w,op):w.commit(op,authorize(w,op));return op

def started(w,op):accepted(w,op);w.claim(op);return op

class WireTests(unittest.TestCase):
 def assertCode(self,code,fun,*args,**kw):
  with self.assertRaises(ProtocolError) as ctx:fun(*args,**kw)
  self.assertEqual(ctx.exception.code,code)
 def test_canonical_roundtrip(self):
  o={'z':['你好','😊'],'a':False}
  self.assertEqual(load_canonical(canonical(o)),o)
 def test_reject_whitespace_raw(self):self.assertCode('NONCANONICAL',load_canonical,b' {"a":true}')
 def test_reject_duplicate_raw(self):self.assertCode('DUPLICATE_KEY',load_canonical,b'{"a":true,"a":false}')
 def test_reject_number_raw(self):self.assertCode('WIRE_TYPE',load_canonical,b'{"a":1}')
 def test_reject_nonascii_object_key(self):self.assertCode('KEY_ENCODING',canonical,{'键':True})
 def test_reject_surrogate(self):self.assertCode('UNICODE',canonical,{'a':'\ud800'})
 def test_b64_wrong_width(self):self.assertCode('BASE64',raw,b64(b'abc'),32)
 def test_strict_point_identity_rejection(self):self.assertFalse(good_point(b'\x01'+b'\0'*31))
 def test_strict_point_noncanonical_rejection(self):self.assertIsNone(point_decode((2**255-19).to_bytes(32,'little')))
 def test_strict_signature_and_tamper(self):
  k=Identity('alice',22,purposes=['Review']);sig=k.key.sign(b'hello')
  strict_verify(k.pub,sig,b'hello');self.assertCode('BAD_SIGNATURE',strict_verify,k.pub,sig,b'bye')
 def test_reject_signature_bad_R(self):
  k=Identity('alice',23,purposes=['Review']);sg=k.key.sign(b'm')
  self.assertCode('SIGNATURE_ENCODING',strict_verify,k.pub,b'\x01'+b'\0'*31+sg[32:],b'm')
 def test_reject_signature_noncanonical_S(self):
  k=Identity('alice',24,purposes=['Review']);sg=k.key.sign(b'm');from .wire import L
  self.assertCode('SIGNATURE_ENCODING',strict_verify,k.pub,sg[:32]+L.to_bytes(32,'little'),b'm')
 def test_envelope_reject_cross_profile(self):
  w,op=sample();r=w.idents['V'].sign('PAY-1','Review',w.scope,{'ctx':op.ctx,'purpose':'ANOMALY','verdict':'APPROVE','reason':'ok'},aud=['fixture-h'])
  r['protected']['profile']='MED-DEMO-1';self.assertCode('WRONG_SCOPE',envelope,r,w.keys,100)
 def test_envelope_invalid_sig(self):
  w,op=sample();r=w.review(op);r['body']['payload']['reason']='edited'
  self.assertCode('BAD_SIGNATURE',envelope,r,w.keys,100)
 def test_record_profile_domain_separation(self):
  o={'version':'2.6','profile':'PAY-1','kind':'POLICY','scope':{'domain':'d','tenant':'t','scenario':'payment'},'value':{'v':'1'}}
  p=copy.deepcopy(o);p['profile']='MED-DEMO-1'
  self.assertNotEqual(rec_ref(o),rec_ref(p))
 def test_action_hash_profile_domain_separation(self):
  w,op=sample();self.assertNotEqual(action_hash('PAY-1',op.action),action_hash('IND-DEMO-1',op.action))
 def test_invalid_refs_not_silent(self):
  w,op=sample();r=w.review(op);r['body']['refs']=[digest(['extra'])]
  self.assertCode('REFS',envelope,r,w.keys,100)
 def test_wrong_message_purpose(self):
  w,op=sample();r=w.review(op)
  r['protected']['type']='Permit';self.assertCode('LIFETIME',envelope,r,w.keys,100)
 def test_expired_envelope(self):
  w,op=sample();r=w.review(op);self.assertCode('EXPIRED',envelope,r,w.keys,1100)

class FlowTests(unittest.TestCase):
 def assertCode(self,code,fun,*args,**kw):
  with self.assertRaises(ProtocolError) as ctx:fun(*args,**kw)
  self.assertEqual(ctx.exception.code,code)
 def test_pay_clear_complete_chain(self):
  w,op=sample();started(w,op)
  r=w.certify_fact(op,w.tool_fact(op));self.assertEqual(w.receive_final(op,r),'SETTLED')
  self.assertEqual((op.calls,op.settlements,w.spent,w.reserved),(1,1,1,0))
 def test_pay_flag_needs_review(self):
  w,op=sample(risk='ANOMALY');self.assertEqual(op.required,('ANOMALY',));authorize(w,op);w.commit(op)
  self.assertEqual(op.status,'ACCEPTED')
 def test_pay_low_evidence_needs_review(self):
  w,op=sample(risk='LOW_EVIDENCE');self.assertEqual(op.required,('LOW_EVIDENCE',))
 def test_ind_normal_route(self):
  w,op=sample('IND-DEMO-1');self.assertEqual(op.required,());accepted(w,op)
 def test_ind_defect_quarantine(self):
  w,op=sample('IND-DEMO-1',label='DEMO_DEFECT');accepted(w,op)
  self.assertEqual(op.action['payload']['route'],'QUARANTINE')
 def test_ind_defect_wrong_route_fails(self):
  w=ReferenceW('IND-DEMO-1');self.assertCode('CLAIM_FALSE',w.prepare,IND,{'label':'DEMO_DEFECT'})
 def test_ind_uncertain_needs_review(self):
  w,op=sample('IND-DEMO-1',label='DEMO_UNCERTAIN');self.assertEqual(op.required,('QUALITY_REVIEW',));accepted(w,op)
 def test_med_must_review(self):
  w,op=sample('MED-DEMO-1');self.assertEqual(op.required,('CLINICAL_REVIEW',));accepted(w,op)
 def test_med_missing_record_fails(self):
  w=ReferenceW('MED-DEMO-1');self.assertCode('CLAIM_FALSE',w.prepare,MED,{'available':False,'complete':True,'label':'DEMO_A'})
 def test_med_wrong_template_fails(self):
  w=ReferenceW('MED-DEMO-1');p=dict(MED);p['template_id']='DEMO-ORDER-B'
  self.assertCode('CLAIM_FALSE',w.prepare,p,{'available':True,'complete':True,'label':'DEMO_A'})
 def test_no_u_cannot_issue(self):
  w,op=sample();self.assertCode('MISSING_AUTH',w.issue,op)
 def test_no_v_cannot_authorize(self):
  w,op=sample('MED-DEMO-1');self.assertCode('REVIEW_REQUIRED',w.authorize,op)
 def test_deny_blocks_issue(self):
  w,op=sample('MED-DEMO-1');w.review(op,'DENY');w.review(op,'APPROVE');w.authorize(op)
  self.assertCode('REVIEW_DENY',w.issue,op)
 def test_deny_after_issue_blocks_commit(self):
  w,op=sample('MED-DEMO-1');proof=authorize(w,op);w.review(op,'DENY')
  self.assertCode('REVIEW_DENY',w.commit,op,proof)
 def test_stale_snapshot_blocks_issue(self):
  w,op=sample();w.authorize(op)
  w.publish('POLICY',list(w.basekey()),{'revision':'2'})
  self.assertCode('STALE',w.issue,op)
 def test_stale_after_issue_blocks_commit(self):
  w,op=sample();proof=authorize(w,op)
  w.publish('POLICY',list(w.basekey()),{'revision':'2'})
  self.assertCode('STALE',w.commit,op,proof)
 def test_broken_permit_deps_rejected(self):
  w,op=sample();proof=authorize(w,op);p=copy.deepcopy(op.permit)
  p['body']['deps']=[]
  op.permit=p
  self.assertCode('BAD_SIGNATURE',w.commit,op,proof)
 def test_distinct_operation_same_intent_rejected(self):
  w,op=sample();accepted(w,op)
  second=w.prepare(PAY,{'risk':'CLEAR'})
  self.assertCode('DUPLICATE_INTENT',w.commit,second,authorize(w,second))
 def test_replay_proof_rejected(self):
  w,op=sample();proof=authorize(w,op);w.commit(op,proof)
  self.assertCode('REPLAY',w.commit,op,proof)
 def test_no_second_dispatch(self):
  w,op=sample();started(w,op);self.assertCode('NO_REDISPATCH',w.claim,op)
 def test_cancel_only_before_start(self):
  w,op=sample();accepted(w,op);w.cancel_pending(op)
  self.assertEqual((op.status,w.reserved),('FAILED_CONFIRMED',0))
  self.assertCode('CANCEL_FORBIDDEN',w.cancel_pending,op)
 def test_unknown_retains_capacity(self):
  w,op=sample();started(w,op)
  self.assertEqual((op.status,w.reserved),('EFFECT_UNKNOWN',1))
 def test_resource_cap(self):
  w=ReferenceW('PAY-1',cap=1);p1=w.prepare(PAY,{'risk':'CLEAR'});accepted(w,p1)
  p2=dict(PAY);p2['stage']='next';o2=w.prepare(p2,{'risk':'CLEAR'})
  self.assertCode('RESOURCE_LIMIT',w.commit,o2,authorize(w,o2))
 def test_status_does_not_mutate(self):
  w,op=sample();started(w,op)
  before=(op.calls,op.settlements,w.reserved,w.spent)
  self.assertEqual(w.status_query(op),'EFFECT_UNKNOWN')
  self.assertEqual((op.calls,op.settlements,w.reserved,w.spent),before)
 def test_failed_confirmed_does_not_spend(self):
  w,op=sample();started(w,op)
  w.receive_final(op,w.certify_fact(op,w.tool_fact(op,'FAILED_CONFIRMED')))
  self.assertEqual((op.status,op.settlements,w.spent,w.reserved),('FAILED_CONFIRMED',1,0,0))
 def test_recertification_same_fact_same_id(self):
  w,op=sample();started(w,op);f=w.tool_fact(op)
  x=w.certify_fact(op,f);self.assertEqual(w.receive_final(op,x),'SETTLED')
  first=op.finalfact_id;w.now=101;y=w.certify_fact(op,f)
  self.assertNotEqual(rec_ref(x),rec_ref(y));self.assertEqual(w.receive_final(op,y),'EXISTING')
  self.assertEqual((op.finalfact_id,op.settlements),(first,1))
 def test_recertification_after_rotation(self):
  w,op=sample();started(w,op);f=w.tool_fact(op);old=w.certify_fact(op,f)
  w.rotate_tool(111,True);w.now=101
  self.assertCode('TOOL_TRUST',w.receive_final,op,old)
  newer=w.certify_fact(op,f);self.assertEqual(w.receive_final(op,newer),'SETTLED')
  self.assertEqual(op.calls,1)
 def test_noncontinuous_ledger_stays_unknown(self):
  w,op=sample();started(w,op);f=w.tool_fact(op);w.rotate_tool(114,False)
  self.assertCode('LEDGER_UNKNOWN',w.receive_final,op,w.certify_fact(op,f))
  self.assertEqual((op.status,w.reserved),('EFFECT_UNKNOWN',1))
 def test_bad_signed_contradiction_does_not_halt(self):
  w,op=sample();started(w,op);f=w.tool_fact(op);w.receive_final(op,w.certify_fact(op,f))
  bad=w.certify_fact(op,{**f,'effect_id':'changed'});bad['value']['attestation']['sig']='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
  self.assertCode('SIGNATURE_ENCODING',w.receive_final,op,bad)
  self.assertEqual(op.status,'SUCCEEDED')
 def test_trusted_contradiction_halts(self):
  w,op=sample();started(w,op);f=w.tool_fact(op);w.receive_final(op,w.certify_fact(op,f))
  self.assertCode('TRUSTED_CONTRADICTION',w.receive_final,op,w.certify_fact(op,{**f,'effect_id':'different'}))
  self.assertEqual((op.status,op.settlements),('HALTED',1))
 def test_wrong_bound_final_rejected(self):
  w,op=sample();started(w,op);f=w.tool_fact(op);f['dispatch_attempt']=sid(12345)
  self.assertCode('TOOL_BINDING',w.receive_final,op,w.certify_fact(op,f))
  self.assertEqual(op.status,'EFFECT_UNKNOWN')
 def test_zero_effect_from_missing_ledger_not_a_failure(self):
  w,op=sample();started(w,op)
  self.assertEqual(op.status,'EFFECT_UNKNOWN');self.assertEqual(op.settlements,0)
 def test_cross_profile_tool_final_rejected(self):
  w,op=sample();started(w,op)
  v,other=sample('MED-DEMO-1');started(v,other)
  self.assertCode('WRONG_SCOPE',w.receive_final,op,v.certify_fact(other,v.tool_fact(other)))
 def test_status_after_old_challenge_expiry(self):
  w,op=sample();started(w,op);w.now=1000
  self.assertEqual(w.status_query(op),'EFFECT_UNKNOWN')
 def test_deny_after_accept_is_not_retroactive(self):
  w,op=sample('MED-DEMO-1');accepted(w,op);w.review(op,'DENY')
  self.assertEqual(op.status,'ACCEPTED')
 def test_key_revision_after_issue_blocks_commit(self):
  w,op=sample();proof=authorize(w,op)
  h=w.idents['H'];w.publish('KEY',[h.kid],{'subject':h.name,'kid':h.kid,'purposes':['CommitProof']})
  self.assertCode('STALE',w.commit,op,proof)
 def test_final_seq_duplicate_across_operations_rejected(self):
  w=ReferenceW('PAY-1');a=w.prepare(PAY,{'risk':'CLEAR'})
  p=dict(PAY);p['stage']='stage2';b=w.prepare(p,{'risk':'CLEAR'})
  started(w,a);started(w,b)
  fa=w.tool_fact(a);fb=w.tool_fact(b)
  w.receive_final(a,w.certify_fact(a,fa))
  fb['final_seq']=fa['final_seq']
  self.assertCode('DUPLICATE_FINAL_SEQ',w.receive_final,b,w.certify_fact(b,fb))
  self.assertEqual((b.status,b.settlements),('EFFECT_UNKNOWN',0))
 def test_bad_tool_final_expiry_rejected(self):
  w,op=sample();started(w,op);r=w.certify_fact(op,w.tool_fact(op))
  w.now=1000;self.assertCode('EXPIRED',w.receive_final,op,r)
 def test_eight_racing_commits_same_intent(self):
  w=ReferenceW('PAY-1',cap=8)
  ops=[w.prepare(PAY,{'risk':'CLEAR'}) for _ in range(8)]
  proofs=[authorize(w,o) for o in ops]
  successes=[];errors=[]
  def work(o,p):
   try:w.commit(o,p);successes.append(o.action['operation_id'])
   except ProtocolError as e:errors.append(e.code)
  ts=[threading.Thread(target=work,args=(o,p)) for o,p in zip(ops,proofs)]
  for t in ts:t.start()
  for t in ts:t.join()
  self.assertEqual(len(successes),1);self.assertEqual(errors.count('DUPLICATE_INTENT'),7)
 def test_denial_race_linearizable(self):
  w,op=sample('MED-DEMO-1');proof=authorize(w,op)
  with w.lock:w.review(op,'DENY')
  self.assertCode('REVIEW_DENY',w.commit,op,proof)

if __name__=='__main__':unittest.main()
