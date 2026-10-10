"""Isolated microbenchmark, NOT end-to-end ZJJ performance.
Usage: python research/assurance/benchmark_primitives.py --iterations 1000 --output result.json
Requires: cryptography (for Ed25519). This script does not execute protocol APIs.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import platform
import statistics
import time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from importlib.metadata import version


def ns_bench(action, n):
    samples = []
    for _ in range(n):
        start = time.perf_counter_ns()
        action()
        samples.append(time.perf_counter_ns()-start)
    ordered = sorted(samples)
    return {'median_us':round(statistics.median(samples)/1000,3),
            'p95_us':round(ordered[(len(ordered)*95+99)//100-1]/1000,3),
            'mean_us':round(statistics.mean(samples)/1000,3)}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--iterations', type=int, default=1000)
    p.add_argument('--output')
    args=p.parse_args()
    if args.iterations < 100: p.error('use at least 100 iterations')
    key=Ed25519PrivateKey.generate()
    pub=key.public_key()
    result={'kind':'primitive_microbenchmark_only',
            'generated_at_utc':datetime.now(timezone.utc).isoformat(),
            'iterations':args.iterations,
            'environment':{'python':platform.python_version(), 'platform':platform.platform(),
                           'cryptography':version('cryptography')},
            'public_key_bytes':len(pub.public_bytes(Encoding.Raw,PublicFormat.Raw)),
            'signature_bytes':64, 'sizes':{}}
    for size in (512,4096,16384):
        data=b'ZJJ-domain-separated-test' + b'z'*(size-25)
        sig=key.sign(data)
        assert len(data)==size and len(sig)==64
        pub.verify(sig,data)
        for _ in range(100):key.sign(data);pub.verify(sig,data);hashlib.sha256(data).digest()
        result['sizes'][size]={
            'sha256':ns_bench(lambda:hashlib.sha256(data).digest(),args.iterations),
            'ed25519_sign':ns_bench(lambda:key.sign(data),args.iterations),
            'ed25519_verify':ns_bench(lambda:pub.verify(sig,data),args.iterations),
        }
    result['limits']=[
        'Single-process sequential local microbench. No network, W transaction, JSON Schema, graph checking or durable store.',
        'Not a measured end-to-end ZJJ signature count or commit latency.',
        'No claims about real payments, industrial equipment or medical devices.',
        'Measurements vary with hardware/software/load and cannot be used for cross-system superiority without matched setups.'
    ]
    out=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(out,encoding='utf8')
    print(out)

if __name__=='__main__':main()
