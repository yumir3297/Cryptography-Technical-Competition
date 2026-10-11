"""Trusted fixed-roster signer filtering; bootstrap owns keys, W owns only publics."""
import copy
from jsonschema import Draft202012Validator
from research.reference_executor.wire import require, b64, canonical, keyid, envelope, action_hash
from competition.core.event_clock import require_window
from competition.core.trusted_state import ROLES, TYPES, PROFILE_SCOPES

class ScopedSignerBroker:
    def __init__(self,state,private_actors):
        self.state=state
        self._signers={p:dict(roster) for p,roster in private_actors.items()}
        require(all(a.kid==state.actors[p][alias].kid for p,r in self._signers.items() for alias,a in r.items()),'BROKER_ROSTER')

    def sign(self,profile,alias,unsigned,action):
        require(profile in PROFILE_SCOPES and alias in TYPES,'BROKER_ROLE')
        h=unsigned['protected']; b=unsigned['body']; who=self.state.actors[profile][alias]
        require((h['proto'],h['version'],h['profile'],h['alg'],h['issuer'],h['kid'],b['scope'])==('ZJJ-AAP','2.6',profile,'Ed25519',who.name,who.kid,PROFILE_SCOPES[profile]) and h['type'] in TYPES[alias],'BROKER_BINDING')
        schema=copy.deepcopy(self.state.schemas[profile].defs[h['type']]); schema['required'].remove('sig'); del schema['properties']['sig']
        Draft202012Validator({'$defs':self.state.schemas[profile].defs,**schema}).validate(unsigned)
        payload=b['payload']; ctx=payload.get('ctx')
        if ctx is not None:
            require(ctx['action_hash']==action_hash(profile,action) and all(ctx[k]==action[k] for k in ('scope','operation_id','principal','holder','holder_kid','executor')),'BROKER_ACTION_BINDING')
        else:
            require(payload.get('operation_id')==action['operation_id'] and payload.get('action_hash')==action_hash(profile,action),'BROKER_ACTION_BINDING')
            for field in ('holder','holder_kid'):
                if field in payload:require(payload[field]==action[field],'BROKER_ACTION_BINDING')
        with self.state.tx() as c:
            event=self.state.event(c,profile,action['operation_id'],'AUTHZ_GUARD',h['kid'])
            self.state.credential(c,profile,alias,ROLES[profile][alias],h['type'],action,event)
            # A broker restricts who/what/where may be signed. Core independently
            # decides approval and dependencies; signer output is never an oracle.
            result=copy.deepcopy(unsigned)
            result['sig']=b64(self._signers[profile][alias].key.sign(canonical(['ZJJ-SIG-v1',h,b])))
            self.state.schemas[profile].validate(result,h['type'])
            envelope(result,{who.kid:who},now=event['lo']); require_window(b,event)
            return result
