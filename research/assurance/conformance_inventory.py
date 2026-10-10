"""Inventory 39 existing semantic cases without inventing execution evidence.

Run from repository root: python research/assurance/conformance_inventory.py
"""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
CASES=ROOT/'system_dev/v26/semantic_cases.json'
# Models are intentionally less complete than a semantic protocol executor.
ABSTRACT_RELEVANCE={
    'CORE-01':'Only the authorization/acceptance guard is modeled',
    'CORE-05':'Only a single abstract revision is modeled, not a dependency closure',
    'CORE-07':'Independent U and registered subject separation are modeled as booleans',
    'CORE-12':'Two candidates sharing one intent; no 8-way concurrency or real W transaction',
    'CORE-15':'At-most-one dispatch in abstract transitions; no persistent crash recovery',
    'CORE-16':'Same final fact/settlement once; no Ed25519 verification in abstraction',
    'AUD-02B':'Tool key-epoch change and re-attestation abstractly; no real ledger transfer',
    'AUD-02C':'Loss of ledger continuity freezes recovery; no real durable ledger',
}

def main():
    if not CASES.exists():
        raise SystemExit('Run after merging patch in repository containing system_dev/v26/semantic_cases.json')
    obj=json.loads(CASES.read_text(encoding='utf8'))
    cases=obj['cases']
    if len(cases)!=39:
        raise SystemExit(f'Expected 39 original cases, saw {len(cases)}; re-baseline explicitly.')
    if len({c['id'] for c in cases})!=len(cases):raise SystemExit('Duplicate case IDs')
    if any(c.get('status')!='NOT_RUN' for c in cases):
        raise SystemExit('Source has changed since inventory baseline; inspect real artifacts before reporting')
    result={'contract':obj['contract'],'full_semantic_cases':len(cases),
            'full_semantic_pass':0,'full_semantic_not_run':len(cases),
            'abstract_traceability':{k:v for k,v in ABSTRACT_RELEVANCE.items() if k in {c['id'] for c in cases}},
            'warning':'Abstract relevance is NOT a passed semantic test.'}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result

if __name__=='__main__':main()
