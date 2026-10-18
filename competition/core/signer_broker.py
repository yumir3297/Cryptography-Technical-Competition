"""Trusted fixed-roster signer filtering; bootstrap owns keys, W owns only publics."""
from competition.support.schema import COMPETITION_PROTO
import copy
import os
from competition.support.wire import digest, strict_verify, raw
from functools import wraps
from jsonschema import Draft202012Validator, ValidationError
from competition.support.wire import ProtocolError
from competition.support.wire import require, b64, canonical, keyid, envelope, action_hash
from competition.core.event_clock import require_window, refresh_event_age
from competition.core.trusted_state import ROLES, TYPES, PROFILE_SCOPES

def _protocol_inputs(fn):
    @wraps(fn)
    def checked(*args,**kwargs):
        try:return fn(*args,**kwargs)
        except (KeyError,TypeError,ValueError,ValidationError) as exc:
            if isinstance(exc,ProtocolError):raise
            raise ProtocolError('BROKER_FIELDS') from exc
    return checked

class ScopedSignerBroker:
    def __init__(self,state,private_actors):
        self.state=state
        self._signers={p:dict(roster) for p,roster in private_actors.items()}
        require(all(a.kid==state.actors[p][alias].kid for p,r in self._signers.items() for alias,a in r.items()),'BROKER_ROSTER')

    @staticmethod
    def request_ref(profile,alias,unsigned,action):
        return digest(['COMP-APP-SIGN-REQUEST-v1',profile,alias,unsigned,action])

    @_protocol_inputs
    def challenge(self,profile,alias,unsigned,action):
        require(profile in self.state.actors and alias in TYPES,'BROKER_ROLE')
        ref=self.request_ref(profile,alias,unsigned,action)
        nonce=b64(os.urandom(32))
        with self.state.tx() as c:
            event=self.state.event(c,profile,action['operation_id'],'AUTHZ_GUARD',ref)
            c.execute('INSERT INTO a_sign_call VALUES(?,?,?,?,?,0)',(nonce,profile,alias,ref,event['lo']+30))
        who=self.state.actors[profile][alias]
        return {'proto':COMPETITION_PROTO,'profile':profile,'scope':PROFILE_SCOPES[profile],
                'alias':alias,'subject':who.name,'kid':who.kid,'request_ref':ref,'nonce':nonce}

    def authenticate(self,c,profile,alias,unsigned,action,proof,event):
        require(type(proof) is dict and set(proof)=={'claim','signature'},'SIGN_CALLER_REQUIRED')
        cl=proof['claim'];who=self.state.actors[profile][alias]
        ref=self.request_ref(profile,alias,unsigned,action)
        require(type(cl) is dict and set(cl)=={'proto','profile','scope','alias','subject','kid','request_ref','nonce'},'SIGN_CALLER_BINDING')
        require((cl['proto'],cl['profile'],cl['scope'],cl['alias'],cl['subject'],cl['kid'],cl['request_ref'])==
                (COMPETITION_PROTO,profile,PROFILE_SCOPES[profile],alias,who.name,who.kid,ref),'SIGN_CALLER_BINDING')
        strict_verify(who.pub,raw(proof['signature'],64),canonical(['COMP-APP-SIGN-CALL-v1',cl]))
        row=c.execute('SELECT * FROM a_sign_call WHERE nonce=?',(cl['nonce'],)).fetchone()
        require(row is not None and row['used']==0,'SIGN_CALLER_REPLAY')
        require((row['profile'],row['alias'],row['request_ref'])==(profile,alias,ref),'SIGN_CALLER_BINDING')
        require_window({'iat':'0','exp':str(row['expires'])},event)
        require(c.execute('UPDATE a_sign_call SET used=1 WHERE nonce=? AND used=0',(cl['nonce'],)).rowcount==1,'SIGN_CALLER_REPLAY')
        return row['expires']

    @_protocol_inputs
    def sign(self,profile,alias,unsigned,action,*,caller_proof=None):
        require(profile in self.state.actors and alias in TYPES,'BROKER_ROLE')
        unsigned=copy.deepcopy(unsigned);action=copy.deepcopy(action)
        h=unsigned['protected']; b=unsigned['body']; who=self.state.actors[profile][alias]
        require((h['proto'],h['version'],h['profile'],h['alg'],h['issuer'],h['kid'],b['scope'])==(COMPETITION_PROTO,'2.6',profile,'Ed25519',who.name,who.kid,PROFILE_SCOPES[profile]) and h['type'] in TYPES[alias],'BROKER_BINDING')
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
            caller_expires=self.authenticate(c,profile,alias,unsigned,action,caller_proof,event)
            self.state.credential(c,profile,alias,ROLES[profile][alias],h['type'],action,event)
            # A broker restricts who/what/where may be signed. Core independently
            # decides approval and dependencies; signer output is never an oracle.
            result=copy.deepcopy(unsigned)
            result['sig']=b64(self._signers[profile][alias].key.sign(canonical(['ZJJ-SIG-v1',h,b])))
            self.state.schemas[profile].validate(result,h['type'])
            envelope(result,{who.kid:who},now=event['lo'],proto=COMPETITION_PROTO); require_window(b,event)
            final=refresh_event_age(event)
            credentials=self.state.credential(c,profile,alias,ROLES[profile][alias],h['type'],action,final)
            final=refresh_event_age(final)
            for value in [b,{'iat':'0','exp':str(caller_expires)}]+[row['record']['value'] for row in credentials]:
                require_window(value,final)
            return result
