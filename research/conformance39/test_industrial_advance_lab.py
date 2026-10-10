import copy,tempfile,unittest
from pathlib import Path
from research.conformance39.industrial_advance_lab import IndustrialAdvanceLab
from research.phase8.fixtures import build_scene,prepare_approved
from research.reference_executor.wire import ProtocolError,sid
from research.phase8.scene_authority import _rec

class IndustrialAdvanceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.a,self.action,self.tid,self.sk,self.ev=build_scene(Path(self.tmp.name)/'scene.sqlite','IND-DEMO-1','DEMO_UNCERTAIN')
  self.ext=IndustrialAdvanceLab(self.a)
  self.op=prepare_approved(self.a,self.action,self.tid,self.sk)
  self.a.accept(self.op)
 def test_unknown_attempt_cannot_advance(self):
  self.a.claim(self.op)
  with self.assertRaisesRegex(ProtocolError,'FINAL_MISSING'):self.ext.advance_cycle2(self.op,controller_approved=True)
 def test_controller_required_for_stage_advance(self):
  attempt=self.a.claim(self.op)
  self.assertEqual(self.ext.settle(self.op,self.ext.signed_final(self.op,attempt)),'AWAITING_REINSPECT')
  with self.assertRaisesRegex(ProtocolError,'CONTROLLER_REQUIRED'):self.ext.advance_cycle2(self.op)
 def test_cycle_one_signed_success_allows_exactly_one_advance(self):
  attempt=self.a.claim(self.op)
  self.assertEqual(self.ext.settle(self.op,self.ext.signed_final(self.op,attempt)),'AWAITING_REINSPECT')
  before=self.a.snapshot();self.assertEqual(before['settlements'],1)
  row=self.ext.advance_cycle2(self.op,controller_approved=True)
  self.assertEqual((row['inspection_cycle'],row['phase'],row['state']),('2','REINSPECT','READY'))
  self.assertEqual(row['predecessor_operation_id'],self.action['operation_id'])
  with self.assertRaisesRegex(ProtocolError,'PHASE_GUARD'):self.ext.advance_cycle2(self.op,controller_approved=True)
 def test_bad_tool_signature_cannot_advance_or_release(self):
  attempt=self.a.claim(self.op)
  final=self.ext.signed_final(self.op,attempt);final['value']['effect_id']='forged-effect'
  with self.assertRaisesRegex(ProtocolError,'BAD_SIGNATURE'):self.ext.settle(self.op,final)
  self.assertEqual(self.a.snapshot()['settlements'],0)
  with self.assertRaisesRegex(ProtocolError,'FINAL_MISSING'):self.ext.advance_cycle2(self.op,controller_approved=True)
 def test_wrong_attempt_cannot_advance(self):
  self.a.claim(self.op)
  final=self.ext.signed_final(self.op,sid(999))
  with self.assertRaisesRegex(ProtocolError,'FINAL_BINDING'):self.ext.settle(self.op,final)
 def test_failed_confirmed_cannot_advance(self):
  attempt=self.a.claim(self.op)
  final=self.ext.signed_final(self.op,attempt,outcome='FAILED_CONFIRMED')
  self.assertEqual(self.ext.settle(self.op,final),'STOPPED')
  with self.assertRaisesRegex(ProtocolError,'FIRST_CYCLE_REQUIRED'):self.ext.advance_cycle2(self.op,controller_approved=True)
 def test_identical_final_twice_settles_once(self):
  attempt=self.a.claim(self.op);f=self.ext.signed_final(self.op,attempt)
  self.assertEqual(self.ext.settle(self.op,f),'AWAITING_REINSPECT')
  self.assertEqual(self.ext.settle(self.op,f),'AWAITING_REINSPECT')
  self.assertEqual(self.a.snapshot()['settlements'],1)
 def test_cycle_two_inspect_success_goes_to_manual_hold(self):
  attempt=self.a.claim(self.op)
  self.ext.settle(self.op,self.ext.signed_final(self.op,attempt,seq=1))
  self.ext.advance_cycle2(self.op,controller_approved=True)
  tv=copy.deepcopy(self.a.current_record('TASK',self.a.scope_key()+[self.tid]));tv['value']['task_revision']='2'
  tv['value']['allowed_units'][0]['inspection_cycle']='2';tv['value']['allowed_units'][0]['phase']='REINSPECT'
  self.a.publish('TASK',self.a.scope_key()+[self.tid],tv)
  ev=copy.deepcopy(self.ev['value']['data']);ev['inspection_cycle']='2';ev['phase']='REINSPECT'
  ev['evidence_revision']='2';ev['sampled_at']='99';ev['known_at']='100'
  newe=self.a.sign_evidence(ev)
  self.a.import_evidence(newe,self.sk)
  action=copy.deepcopy(self.action);action['operation_id']=sid(2024)
  action['payload']['inspection_cycle']='2';action['payload']['phase']='REINSPECT'
  op=prepare_approved(self.a,action,self.tid,self.sk)
  self.a.accept(op);attempt2=self.a.claim(op)
  self.assertEqual(self.ext.settle(op,self.ext.signed_final(op,attempt2,seq=2)),'MANUAL_HOLD')
  self.assertEqual(self.a.snapshot()['settlements'],2)
  with self.a.db() as c:
   finalrow=self.a._scene_current(c,self.sk)['record']['value']
   self.assertEqual(finalrow['state'],'MANUAL_HOLD')
   self.assertEqual(finalrow['inspection_cycle'],'2')
