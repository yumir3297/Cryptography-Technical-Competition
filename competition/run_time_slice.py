"""Reproduce/export the IND time slice and the real post-commit process exit."""
import argparse
import json
import os
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

from research.reference_executor.wire import raw, b64
from competition.core.acceptance import IndustrialAcceptanceW
from competition.core.signing import ClockClient
from competition.profiles.industrial_seed import initialize, public_roster


def crash_accept(checkpoint):
    data = json.loads(Path(checkpoint).read_text(encoding='utf-8'))
    actors = {alias: SimpleNamespace(name=a['name'], kid=a['kid'], pub=raw(a['pub'], 32), roles=a['roles'], purposes=a['purposes']) for alias, a in data['actors'].items()}
    clock = ClockClient(data['clock_key_path'], data['clock_database'])
    w = IndustrialAcceptanceW(data['database'], root_public=raw(data['root_public'], 32), actors=actors, clock=clock)
    w.accept(data['ticket_id'], proof=data['accept_proof'])
    # No rollback or graceful cleanup: W has actually committed before process death.
    os._exit(97)


def demo(output):
    import hashlib
    import subprocess
    import sys
    from research.reference_executor.wire import ProtocolError, rec_ref, canonical, strict_verify
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=True)
    run_id = 'time-' + str(time.time_ns())
    private = Path('.runtime') / run_id
    records = []
    scenarios = ['elapsed_success', 'expired_ticket', 'clock_unknown', 'revoke_before_accept', 'x_revoke_after_accept', 'x_expired_after_accept', 'signer_failure', 'post_commit_process_exit']
    for name in scenarios:
        seed = initialize(private / name, proof_ttl=5 if name == 'expired_ticket' else 30)
        try:
            ticket = seed.w.prepare(seed.op)
            accept_proof = seed.accept_proof(ticket['ticket_id'])
            before = seed.w.snapshot(); expected = None; recovery = None; child_code = None
            if name == 'elapsed_success':
                time.sleep(1.1)
            elif name == 'expired_ticket':
                time.sleep(max(0, ticket['expires'] - time.time()) + 0.05)
            elif name == 'clock_unknown':
                seed.clock.close()
            elif name == 'revoke_before_accept':
                seed.revoke('U')
            elif name in ('x_revoke_after_accept', 'x_expired_after_accept'):
                recovery = seed.w.accept(ticket['ticket_id'], proof=accept_proof)
                if name == 'x_revoke_after_accept':
                    seed.revoke('X')
                else:
                    seed.expire_x_credential()
            elif name == 'signer_failure':
                seed.x.close()
            elif name == 'post_commit_process_exit':
                cp = seed.folder / 'checkpoint.json'; seed.save_public_checkpoint(cp, ticket['ticket_id'])
                child = subprocess.run([sys.executable, '-m', 'competition.run_time_slice', '--crash-accept', str(cp)], capture_output=True, text=True)
                child_code = child.returncode
                if child_code != 97:
                    raise RuntimeError(child.stderr)
                with seed.w.db() as c:
                    recovery = {'frozen': json.loads(c.execute('SELECT frozen_json FROM comp_acceptance').fetchone()[0])}
            try:
                result = seed.w.accept(ticket['ticket_id'], seed.x, proof=seed.accept_proof(ticket['ticket_id']) if recovery else accept_proof)
                actual = result['observation_code']
            except ProtocolError as exc:
                result = None; actual = exc.code
            after = seed.w.snapshot()
            if name == 'elapsed_success':
                expected = 'ACCEPTED_WITH_RECEIPT'
            elif name == 'expired_ticket':
                expected = 'EXPIRED'
            elif name == 'clock_unknown':
                expected = 'CLOCK_UNKNOWN'
            elif name == 'revoke_before_accept':
                expected = 'REVOKED'
            elif name == 'post_commit_process_exit':
                expected = 'ACCEPTED_WITH_RECEIPT'
            else:
                expected = 'COMMITTED_RECEIPT_PENDING'
            assert actual == expected, (name, expected, actual)
            accepted = 0 if name in ('expired_ticket', 'clock_unknown', 'revoke_before_accept') else 1
            assert (after['accepts'], after['reserved'], after['calls']) == (accepted, accepted, 0)
            invariant = True
            if recovery:
                invariant = recovery['frozen'] == result['frozen']
                assert invariant
            if result and result['acceptance']:
                acceptance = result['acceptance']; core = result['frozen']['core']
                strict_verify(seed.actors['X'].pub, raw(acceptance['sig'], 64), canonical(['ZJJ-SIG-v1', core['protected'], core['body']]))
                assert result['frozen']['commit_ref'] == rec_ref(result['frozen']['commit'])
                repeat = seed.w.accept(ticket['ticket_id'], seed.x, proof=seed.accept_proof(ticket['ticket_id']))
                assert repeat['frozen'] == result['frozen'] and repeat['acceptance'] == acceptance
                assert seed.w.snapshot() == after
            case_id = {'elapsed_success': 'C-TIME-01', 'expired_ticket': 'C-TIME-02', 'clock_unknown': 'C-TIME-02', 'revoke_before_accept': 'C-TIME-03', 'x_revoke_after_accept': 'C-TIME-03', 'x_expired_after_accept': 'C-TIME-03', 'signer_failure': 'C-EXEC-04', 'post_commit_process_exit': 'C-STATE-01'}[name]
            item = {'subcase_id': case_id + '/IND-DEMO-1/' + name, 'scenario': name, 'status': 'PASS', 'expected': expected, 'actual': actual, 'before': before, 'after': after, 'prepared_at': ticket['prepared_at'], 'child_exit_code': child_code, 'frozen_preserved': invariant, 'result': result, 'input': seed.op, 'prepared_time_witness': ticket['time_witness'], 'public_roster': public_roster(seed.actors), 'trusted_root_public': b64(seed.issuer.root_public)}
            if name == 'elapsed_success':
                item['elapsed_authenticated_seconds'] = int(result['frozen']['commit']['value']['accepted_at']) - ticket['prepared_at']
                assert item['elapsed_authenticated_seconds'] >= 1
            evidence = output / (name + '.json')
            evidence.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding='utf-8')
            # Public table snapshot contains real C/E certificates, W facts and counts, no private keys.
            with seed.w.db() as c:
                tables = ['current_row', 'journal', 'accept_intent', 'resource', 'flight', 'behavior', 'comp_ticket', 'comp_acceptance', 'comp_consumed', 'comp_event_clock', 'comp_accept_nonce', 'comp_read_nonce']
                snapshot = {t: [dict(row) for row in c.execute('SELECT * FROM ' + t)] for t in tables}
            (output / (name + '-w.json')).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
            records.append({k: item[k] for k in ('subcase_id', 'scenario', 'status', 'expected', 'actual', 'after', 'child_exit_code', 'frozen_preserved')})
            print(name + ': PASS', flush=True)
        finally:
            seed.close()
    source_files = [{'path': p.as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(Path('competition').rglob('*.py'))]
    (output / 'source_manifest.json').write_text(json.dumps(source_files, indent=2), encoding='utf-8')
    files = [{'path': p.name, 'size': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(output.glob('*.json')) if p.name not in ('report.json', 'manifest.json')]
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    report = {'run_id': run_id, 'base_commit': 'dbda1cac814306fddcdd508cd9e45b5b62551299', 'build_commit': head, 'dirty': bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], text=True).strip()), 'source_digest': hashlib.sha256(''.join(p.as_posix() + ':' + hashlib.sha256(p.read_bytes()).hexdigest() + '\n' for p in sorted(Path('competition').rglob('*.py'))).encode()).hexdigest(), 'contract_version': 'COMP-APP-MIN-1.0', 'kind': 'IND_time_acceptance_vertical_slice_not_21_group_full_pass', 'cases': records, 'limits': ['Trusted single-host OS wall/monotonic clock, not independent time attestation.', 'C/X separate subprocesses but no Linux DAC proof in this Windows run; bootstrap remains trusted.', 'IND acceptance/receipt only; PR3 delivery, tools and three-Profile common W are not implemented.', 'Application status projection, not full original R2 signed STATUS when receipt absent.', 'Private run keys remain under ignored .runtime; evidence export excludes key contents.']}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'manifest.json').write_text(json.dumps({'run_id': run_id, 'files': files}, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--crash-accept')
    parser.add_argument('--output', default='competition/evidence/time-slice')
    args = parser.parse_args()
    if args.crash_accept:
        crash_accept(args.crash_accept)
    else:
        demo(args.output)
