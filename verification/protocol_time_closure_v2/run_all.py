"""Persist candidate wire/crypto checks and finite counterexample evidence."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import importlib.metadata
import io
import json
import platform
import shutil
import subprocess
import sys
import unittest
from codec import enc, parse, b64, candidate_ref, core_ref, fact_id
from observation import ROOT, SCHEMA, Interval, receive
from fixtures import published_fixture
from build_schema import make_schema
from interleavings import run


def main():
    base = Path(__file__).resolve().parent
    out = base/'runs'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out.mkdir(parents=True)
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(base), pattern='test_*.py')
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    (out/'tests.txt').write_text(stream.getvalue(),encoding='utf-8')
    enumeration = run()
    (out/'interleavings.json').write_text(json.dumps(enumeration,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    vectors = []
    for profile in ('PAY-1','IND-DEMO-1','MED-DEMO-1'):
        ctx, _, _, q, package, _, _ = published_fixture(profile)
        verdict = receive(ctx,q,package,Interval(1103,1103))
        parsed = parse(package)
        vectors.append({'profile':profile,'PUBLIC_TEST_KEYS_ONLY':True,
                        'public_test_seeds_hex':{'original':'11'*32,'holder':'22'*32,'observer':'33'*32},
                        'query':parse(q),'package':parsed,'query_wire_base64':b64(q),
                        'package_wire_base64':b64(package),'query_ref':candidate_ref(parse(q)),
                        'observation_ref':candidate_ref(parsed['observation']),
                        'original_acceptance_ref':core_ref(parsed['archive']['original_core']),
                        'fact_id':fact_id(verdict['fact']),
                        'oracle_premises':'Synthetic authenticated history/read/publication inputs; placeholder historical refs are not audited R2 evidence.',
                        'expected_truth_with_test_authority':'T'})
    (out/'vectors.json').write_text(json.dumps(vectors,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    node = shutil.which('node')
    cross = subprocess.run([node,str(base/'check_vectors.mjs'),str(out/'vectors.json')],
                           capture_output=True,text=True,encoding='utf-8') if node else None
    cross_report = json.loads(cross.stdout) if cross and cross.returncode == 0 else {'passed':False,'error':'Node cross-check unavailable or failed'}
    (out/'node_crosscheck.json').write_text(json.dumps(cross_report,indent=2)+'\n',encoding='utf-8')
    original = json.loads((ROOT/'system_dev/v26/semantic_cases.json').read_text(encoding='utf-8'))
    supplemental = json.loads((ROOT/'verification/protocol_time_closure_lab/temporal_cases.json').read_text(encoding='utf-8'))
    status = {s:sum(c['status']==s for c in original['cases']) for s in sorted({c['status'] for c in original['cases']})}
    first = subprocess.run([sys.executable,str(ROOT/'verification/protocol_time_closure_lab/run_all.py')],
                           cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    (out/'first_model_stdout.txt').write_text(first.stdout+first.stderr,encoding='utf-8')
    first_report = json.loads(first.stdout) if first.returncode == 0 else {'passed':False}
    schema_matches = SCHEMA == make_schema()
    passed = (result.wasSuccessful() and result.testsRun >= 33 and enumeration['passed'] and schema_matches and cross_report['passed']
              and len(vectors)==3 and first_report.get('passed') and status=={'NOT_RUN':39}
              and len(supplemental['cases'])==22 and all(c['status']=='NOT_RUN' for c in supplemental['cases']))
    sources = list(base.glob('*.py')) + [base/'schema.json',base/'requirements.txt',base/'README.md',base/'check_vectors.mjs']
    sources += [ROOT/p for p in ('system_dev/v26/01_core_contract.md','system_dev/v26/04_tool_final_recovery.md',
                                'system_dev/v26/05_time_acceptance_recovery_PROPOSED.md',
                                'system_dev/v26/06_time_observation_candidate_contract.md',
                                'system_dev/v26/semantic_cases.json',
                                'verification/protocol_time_closure_lab/model.py',
                                'verification/protocol_time_closure_lab/test_model.py')]
    sources += list((ROOT/'system_dev/v26/contracts').glob('*.schema.json'))
    report = {'contract':'ZJJ-TIME-RESEARCH/0.2','generated_at_utc':datetime.now(timezone.utc).isoformat(),
              'passed':passed,'candidate_tests':{'run':result.testsRun,'failures':len(result.failures),
                                               'errors':len(result.errors),'skipped':len(result.skipped)},
              'schema_regeneration_equal':schema_matches,
              'independent_node_vector_crosscheck':cross_report,
              'finite_exploration':{'states':enumeration['cas_model']['states'],
                                    'transitions':enumeration['cas_model']['transitions'],
                                    'violations':len(enumeration['cas_model']['violations']),
                                    'legacy_counterexample_events':enumeration['legacy_without_CAS']['violations'][0]['trace_length'],
                                    'domain':'See interleavings.json; one historical fact and one server query transaction.'},
              'signed_candidate_vectors':{'profiles':[v['profile'] for v in vectors],
                                           'original_signature_present':False,'original_receipt_exp':'1000',
                                           'current_query_time':'1100','current_observer_public_test_seed':'33'*32},
              'first_model':first_report,'official_39_status':status,'executed_official_cases':0,
              'supplemental_22_status':'NOT_RUN','product_66_executed_here':0,
              'source_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted(sources)},
              'environment':{'python':sys.version,'platform':platform.platform(),
                             'dependencies':{x:importlib.metadata.version(x) for x in ('cryptography','jsonschema')}},
              'limits':['Conditional candidate-rule checks, not official R2 conformance or product implementation.',
                        'Trusted C current authorization intersection and W authenticated history/read/publication are explicit input premises.',
                        'Independent anti-rollback highwater/continuity, real clock, database CAS/durability and historical full-graph audit are not implemented.',
                        'No second implementation, real network, devices, unbounded liveness or complete security proof.']}
    (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if passed:
        (base/'LATEST').write_text(out.name+'\n',encoding='utf-8')
    print(json.dumps({'passed':passed,'candidate_tests':result.testsRun,'states':report['finite_exploration']['states'],
                      'transitions':report['finite_exploration']['transitions'],'violations':report['finite_exploration']['violations'],
                      'first_model_tests':first_report.get('tests'),
                      'results':(out/'results.json').relative_to(ROOT).as_posix()},ensure_ascii=True))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
