"""Phase 14 verifier-only experimental scene W.
No C/E/X signing key is accepted, retained or constructed by this class.
PREPARE never accepts/reserves resources. FINALIZE validates external X and
atomically commits acceptance/resource/scene/behavior after fresh CAS checks.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from research.phase12.authority import HardenedSceneW
from research.phase8.scene_authority import PROFILES, _rec, _json, _clone
from research.phase11.trusted_clock import checked_clock, consume_clock
from research.reference_executor.wire import ProtocolError, require, b64, keyid, envelope, digest, rec_ref, sortset, sid
from research.strict_v26.upstream_schema import UpstreamSchema
from research.phase11.run_phase11 import ROOT

@dataclass(frozen=True)
class PublicActor:
    name: str
    kid: str
    pub: bytes
    roles: frozenset
    purposes: frozenset

    @classmethod
    def from_identity(cls, v):
        return cls(v.name, v.kid, bytes(v.pub), frozenset(v.roles), frozenset(v.purposes))

class PublicRoot:
    """Public Ed25519 key. It deliberately has no sign method."""
    def __init__(self, key):
        self.key = Ed25519PublicKey.from_public_bytes(key)
    def public_key(self):
        return self.key

class VerifierOnlySceneW(HardenedSceneW):
    def __init__(self, db_path, profile, *, root_public, actors):
        require(profile in PROFILES, 'PROFILE')
        require(type(root_public) is bytes and len(root_public)==32, 'ROOT_PUBLIC')
        require(set(actors)=={'H','G','X','U','V','E'}, 'ACTOR_SET')
        roster={k:PublicActor.from_identity(v) for k,v in actors.items()}
        for actor in roster.values():
            require(keyid(actor.pub)==actor.kid, 'KEY_TRUST')
        super().__init__(db_path,profile,controller=PublicRoot(root_public),actors=roster)
        require(self.root_public==root_public, 'ROOT_PUBLIC')
        with self.db() as c:
            c.executescript("""CREATE TABLE IF NOT EXISTS p14_pending(
                ticket TEXT PRIMARY KEY,operation_id TEXT NOT NULL UNIQUE,
                operation_json TEXT NOT NULL,plan_json TEXT NOT NULL,
                prepare_time INTEGER NOT NULL,state TEXT NOT NULL,
                acceptance_json TEXT NOT NULL DEFAULT '');""")

    def _env(self,*args,**kwargs): raise ProtocolError('EXTERNAL_SIGNER_REQUIRED')
    def certify(self,*args,**kwargs): raise ProtocolError('EXTERNAL_C_REQUIRED')
    def publish(self,*args,**kwargs): raise ProtocolError('EXTERNAL_C_REQUIRED')
    def sign_evidence(self,*args,**kwargs): raise ProtocolError('EXTERNAL_E_REQUIRED')
    def _evidence_signed(self,*args,**kwargs): raise ProtocolError('EXTERNAL_E_REQUIRED')
    def enroll_actor(self,*args,**kwargs): raise ProtocolError('EXTERNAL_POP_REQUIRED')
    def grant(self,*args,**kwargs): raise ProtocolError('EXTERNAL_C_REQUIRED')
    def accept(self,*args,**kwargs): raise ProtocolError('PREPARE_SIGN_FINALIZE_REQUIRED')

    def _plan(self,c,op,at):
        require(op['proof'] is not None and op['permit'] is not None,'MISSING_PROOF')
        require(op['acceptance'] is None and op['commit_record'] is None,'UNTRUSTED_OUTPUT')
        self._verify_signed_chain(c,op,now=at)
        scene=self._fresh(c,op,at)
        a=op['action'];p=a['payload'];dest=a['destination'];task=op['task_id'];oid=a['operation_id']
        intent=_json([self.profile,self.scope,p['line_id'],p['unit_id'],p['inspection_cycle']]
            if self.profile=='IND-DEMO-1' else [self.profile,self.scope,p['synthetic_patient_id'],p['encounter_id']])
        require(c.execute('SELECT 1 FROM accept_intent WHERE intent=? OR operation_id=?',(intent,oid)).fetchone() is None,'DUPLICATE_INTENT')
        require(c.execute('SELECT 1 FROM flight WHERE task_id=?',(task,)).fetchone() is None,'TASK_BUSY')
        res=c.execute('SELECT * FROM resource WHERE destination=?',(dest,)).fetchone()
        cap,reserved,spent,revision=(res['capacity'],res['reserved'],res['spent'],res['revision']) if res else (8,0,0,1)
        require(reserved+spent+1<=cap,'RESOURCE_LIMIT')
        bh=c.execute('SELECT * FROM behavior WHERE principal=?',(a['principal'],)).fetchone()
        require(bh is not None and bh['accepted_count']<bh['count_cap'],'BEHAVIOR_LIMIT')
        bev=self.current(c,'BEHAVIOR',self.scope_key()+[a['principal']])
        require(bev['revision']==bh['revision'] and int(bev['record']['value']['accepted_count'])==bh['accepted_count'],'BEHAVIOR_INTEGRITY')
        before_scene=self._scene_witness(op['scene_key'],scene)
        scene_next=_clone(scene['record']['value']);scene_next.update({'state':'ACCEPTED','operation_id':oid})
        sref=self._state_ref(PROFILES[self.profile][2],op['scene_key'],scene['revision']+1,scene_next)
        after_scene={'namespace':PROFILES[self.profile][2],'key':op['scene_key'],
            'revision':str(scene['revision']+1),'ref':sref,'row':scene_next}
        before_behavior=self._behavior_witness(a['principal'],bev)
        inflight=sortset(json.loads(bh['inflight'])+[oid])
        behavior_next={'accepted_count':str(bh['accepted_count']+1),'count_cap':'32','inflight':inflight}
        bref=self._state_ref('BEHAVIOR',self.scope_key()+[a['principal']],bev['revision']+1,behavior_next)
        after_behavior={'key':self.scope_key()+[a['principal']],'revision':str(bev['revision']+1),'ref':bref,'row':behavior_next}
        seq=c.execute('SELECT COALESCE(MAX(rowid),0)+1 FROM accept_intent').fetchone()[0]
        reservation=sid(800+seq)
        resource_key=(self.scope_key()+['route-capacity',p['line_id'],dest,'unit']
            if self.profile=='IND-DEMO-1' else self.scope_key()+['order-capacity',dest,'order'])
        reservation_plan={'reservation_id':reservation,'key':resource_key,
            'unit':'UNIT' if self.profile=='IND-DEMO-1' else 'ORDER','amount':'1',
            'capacity_before':str(cap),'reserved_before':str(reserved),'spent_before':str(spent),
            'reserved_after':str(reserved+1),'spent_after':str(spent),
            'revision_before':str(revision),'revision_after':str(revision+1)}
        ref=lambda e:digest(['ZJJ-OBJ-v1',e['protected'],e['body']])
        pref=ref(op['permit']);proofref=ref(op['proof']);authref=ref(op['authorization'])
        reviews=sortset([ref(r) for r in op['reviews']])
        value={'ctx':op['ctx'],'action':a,'permit_ref':pref,'proof_ref':proofref,
            'authorization_ref':authref,'review_refs':reviews,'accept_seq':str(seq),
            'accepted_at':str(at),'trusted_time':{'lo':str(at),'hi':str(at)},
            'checked_deps':op['deps'],'reservation_plan':[reservation_plan],
            'reservation_ids':[reservation],'behavior_before':before_behavior,
            'behavior_after':after_behavior,'taskflight':{'key':self.scope_key()+[task],
            'operation_id':oid},'dispatch_before':'220','frozen_tool_request':a,
            'signing_public_key':b64(self.actors['X'].pub),
            'credential_witnesses':self._credential_witnesses(c,op,seq),
            'scene_before':before_scene,'scene_after':after_scene}
        require(len(value)==21,'COMMIT_STRUCTURE')
        commit=_rec(self.profile,'COMMIT',self.scope,value)
        payload={'ctx':op['ctx'],'permit_ref':pref,'proof_ref':proofref,
            'authorization_ref':authref,'review_refs':reviews,'accept_seq':str(seq),
            'accepted_at':str(at),'commit_record_ref':rec_ref(commit),'dispatch_before':'220'}
        freeze={'action':a,'pre_deps':op['deps'],'scene_after_ref':sref,
            'scene_after_revision':scene['revision']+1,'behavior_after':after_behavior,
            'task_id':task,'commit_record':commit}
        journal=c.execute('SELECT COALESCE(MAX(seq),0) FROM journal').fetchone()[0]
        epoch=c.execute('SELECT generation FROM c_root_epoch WHERE id=1').fetchone()[0]
        return {'commit':commit,'payload':payload,'freeze':freeze,'intent':intent,
            'journal':journal,'root_epoch':epoch,'resource_revision':revision,
            'resource_reserved':reserved,'resource_spent':spent,
            'scene_revision':scene['revision'],'behavior_revision':bev['revision']}

    def prepare_accept(self,op,*,clock):
        oid=op['action']['operation_id']
        with self.tx() as c:
            lo,hi,seq=checked_clock(c,clock,self.root_public,self.profile,self.scope,oid,'PREPARE')
            require(lo==hi,'TIME_INTERVAL_AMBIGUOUS')
            plan=self._plan(c,op,lo)
            ticket=b64(os.urandom(16))
            c.execute('INSERT INTO p14_pending(ticket,operation_id,operation_json,plan_json,prepare_time,state) VALUES(?,?,?,?,?,?)',
                (ticket,oid,_json(op),_json(plan),lo,'PREPARED'))
            consume_clock(c,seq)
        return {'ticket':ticket,'profile':self.profile,'scope':self.scope,
            'commit_record':plan['commit'],'acceptance_payload':plan['payload'],
            'refs':sortset([plan['payload']['permit_ref'],plan['payload']['proof_ref'],
                plan['payload']['authorization_ref']]+plan['payload']['review_refs']),
            'aud':[self.actors[a].name for a in ('H','G','U')],
            'signed_at':lo,'x_kid':self.actors['X'].kid}

    def finalize_accept(self,ticket,acceptance,*,clock):
        with self.tx() as c:
            pending=c.execute('SELECT * FROM p14_pending WHERE ticket=?',(ticket,)).fetchone()
            require(pending is not None,'NO_PREPARE')
            if pending['state']=='DONE':
                require(json.loads(pending['acceptance_json'])==acceptance,'REPLAY_CONFLICT')
                return json.loads(pending['acceptance_json'])
            require(pending['state']=='PREPARED','PREPARE_STATE')
            op=json.loads(pending['operation_json']);expected=json.loads(pending['plan_json'])
            oid=op['action']['operation_id']
            lo,hi,seq=checked_clock(c,clock,self.root_public,self.profile,self.scope,oid,'FINALIZE')
            require(lo==hi==pending['prepare_time'],'TIME_CHANGED')
            self._verify_signed_chain(c,op,now=lo)
            who=self.actors['X'];envelope(acceptance,{who.kid:who},now=lo)
            require(acceptance['protected']['type']=='Acceptance' and
                acceptance['protected']['profile']==self.profile and
                acceptance['protected']['issuer']==who.name and
                acceptance['body']['scope']==self.scope,'ACCEPTANCE_BINDING')
            require(acceptance['body']['payload']==expected['payload'] and
                acceptance['body']['refs']==sortset([expected['payload']['permit_ref'],expected['payload']['proof_ref'],
                    expected['payload']['authorization_ref']]+expected['payload']['review_refs']) and
                acceptance['body']['aud']==sortset([self.actors[a].name for a in ('H','G','U')]),'ACCEPTANCE_BINDING')
            UpstreamSchema(ROOT,self.profile).validate(expected['commit'],'Record_COMMIT')
            UpstreamSchema(ROOT,self.profile).validate(acceptance,'Acceptance')
            actual=self._plan(c,op,lo)
            require(actual==expected,'PREPARE_STALE')
            require(c.execute('SELECT generation FROM c_root_epoch WHERE id=1').fetchone()[0]==expected['root_epoch'],'ROOT_CHANGED')
            require(c.execute('SELECT COALESCE(MAX(seq),0) FROM journal').fetchone()[0]==expected['journal'],'CONTROL_CHANGED')
            a=op['action'];dest=a['destination'];scene=expected['commit']['value']['scene_after'];bf=expected['freeze']['behavior_after']
            self._scene_update(c,op['scene_key'],expected['scene_revision'],scene['row'])
            self._behavior_update(c,a['principal'],expected['behavior_revision'],bf['row'])
            inflight=bf['row']['inflight']
            require(c.execute('UPDATE behavior SET accepted_count=accepted_count+1,revision=revision+1,inflight=? WHERE principal=? AND revision=?',
                (_json(inflight),a['principal'],expected['behavior_revision'])).rowcount==1,'BEHAVIOR_RACE')
            c.execute('INSERT OR IGNORE INTO resource(destination) VALUES(?)',(dest,))
            require(c.execute('UPDATE resource SET reserved=reserved+1,revision=revision+1 WHERE destination=? AND revision=? AND reserved=? AND spent=? AND reserved+spent+1<=capacity',
                (dest,expected['resource_revision'],expected['resource_reserved'],expected['resource_spent'])).rowcount==1,'RESOURCE_RACE')
            c.execute('INSERT INTO flight VALUES(?,?)',(op['task_id'],a['operation_id']))
            frozen={**expected['freeze'],'acceptance':acceptance}
            c.execute('INSERT INTO accept_intent(intent,operation_id,scene_namespace,scene_key,accepted_blob) VALUES(?,?,?,?,?)',
                (expected['intent'],a['operation_id'],PROFILES[self.profile][2],_json(op['scene_key']),_json(frozen)))
            c.execute('INSERT INTO journal(kind,key,blob) VALUES(?,?,?)',('ACCEPT',expected['intent'],_json(frozen)))
            c.execute('UPDATE p14_pending SET state=?,acceptance_json=? WHERE ticket=? AND state=?',
                ('DONE',_json(acceptance),ticket,'PREPARED'))
            consume_clock(c,seq)
        return acceptance
