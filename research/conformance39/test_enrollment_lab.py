import copy, tempfile, unittest
from pathlib import Path
from research.conformance39.enrollment_lab import EnrollmentLab
from research.reference_executor.wire import Identity,ProtocolError,b64

class EnrollmentProofTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.db=Path(self.tmp.name)/'enrollment.sqlite'
  self.lab=EnrollmentLab(self.db);self.user=Identity('fixture-holder',57)
  self.pending=self.lab.begin(self.user.name,b64(self.user.pub),['IssueRequest','CommitProof'])
  self.proof=self.lab.possession(self.user,self.pending)
 def rejected(self,proof,code=None):
  with self.assertRaises(ProtocolError) as m:self.lab.register(proof)
  if code:self.assertEqual(m.exception.code,code)
  self.assertEqual(self.lab.snapshot()['grants'],0)
 def test_exact_possession_registers_one_key_no_business_role(self):
  grant=self.lab.register(self.proof)
  self.assertEqual(grant['kind'],'KEY_GRANT')
  self.assertEqual(grant['value']['purposes'],['CommitProof','IssueRequest'])
  self.assertEqual(self.lab.snapshot(),{'grants':1,'consumed':1,'audit':1})
 def test_identical_original_proof_replay_returns_historical_grant(self):
  one=self.lab.register(self.proof);again=self.lab.register(self.proof,now=250)
  self.assertEqual(one,again);self.assertEqual(self.lab.snapshot()['grants'],1)
 def test_modified_scope_rejected(self):
  bad=copy.deepcopy(self.proof);bad['tuple']['scope']['tenant']='other'
  self.rejected(bad,'TUPLE_BINDING')
 def test_modified_purposes_rejected(self):
  bad=copy.deepcopy(self.proof);bad['tuple']['purposes']=['CONTROL']
  self.rejected(bad,'TUPLE_BINDING')
 def test_modified_exp_rejected(self):
  bad=copy.deepcopy(self.proof);bad['exp']='138'
  self.rejected(bad,'BAD_SIGNATURE')
 def test_modified_root_rejected(self):
  bad=copy.deepcopy(self.proof);bad['tuple']['root_generation']='2'
  self.rejected(bad,'TUPLE_BINDING')
 def test_different_applicant_signature_rejected(self):
  bad=copy.deepcopy(self.proof);other=Identity('other',87)
  bad['signature']=self.lab.possession(other,self.pending)['signature']
  self.rejected(bad,'BAD_SIGNATURE')
 def test_wrong_nonce_rejected(self):
  bad=copy.deepcopy(self.proof);bad['nonce']=b64(bytes(32))
  self.rejected(bad,'NONCE_BINDING')
 def test_too_long_signature_lifetime_rejected(self):
  bad=self.lab.possession(self.user,self.pending,iat=100,exp=161)
  self.rejected(bad,'PROOF_TIME')
 def test_late_proof_rejected(self):
  with self.assertRaisesRegex(ProtocolError,'PROOF_TIME'):self.lab.register(self.proof,now=140)
 def test_root_rotation_blocks_unconsumed_proof(self):
  self.lab.rotate_root();self.rejected(self.proof,'ROOT_GENERATION')
 def test_nonce_proof_replacement_after_first_accept_rejected(self):
  self.lab.register(self.proof)
  wrong=copy.deepcopy(self.proof);wrong['iat']='103'
  wrong['signature']=self.lab.possession(self.user,self.pending,iat=103,exp=140)['signature']
  with self.assertRaisesRegex(ProtocolError,'REPLAY'):self.lab.register(wrong,now=104)
  self.assertEqual(self.lab.snapshot()['grants'],1)
 def test_restart_keeps_key_and_nonce_consumed(self):
  grant=self.lab.register(self.proof)
  recovered=EnrollmentLab(self.db)
  self.assertEqual(recovered.register(self.proof,now=250),grant)
  self.assertEqual(recovered.snapshot(),{'grants':1,'consumed':1,'audit':1})
