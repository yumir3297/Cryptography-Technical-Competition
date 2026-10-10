"""Intentionally hard-exit a fresh interpreter within or after SQLite commit."""
import argparse
from research.phase4.flow import SignedPayFlow
from .durable_w import DurablePayW

def ready():
    f=SignedPayFlow();op=f.prepare()
    for p in op.required:f.review(op,purpose=p)
    f.authorize(op);f.issue(op);f.challenge(op)
    return f,op

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('db')
    parser.add_argument('point',choices=['hard_after_validation','hard_after_writes','hard_after_commit'])
    args=parser.parse_args()
    f,o=ready()
    DurablePayW(args.db).accept(f,o,inject=args.point)
    raise AssertionError('Crash hook did not trigger')
