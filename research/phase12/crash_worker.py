"""Crash injection: committed W claim, then hard process exit without a final."""
import json,os,sys
from pathlib import Path
from research.phase6.trusted_final import Controller,ToolLedger
from research.phase12.authority import HardenedPayW,HardenedSceneW

def main():
    q=json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
    profile=q['profile']
    if profile=='PAY-1':
        ledger=ToolLedger(q['ledger_path'],profile='PAY-1')
        w=HardenedPayW(q['db_path'],Controller.fixture().public_key,ledger=ledger)
    else:w=HardenedSceneW(q['db_path'],profile)
    result=w.claim_r2(q['operation_id'],q['attempt'],clock=q['clock'])
    assert result['status']=='CLAIMED',result
    os._exit(79)

if __name__=='__main__':main()
