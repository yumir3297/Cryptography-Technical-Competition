"""Traceability against 2026-10-07 upstream 39 case IDs; NOT a conformance claim."""
import json
from pathlib import Path

PARTIAL={
 'CORE-01':'signed H/V/U/G/X path only; no official full COMMIT witness',
 'CORE-02':'profile/scope alteration and signature tamper only',
 'CORE-03':'permit dependency equality; not full independently derived RequiredDeps graph',
 'CORE-04':'signed direct-ref mismatch; no full typed graph closure or cycles',
 'CORE-05':'mock authoritative revision invalidation; no range/rollback mechanics',
 'CORE-07':'required independent U signature; separation checks limited to fixture identities',
 'CORE-10':'signature tamper rejection; no persistent Acceptance response recovery',
 'CORE-11':'nonce/proof replay only; no full ID conflict replay cache',
 'CORE-12':'8 Python threads under RLock; not real database serializable transactions',
 'CORE-13':'expiry condition and pre-dispatch guard only',
 'CORE-15':'pending cancel / no redispatch; no crash persistence',
 'CORE-16':'signed mock tool final and contradictory fact; no durable tool effect',
 'CORE-17':'fresh STATUS-only challenge and read-only state; no holder rekey',
 'CORE-18':'single-profile stable intent uniqueness; no v2.5 migration',
 'PAY-01':'trusted fixture risk label CLEAR/ANOMALY/LOW_EVIDENCE; NOT history-int-v2',
 'PAY-04':'amount/format fixed constraints; no 3 certified source facts',
 'IND-01':'3 fixed synthetic label mappings and basic independent review',
 'MED-01':'synthetic review and independent Authorization; no certified clinician role',
 'MED-02':'stable synthetic encounter/group intent; no C-authorized encounter task changes',
 'MED-03':'mock availability/completeness gate; no authenticated source evidence',
 'SC-01':'sample 8-slot cap only; no full TTL/32-count resource model',
 'SC-02':'profile-separated signature and tool final rejection only',
 'AUD-02A':'expired proof guard / current re-attestation; no persistent ledger',
 'AUD-02B':'current key re-attestation same frozen fact; continuity is a boolean fixture',
 'AUD-02C':'ledger-continuity=false blocks settlement; no real ledger transfer proof',
 'AUD-02D':'bad and authentic contradictory signed facts with HALTED; not full archival contradiction evidence',
}
CASE_IDS=([f'CORE-{i:02}' for i in range(1,21)] + [f'PAY-{i:02}' for i in range(1,6)]
          + [f'IND-{i:02}' for i in range(1,5)] + [f'MED-{i:02}' for i in range(1,5)]
          + ['SC-01','SC-02','AUD-02A','AUD-02B','AUD-02C','AUD-02D'])
assert len(CASE_IDS)==39 and len(set(CASE_IDS))==39

def matrix(repo_root):
 path=Path(repo_root)/'system_dev/v26/semantic_cases.json'
 result={'source':str(path),'upstream_schema_found':path.exists(),
         'source_verified':False,'cases':[],
         'official_full_conformance_pass':0,
         'warning':'PARTIAL means only specific sub-properties tested; NOT a full upstream case PASS.'}
 if path.exists():
  original=json.loads(path.read_text(encoding='utf-8'))
  got=[v['id'] for v in original['cases']]
  if got!=CASE_IDS:raise ValueError('Upstream semantic case IDs/order changed: rebaseline manually')
  result['source_verified']=True
 for i in CASE_IDS:
  result['cases'].append({'id':i,'status':'PARTIAL' if i in PARTIAL else 'NOT_RUN',
                         'partial_evidence':PARTIAL.get(i,'Not implemented in the reference slice')})
 result['partial_count']=len(PARTIAL)
 result['not_run_count']=len(CASE_IDS)-len(PARTIAL)
 return result
