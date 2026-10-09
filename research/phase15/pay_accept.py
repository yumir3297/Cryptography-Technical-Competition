"""Phase15 PAY-1 verifier-only acceptance experiment.

External proposal -> W PREPARE (read-only reservation) -> external X signature
-> W FINALIZE. No signer or SignedPayFlow instance enters W. The signed
C registry and serialized W account are authoritative in this lab.

This is deliberately NOT complete RequiredDeps reconstruction, real payment
execution or official 39-case conformance. C/E roots are fixture-governed.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from research.phase12.authority import HardenedPayW
from research.phase5.durable_w import _json, archive_verify, archive_verify_reply
from research.phase4.flow import check_record_contract
from research.phase11.trusted_clock import checked_clock, consume_clock
from research.strict_v26.pay_dependencies import TrustedStore, required_pay_deps
from research.strict_v26.pay_history import verify_pay_authoritative
from research.reference_executor.wire import (ProtocolError, require, raw, keyid, envelope, number,
    msgref, rec_ref, canonical, digest, sortset, b64, strict_verify)
from research.strict_v26.upstream_schema import UpstreamSchema
from research.phase11.run_phase11 import ROOT


@dataclass(frozen=True)
class PublicPayActor:
    name: str
    pub: bytes
    kid: str
    purposes: frozenset

    @classmethod
    def from_identity(cls, actor):
        return cls(actor.name, bytes(actor.pub), actor.kid, frozenset(actor.purposes))


class VerifierOnlyPayW(HardenedPayW):
    def __init__(self, db_path, root_pub, *, ledger, actors):
        require(type(root_pub) is bytes and len(root_pub)==32, 'ROOT_PUBLIC')
        require(set(actors)>=set(('H','G','X','U','E','V')), 'ACTOR_SET')
        self.public_actors={k:PublicPayActor.from_identity(v) for k,v in actors.items()}
        require(all(keyid(v.pub)==v.kid for v in self.public_actors.values()), 'ACTOR_KEY')
        self.keyring={v.kid:v for v in self.public_actors.values()}
        super().__init__(db_path,root_pub,ledger=ledger)
        with self._read() as c:
            c.executescript("""CREATE TABLE IF NOT EXISTS p15_pending_pay(
                ticket TEXT PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE,
                bundle TEXT NOT NULL, intent TEXT NOT NULL,
                nonce TEXT NOT NULL, prepared_at INTEGER NOT NULL,
                account_revision INTEGER NOT NULL, accepted_seq INTEGER NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('PREPARED','DONE')),
                acceptance TEXT NOT NULL DEFAULT '', reply TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS p15_authoritative_sources(
                id INTEGER PRIMARY KEY CHECK(id=1), seq INTEGER NOT NULL,
                certificate TEXT NOT NULL
            );""")

    def accept(self,*args,**kwargs):
        raise ProtocolError('EXTERNAL_X_REQUIRED')

    def publish_source_bundle(self,cert):
        """C-signed immutable source corpus; W never trusts caller-supplied Permit.deps.

        This is a laboratory signed C snapshot, not a real publisher/PoP or KMS.
        Every non-BEHAVIOR row must also match the current signed C registry.
        """
        require(type(cert) is dict and set(cert)=={'claim','signature'},'SOURCE_FIELDS')
        cl=cert['claim']
        require(type(cl) is dict and set(cl)=={'scope','seq','rows'},'SOURCE_FIELDS')
        require(number(cl['seq'],True) and type(cl['rows']) is list
                and 12<=len(cl['rows'])<=64,'SOURCE_FIELDS')
        strict_verify(self.root_pub,raw(cert['signature'],64),
                      canonical(['ZJJ-P15-C-SOURCE-v1',cl]))
        with self._tx() as c:
            old=c.execute('SELECT seq FROM p15_authoritative_sources WHERE id=1').fetchone()
            require(old is None or int(cl['seq'])>old['seq'],'SOURCE_REPLAY')
            seen=set()
            for row in cl['rows']:
                require(type(row) is dict and set(row)==
                        {'namespace','key','revision','ref','value','record'},'SOURCE_FIELDS')
                ns,key=row['namespace'],row['key']
                require(type(ns) is str and type(key) is list and
                        all(type(k) is str for k in key),'SOURCE_FIELDS')
                idx=ns,_json(key)
                require(idx not in seen,'SOURCE_DUPLICATE')
                seen.add(idx)
                if row['record']=={}:
                    require(ns=='BEHAVIOR' and row['ref']==digest(['ZJJ-STATE-v1',ns,key,
                                            str(row['revision']),row['value']]),'SOURCE_REF')
                else:
                    require(rec_ref(row['record'])==row['ref'] and
                            row['record']['scope']==cl['scope'] and
                            row['record']['value']==row['value'],'SOURCE_REF')
                if ns!='BEHAVIOR':
                    c_row=c.execute('SELECT * FROM authority WHERE namespace=? AND dep_key=?',
                                   (ns,_json(key))).fetchone()
                    require(c_row is not None and c_row['active']==1 and
                            c_row['revision']==int(row['revision']) and
                            c_row['ref']==row['ref'],'SOURCE_NOT_CURRENT')
            c.execute('INSERT INTO p15_authoritative_sources(id,seq,certificate) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET seq=excluded.seq,certificate=excluded.certificate',
                      (int(cl['seq']),_json(cert)))
        return True

    def _trusted_deps(self,c,bundle,at):
        src=c.execute('SELECT certificate FROM p15_authoritative_sources WHERE id=1').fetchone()
        require(src is not None,'SOURCES_UNAVAILABLE')
        cert=json.loads(src['certificate']);cl=cert['claim']
        require(cl['scope']==bundle['commit']['scope'],'SOURCE_SCOPE')
        strict_verify(self.root_pub,raw(cert['signature'],64),
                      canonical(['ZJJ-P15-C-SOURCE-v1',cl]))
        store=TrustedStore(cl['scope'])
        for x in cl['rows']:
            store._set(x['namespace'],x['key'],int(x['revision']),x['ref'],x['value'],x['record'] or None)
        commit=bundle['commit'];v=commit['value'];task_id=v['taskflight']['key'][-1]
        docs={x['namespace']:x for x in cl['rows'] if x['namespace'] in
              ('POLICY','TASK','ORDER','EXPERIENCE')}
        require(set(docs)=={'POLICY','TASK','ORDER','EXPERIENCE'},'RISK_SOURCES_MISSING')
        assessment=bundle['assessment'];basis=bundle['basis']
        check_record_contract(assessment,'ASSESSMENT',cl['scope'])
        check_record_contract(basis,'BASIS',cl['scope'])
        gate=UpstreamSchema(ROOT,'PAY-1')
        gate.validate(assessment,'Record_ASSESSMENT')
        gate.validate(basis,'Record_BASIS')
        risk,computed=verify_pay_authoritative(
            scope=cl['scope'],action=v['action'],
            policy_record=docs['POLICY']['record'],
            task_record=docs['TASK']['record'],
            evidence_record=docs['ORDER']['record'],
            history_record=docs['EXPERIENCE']['record'],
            source_public_key=self.public_actors['E'].pub,
            source_subject=self.public_actors['E'].name,
            cutoff=at, policy_rev=int(docs['POLICY']['revision']),
            task_rev=int(docs['TASK']['revision']),
            order_rev=int(docs['ORDER']['revision']),
            history_rev=int(docs['EXPERIENCE']['revision']),
            witness_authenticated=True,
            claimed_assessment=assessment['value'])
        require(assessment['value']==computed,'ASSESSMENT_MISMATCH')
        require(basis['value']['assessment_ref']==rec_ref(assessment) and
                basis['value']['action']==v['action'] and
                v['ctx']['basis_ref']==rec_ref(basis) and
                basis['value']['required_reviews']==list(risk.required_reviews),
                'BASIS_BINDING')
        reviews=bundle['reviews']
        require(len(reviews)==len(risk.required_reviews) and
                sorted(x['body']['payload']['purpose'] for x in reviews)==
                sorted(risk.required_reviews),'REVIEW_REQUIRED')
        signers={k:(a.name,a.kid) for k,a in self.public_actors.items()}
        derived=required_pay_deps(store,v['action'],task_id,signers,bool(risk.required_reviews),at)
        require(derived==v['checked_deps'],'REQUIRED_DEPS_INCOMPLETE')
        return derived

    def _signed(self,env,kind,alias,scope,at):
        who=self.public_actors[alias]
        require(env['protected']['profile']=='PAY-1' and
                env['protected']['type']==kind and
                env['body']['scope']==scope and
                env['protected']['issuer']==who.name, 'MESSAGE_BINDING')
        require(envelope(env,self.keyring,now=at)==who,'MESSAGE_SIGNER')
        UpstreamSchema(ROOT,'PAY-1').validate(env,kind)
        return env['body']['payload']

    @staticmethod
    def _intent(action):
        p=action['payload'];s=action['scope']
        return _json([s['domain'],s['tenant'],s['scenario'],p['payer'],p['order_id'],p['stage']])

    @staticmethod
    def _nonce(bundle):
        ch=bundle['challenge']['body']['payload']
        return _json([ch['nonce'],ch['session_id'],bundle['commit']['value']['action']['operation_id']])

    def _verify_dependencies(self,c,commit,at):
        deps=commit['value']['checked_deps']
        require(type(deps) is list and deps and deps==sortset(deps), 'DEPS_INVALID')
        for d in deps:
            if d['namespace']=='BEHAVIOR':
                require(d['key']==commit['value']['behavior_before']['key'] and
                        d['ref']==commit['value']['behavior_before']['ref'] and
                        d['revision']==commit['value']['behavior_before']['revision'],'BEHAVIOR_DEPS')
                continue
            key=_json(d['key'])
            state=c.execute('SELECT * FROM authority WHERE namespace=? AND dep_key=?',
                            (d['namespace'],key)).fetchone()
            require(state is not None, 'AUTHORITY_MISSING')
            require(state['active']==1, 'REVOKED')
            require(state['revision']==int(d['revision']) and state['ref']==d['ref'],'STALE')
            window=c.execute('SELECT * FROM authority_window WHERE namespace=? AND dep_key=?',
                             (d['namespace'],key)).fetchone()
            require(window is not None, 'AUTHORITY_TIME_UNAVAILABLE')
            require(window['revision']==int(d['revision']) and window['ref']==d['ref'],
                    'AUTHORITY_TIME_UNAVAILABLE')
            require(window['iat']<=at<window['exp'], 'AUTHORITY_EXPIRED')

    def _verify_bundle(self,c,bundle,at):
        require(type(bundle) is dict and set(bundle)==
                {'commit','permit','proof','challenge','challenge_request','authorization',
                 'reviews','assessment','basis'}, 'BUNDLE_FIELDS')
        commit=bundle['commit']
        check_record_contract(commit,'COMMIT',commit['scope'])
        UpstreamSchema(ROOT,'PAY-1').validate(commit,'Record_COMMIT')
        v=commit['value'];ctx=v['ctx'];scope=commit['scope'];action=v['action']
        require(action['scope']==scope and ctx['scope']==scope and
                ctx['operation_id']==action['operation_id'], 'CONTEXT_BINDING')
        require(v['accepted_at']==str(at) and v['trusted_time']=={'lo':str(at),'hi':str(at)},
                'TIME_WITNESS')
        require(v['signing_public_key']==b64(self.public_actors['X'].pub),'X_BINDING')
        proof=self._signed(bundle['proof'],'CommitProof','H',scope,at)
        permit=self._signed(bundle['permit'],'Permit','G',scope,at)
        chal=self._signed(bundle['challenge'],'Challenge','X',scope,at)
        req=self._signed(bundle['challenge_request'],'ChallengeRequest','H',scope,at)
        auth=self._signed(bundle['authorization'],'Authorization','U',scope,at)
        reviews=bundle['reviews']
        require(type(reviews) is list and len(reviews)<=8,'REVIEWS')
        for rev in reviews:
            p=self._signed(rev,'Review','V',scope,at)
            require(p['ctx']==ctx and p['verdict']=='APPROVE','REVIEW_DENIED')
        rr=sortset([msgref(rev) for rev in reviews])
        require(permit['ctx']==ctx and permit['max_uses']=='1' and
                int(permit['dispatch_before'])>at,'PERMIT_BINDING')
        require(auth['ctx']==ctx and auth['verdict']=='APPROVE' and
                auth['review_refs']==rr and permit['authorization_ref']==msgref(bundle['authorization'])
                and permit['review_refs']==rr,'AUTHORIZATION_BINDING')
        require(proof['ctx']==ctx and proof['permit_ref']==msgref(bundle['permit']) and
                proof['challenge_ref']==msgref(bundle['challenge']) and
                proof['nonce']==chal['nonce'] and proof['session_id']==chal['session_id']
                and proof['attempt_id']==req['attempt_id'],'PROOF_BINDING')
        require(v['permit_ref']==msgref(bundle['permit']) and
                v['proof_ref']==msgref(bundle['proof']) and
                v['authorization_ref']==msgref(bundle['authorization']) and
                v['review_refs']==rr and v['dispatch_before']==permit['dispatch_before'],
                'COMMIT_BINDING')
        require(v['checked_deps']==bundle['permit']['body']['deps'],'DEPS_CONFLICT')
        require(v['taskflight']['operation_id']==action['operation_id'],'TASK_BINDING')
        require(v['taskflight']['key'][-1] in (req.get('task_id',''),v['taskflight']['key'][-1]),'TASK_BINDING')
        self._trusted_deps(c,bundle,at)
        self._verify_dependencies(c,commit,at)
        # Issuer KEY and ROLE refs are C-authenticated and bound to the roster.
        for w in v['credential_witnesses']:
            require(w['kid'] in self.keyring and
                    w['public_key']==b64(self.keyring[w['kid']].pub) and
                    w['subject']==self.keyring[w['kid']].name,'CREDENTIAL_BINDING')
            k=c.execute('SELECT * FROM authority WHERE namespace=? AND dep_key=?',
                        ('KEY',_json([w['kid']]))).fetchone()
            r=c.execute('SELECT * FROM authority WHERE namespace=? AND dep_key=?',
                        ('ROLE',_json([scope['domain'],scope['tenant'],scope['scenario'],w['subject'],w['role']]))).fetchone()
            require(k is not None and r is not None and k['active']==1 and r['active']==1 and
                    k['ref']==w['key_grant_ref'] and r['ref']==w['role_grant_ref'] and
                    k['revision']==int(w['key_revision']) and r['revision']==int(w['role_revision']),
                    'CREDENTIAL_STALE')
        a=c.execute('SELECT * FROM account WHERE id=1').fetchone()
        amount=int(action['payload']['amount_minor'])
        res=v['reservation_plan'][0]
        require(amount>0 and
                int(v['accept_seq'])==a['accept_seq']+1 and
                a['accepted_count']<a['count_cap'] and
                a['reserved']+a['spent']+amount<=a['capacity'],'ACCOUNT_LIMIT')
        require(res['amount']==str(amount) and
                res['capacity_before']==str(a['capacity']) and
                res['reserved_before']==str(a['reserved']) and
                res['spent_before']==str(a['spent']) and
                res['reserved_after']==str(a['reserved']+amount) and
                res['spent_after']==str(a['spent']) and
                res['revision_before']==str(a['revision']) and
                res['revision_after']==str(a['revision']+1),'RESOURCE_WITNESS')
        before=v['behavior_before'];after=v['behavior_after']
        require(before['key']==after['key'] and
                int(after['revision'])==int(before['revision'])+1 and
                int(before['row']['accepted_count'])==a['accepted_count'] and
                int(after['row']['accepted_count'])==a['accepted_count']+1 and
                action['operation_id'] in after['row']['inflight'] and
                after['ref']==digest(['ZJJ-STATE-v1','BEHAVIOR',after['key'],
                                     after['revision'],after['row']]),'BEHAVIOR_WITNESS')
        require(c.execute('SELECT 1 FROM flight WHERE task_id=?',
                          (v['taskflight']['key'][-1],)).fetchone() is None,'TASK_BUSY')
        require(c.execute('SELECT 1 FROM accepted WHERE operation_id=? OR intent_key=? OR nonce_key=?',
                          (action['operation_id'],self._intent(action),self._nonce(bundle))).fetchone() is None,
                'REPLAY')
        return a

    def prepare_pay(self,bundle,*,clock):
        v=bundle['commit']['value'];oid=v['action']['operation_id'];scope=bundle['commit']['scope']
        with self._tx() as c:
            lo,hi,seq=checked_clock(c,clock,self.root_pub,'PAY-1',scope,oid,'PREPARE')
            require(lo==hi,'TIME_AMBIGUOUS')
            a=self._verify_bundle(c,bundle,lo)
            ticket=b64(os.urandom(16))
            c.execute('INSERT INTO p15_pending_pay(ticket,operation_id,bundle,intent,nonce,prepared_at,account_revision,accepted_seq,state) VALUES(?,?,?,?,?,?,?,?,?)',
                      (ticket,oid,_json(bundle),self._intent(v['action']),self._nonce(bundle),lo,
                       a['revision'],a['accept_seq'],'PREPARED'))
            consume_clock(c,seq)
        x=self.public_actors['X'];src=v
        payload={'ctx':src['ctx'],'permit_ref':src['permit_ref'],
                 'proof_ref':src['proof_ref'],'authorization_ref':src['authorization_ref'],
                 'review_refs':src['review_refs'],'accept_seq':src['accept_seq'],
                 'accepted_at':src['accepted_at'],'commit_record_ref':rec_ref(bundle['commit']),
                 'dispatch_before':src['dispatch_before']}
        return {'ticket':ticket,'profile':'PAY-1','scope':scope,'x_kid':x.kid,
                'signed_at':lo,'acceptance_payload':payload,
                'refs':sortset([src['permit_ref'],src['proof_ref'],
                                src['authorization_ref']]+src['review_refs']),
                'aud':sortset([self.public_actors[k].name for k in ('H','G','U')]),
                'x_issuer_deps':[d for d in src['checked_deps'] if d['namespace']=='KEY' and d['key']==[x.kid] or
                                 d['namespace']=='ROLE' and d['key'][-2:]==[x.name,'EXECUTOR']],
                'proof_ref':src['proof_ref'],'operation_id':oid,'accept_seq':src['accept_seq'],
                'commit_record_ref':rec_ref(bundle['commit'])}

    def finalize_pay(self,ticket,acceptance,reply,*,clock):
        with self._tx() as c:
            row=c.execute('SELECT * FROM p15_pending_pay WHERE ticket=?',(ticket,)).fetchone()
            require(row is not None,'NO_PREPARE')
            if row['state']=='DONE':
                require(json.loads(row['acceptance'])==acceptance and json.loads(row['reply'])==reply,
                        'REPLAY_CONFLICT')
                old=c.execute('SELECT * FROM accepted WHERE operation_id=?',(row['operation_id'],)).fetchone()
                require(old is not None,'ARCHIVE_MISSING')
                return self._load(old)
            bundle=json.loads(row['bundle']);record=bundle['commit'];v=record['value'];oid=row['operation_id']
            lo,hi,seq=checked_clock(c,clock,self.root_pub,'PAY-1',record['scope'],oid,'FINALIZE')
            require(lo==hi==row['prepared_at'],'TIME_CHANGED')
            self._verify_bundle(c,bundle,lo)
            self._signed(acceptance,'Acceptance','X',record['scope'],lo)
            self._signed(reply,'Result','X',record['scope'],lo)
            expected={'ctx':v['ctx'],'permit_ref':v['permit_ref'],'proof_ref':v['proof_ref'],
                 'authorization_ref':v['authorization_ref'],'review_refs':v['review_refs'],
                 'accept_seq':v['accept_seq'],'accepted_at':v['accepted_at'],
                 'commit_record_ref':rec_ref(record),'dispatch_before':v['dispatch_before']}
            require(acceptance['body']['payload']==expected and
                    acceptance['body']['refs']==sortset([v['permit_ref'],v['proof_ref'],
                                                v['authorization_ref']]+v['review_refs']) and
                    acceptance['body']['aud']==sortset([self.public_actors[k].name for k in ('H','G','U')]),
                    'ACCEPTANCE_BINDING')
            p=reply['body']['payload']
            require(p['operation_id']==oid and p['result']=='ACCEPTED' and p['status']=='ACCEPTED' and
                    p['request_ref']==v['proof_ref'] and p['acceptance_ref']==msgref(acceptance) and
                    p['status_seq']==v['accept_seq'] and
                    reply['body']['refs']==sortset([v['proof_ref'],msgref(acceptance)]),
                    'RESULT_BINDING')
            archive_verify(record,acceptance)
            archive_verify_reply(acceptance,reply,v['signing_public_key'])
            amount=int(v['action']['payload']['amount_minor'])
            require(c.execute('UPDATE account SET reserved=reserved+?,accepted_count=accepted_count+1, revision=revision+1,accept_seq=accept_seq+1 WHERE id=1 AND revision=? AND accept_seq=? AND reserved+spent+?<=capacity AND accepted_count<count_cap',
                     (amount,row['account_revision'],row['accepted_seq'],amount)).rowcount==1,'ACCOUNT_RACE')
            task=v['taskflight']['key'][-1]
            c.execute('INSERT INTO flight(task_id,operation_id) VALUES(?,?)',(task,oid))
            c.execute('''INSERT INTO accepted(operation_id,intent_key,proof_ref,proof_bytes,nonce_key,task_id,amount,seq,state,commit_bytes,acceptance_bytes,reply_bytes,commit_ref,acceptance_ref,reservation_id)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                      (oid,row['intent'],v['proof_ref'],_json(bundle['proof']),row['nonce'],
                       task,amount,int(v['accept_seq']),'ACCEPTED',_json(record),_json(acceptance),
                       _json(reply),rec_ref(record),msgref(acceptance),v['reservation_ids'][0]))
            c.execute('INSERT INTO audit(kind,operation_id,detail) VALUES(?,?,?)',
                      ('ACCEPTED_PHASE15_EXTERNAL_X',oid,_json({'ticket':ticket,'seq':v['accept_seq']})))
            require(c.execute("UPDATE p15_pending_pay SET state='DONE',acceptance=?,reply=? WHERE ticket=? AND state='PREPARED'",
                      (_json(acceptance),_json(reply),ticket)).rowcount==1,'TICKET_RACE')
            consume_clock(c,seq)
            saved=c.execute('SELECT * FROM accepted WHERE operation_id=?',(oid,)).fetchone()
            out=self._load(saved)
            out['idempotent']=False
            return out
