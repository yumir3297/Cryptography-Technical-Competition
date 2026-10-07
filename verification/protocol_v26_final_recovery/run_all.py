"""Reproducible bounded A02 recovery verification, without product execution."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
import platform
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from verification.protocol_v26_final_recovery import test_recovery, test_old_gap
from verification.protocol_v26_final_recovery.model import fixture, fact_id, record_ref


def main():
    base = Path(__file__).resolve().parent
    out = base / 'runs' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out.mkdir(parents=True)
    results = {}
    for name, module in [('r1_expected_red', test_old_gap), ('r2_recovery', test_recovery)]:
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(module))
        (out / f'{name}.txt').write_text(stream.getvalue(), encoding='utf-8')
        results[name] = {'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped), 'successful': result.wasSuccessful(), 'failed_test_ids': [t.id() for t, _ in result.failures]}
    samples = []
    for profile in ('PAY-1', 'IND-DEMO-1', 'MED-DEMO-1'):
        ledger, w, t1, t2, k1, k2 = fixture(profile)
        old = ledger.reattest(t1, k1, 101)
        w.rotate(t2, continuity_verified=True)
        fresh = ledger.reattest(t2, k2, 1002)
        first = w.receive(fresh, 1002)
        repeat = w.receive(ledger.reattest(t2, k2, 1003), 1003)
        samples.append({'profile': profile, 'original_trust': t1, 'current_trust': t2, 'original_proof': old, 'renewed_proof': fresh, 'original_ref': record_ref(old), 'renewed_ref': record_ref(fresh), 'original_fact_id': fact_id(old), 'renewed_fact_id': fact_id(fresh), 'first_result': first, 'repeat_result': repeat, 'settlements': w.settlements, 'fixture_call_count': ledger.call_count, 'fixture_effect_count': ledger.effect_count})
    sample_path = out / 'signed_examples.json'
    sample_path.write_text(json.dumps(samples, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    expected = {
        'verification.protocol_v26_final_recovery.test_old_gap.OldGap.test_first_expired_receipt_has_a_recovery_route',
        'verification.protocol_v26_final_recovery.test_old_gap.OldGap.test_first_receipt_after_rotation_has_a_recovery_route',
    }
    red = results['r1_expected_red']
    passed = red['tests'] == 2 and red['errors'] == 0 and set(red['failed_test_ids']) == expected and results['r2_recovery']['successful'] and results['r2_recovery']['tests'] == 16
    sources = list(base.glob('*.py')) + [base/'README.md', base/'red.txt', ROOT/'verification/protocol_v26_audit/lifecycle/model.py', ROOT/'verification/protocol_v25_reference/wire.py'] + list((ROOT/'system_dev/v26').glob('0*.md')) + list((ROOT/'system_dev/v26/contracts').glob('*.schema.json'))
    report = {'contract': 'ZJJ-CORE-2.6-R2', 'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'passed': passed, 'tests': results, 'signed_examples': sample_path.relative_to(ROOT).as_posix(), 'environment': {'python': sys.version, 'platform': platform.platform(), **{name: importlib.metadata.version(name) for name in ('jsonschema', 'cryptography', 'PyNaCl')}}, 'source_sha256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}, 'limits': ['Bounded signed model, not a product or full protocol implementation.', 'C registration, authenticated control snapshots, claim witnesses and ledger continuity are trusted fixture inputs.', 'Ledger execution counts are fixture constants, not observed real tool effects.', 'No durable database, crash consistency, cross-operation ledger uniqueness or full migration implementation tested.', 'The two R1 failures are expected counterexamples, not passing R2 tests.']}
    (out/'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (base/'LATEST').write_text(out.relative_to(base).as_posix()+'\n', encoding='utf-8')
    print(json.dumps({'passed': passed, 'r2_tests_passed': results['r2_recovery']['tests'] if results['r2_recovery']['successful'] else 0, 'r1_expected_failures': red['failures'], 'results': (out/'results.json').relative_to(ROOT).as_posix()}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
