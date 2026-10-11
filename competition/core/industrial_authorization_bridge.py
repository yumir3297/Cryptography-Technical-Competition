"""Read-only authenticated legacy IND rows; common publications use the same W DB."""
import json
from competition.core.trusted_state import TrustedState, PROFILE_SCOPES
from research.phase8.scene_authority import _rowkey
from research.reference_executor.wire import require, raw, canonical, strict_verify, rec_ref, keyid

class IndustrialAuthorizationState(TrustedState):
    def __init__(self, owner):
        self.owner=owner
        super().__init__(owner.path,owner.root_public,{owner.profile:owner.actors},owner.clock)

    def publish(self,*args,**kwargs):
        # Existing authenticated C publication path owns current_row. Do not
        # create a second authoritative object graph in a_current.
        require(False,'USE_EXISTING_C_PUBLICATION')

    def current(self,c,profile,ns,key):
        require(profile==self.owner.profile,'BINDING')
        row=self.owner.current(c,ns,key); record=row['record']
        require((record['profile'],record['scope'],record['version'])==(profile,PROFILE_SCOPES[profile],'2.6'),'STATE_INTEGRITY')
        require(row['ref']==self.row_ref(ns,key,row['revision'],record),'STATE_INTEGRITY')
        if ns in ('KEY','ROLE','POLICY','TASK','PACKAGE','IDENTITY'):
            journal=c.execute("SELECT blob FROM journal WHERE kind='C' AND key=? ORDER BY seq DESC LIMIT 1",(_rowkey(ns,key),)).fetchone()
            require(journal is not None,'STATE_UNAVAILABLE')
            cert=json.loads(journal['blob']); claim=cert['claim']
            strict_verify(self.root_public,raw(cert['sig'],64),canonical(['ZJJ-C-CONTROL-LAB-v1',claim]))
            require(cert['kid']==keyid(self.root_public) and claim=={'scope':PROFILE_SCOPES[profile],'namespace':ns,'key':key,'previous_revision':str(row['revision']-1),'record':record,'active':True},'STATE_INTEGRITY')
            row={**row,'certificate':cert}
            if ns=='KEY':
                grant=c.execute('SELECT grant FROM verified_enrollment WHERE kid=?',(record['value']['kid'],)).fetchone()
                require(grant is not None and json.loads(grant['grant'])==record,'POP_REQUIRED')
        return row
