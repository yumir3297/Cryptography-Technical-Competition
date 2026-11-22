"""Run the synthetic two-unit batch and export public offline inputs."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from competition.profiles.w_scenarios import register_release_batch
from competition.profiles.w_seed import initialize
from competition.support.wire import b64, require
from competition.verify_industrial_completion import PROFILE, verify
from competition.w_cases import accept_operation


def run_demo(output):
    output.mkdir(parents=True, exist_ok=False)
    with TemporaryDirectory() as folder:
        run = initialize(Path(folder), ind_label='DEMO_NORMAL', resource_capacity={PROFILE: 2})
        try:
            first, second = register_release_batch(run)
            pins = {'c_public': run.root.public_key().public_bytes_raw(),
                    'x_public': run.actors[PROFILE]['X'].pub,
                    'e_public': run.actors[PROFILE]['E'].pub}
            output.joinpath('fixture-public-keys.json').write_text(
                json.dumps({name: b64(key) for name, key in pins.items()}, indent=2), encoding='utf-8')
            for number, op in enumerate((first, second), 1):
                if number == 2:
                    op['task_id'] = first['task_id']
                    op['action']['principal'] = first['action']['principal']
                    op = run.fork_operation(PROFILE, op)
                oid, _ = accept_operation(run, PROFILE, op)
                run.w.claim(PROFILE, oid, run.worker_proof(PROFILE, oid, 'CLAIM'))
                response = run.w.execute_once(PROFILE, oid, run.worker_proof(PROFILE, oid, 'EXECUTE'))
                require(response['state'] == 'SUCCEEDED', 'DEMO_TOOL_RESULT')
                result = run.w.settle(PROFILE, oid, response, run.worker_proof(PROFILE, oid, 'SETTLE'))
                require(result['state'] == 'SETTLED', 'DEMO_SETTLEMENT')
                audit = run.w.audit(PROFILE, oid, run.read_proof(PROFILE, oid, 'AUDIT'))
                verified = verify(audit, **pins)
                output.joinpath(f'acceptance-{number}.json').write_text(
                    json.dumps(audit, indent=2), encoding='utf-8')
                print(json.dumps({'acceptance': number, 'settlement': result['state'], **verified}))
        finally:
            run.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run_demo(parser.parse_args().output)
