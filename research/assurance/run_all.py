"""Run this patch's checks and record evidence without inflating coverage claims."""
from pathlib import Path
from datetime import datetime, timezone
from importlib.metadata import version, PackageNotFoundError
import hashlib
import json
import os
import platform
import subprocess
import sys

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]

def run(*args):
    done=subprocess.run([sys.executable,*args],cwd=HERE,capture_output=True,text=True)
    return {'passed':done.returncode==0,'returncode':done.returncode,'stdout':done.stdout,
            'stderr':done.stderr[-2500:]}


def main():
    report={
        'scope':'candidate normative closure + bounded abstract model + proposed DENY range demo + primitive microbenchmark',
        'generated_at_utc':datetime.now(timezone.utc).isoformat(),
        'python':platform.python_version(),
        'platform':platform.platform(),
        'results':{},
    }
    model=run('abstract_checker.py','--depth','18','--mutants')
    report['results']['abstract_checker_run']={'passed':model['passed']}
    if model['passed']:
        obj=json.loads(model['stdout'])
        report['results']['abstract_checker_run'].update({
            'baseline_states':obj['baseline']['visited_states'],
            'baseline_edges':obj['baseline']['explored_edges'],
            'finite_model_exhausted':obj['baseline']['fully_explored_finite_model'],
            'baseline_has_violation':obj['baseline']['first_violation'] is not None,
            'mutation_counterexamples':{k:v['first_violation']['properties'] if v['first_violation'] else []
                                    for k,v in obj['mutants'].items()},
            'all_mutants_exposed':all(v['first_violation'] for v in obj['mutants'].values()),
        })
    tests=run('-m','unittest','discover','-s',str(HERE),'-p','test_*.py','-v')
    report['results']['abstract_unit_tests']=tests
    try:
        version('cryptography')
        bench=run('benchmark_primitives.py','--iterations','600')
        if bench['passed']:
            b=json.loads(bench['stdout'])
            report['results']['crypto_microbenchmark']={
                'passed':True,'iterations':b['iterations'], 'measurements':b['sizes'],
                'limits':b['limits']}
        else:report['results']['crypto_microbenchmark']=bench
    except PackageNotFoundError:
        report['results']['crypto_microbenchmark']={'passed':False,'skipped':'cryptography not installed'}
    cases=REPO/'system_dev/v26/semantic_cases.json'
    if cases.exists():
        inventory=run('conformance_inventory.py')
        report['results']['semantic_case_inventory']=inventory
    else:
        report['results']['semantic_case_inventory']={
            'passed':False,'skipped':'original semantic_cases.json absent from standalone patch',
            'full_semantic_test_claim':'NOT_RUN / not tested by this package'}
    source_files=sorted(x for x in HERE.glob('*') if x.suffix in ('.py','.md'))
    report['source_sha256']={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in source_files}
    report['overall_local_checks_passed']=(
        model['passed'] and not report['results']['abstract_checker_run'].get('baseline_has_violation',True)
        and report['results']['abstract_checker_run'].get('all_mutants_exposed',False)
        and tests['passed'] and report['results']['crypto_microbenchmark']['passed'])
    outfile=HERE/'local_validation_report.json'
    outfile.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'overall_local_checks_passed':report['overall_local_checks_passed'],
                      'model_states':report['results']['abstract_checker_run'].get('baseline_states'),
                      'unit_tests':tests['stderr'].splitlines()[-3:],
                      'semantic_conformance':'NOT_RUN in standalone patch',
                      'report':str(outfile)},ensure_ascii=False))
    return 0 if report['overall_local_checks_passed'] else 1

if __name__=='__main__':raise SystemExit(main())
