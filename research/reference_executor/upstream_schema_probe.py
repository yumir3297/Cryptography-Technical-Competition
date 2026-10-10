"""Non-destructive offline probe against actual upstream Schema *when installed*.

This does not alter the original Schema or semantic_cases.json. A probe
failure is an engineering todo, not an authorized workaround.
"""
from pathlib import Path
import json
from .engine import ReferenceW
from .wire import sid,digest

ROOT=Path(__file__).resolve().parents[2]
FIXTURES={
 'PAY-1':({'order_id':'ord1','stage':'initial','payer':'payer1','payee':'payee1','amount_minor':'1000','currency':'CNY','purpose':'order-settlement'},{'risk':'ANOMALY'}),
 'IND-DEMO-1':({'line_id':'linea','unit_id':'unit1','station_id':'station1','inspection_cycle':'1','phase':'INITIAL','route':'INSPECT'},{'label':'DEMO_UNCERTAIN'}),
 'MED-DEMO-1':({'synthetic_patient_id':'patient1','encounter_id':'visit1','order_group_id':sid(44),'phase':'SUBMIT','template_id':'DEMO-ORDER-A','record_ref':digest(['ev']),'destination_system':'med-demo-ledger'},{'available':True,'complete':True,'label':'DEMO_A'})
}

def probe(root=ROOT):
 from jsonschema import Draft202012Validator
 records=[]
 for pf,stem in [('PAY-1','pay1'),('IND-DEMO-1','industrial'),('MED-DEMO-1','medical')]:
  path=Path(root)/'system_dev/v26/contracts'/f'{stem}.schema.json'
  if not path.exists():
   records.append({'profile':pf,'status':'SKIPPED_NO_UPSTREAM_SCHEMA','schema':str(path)});continue
  schema=json.loads(path.read_text(encoding='utf8'))
  w=ReferenceW(pf);p,e=FIXTURES[pf];op=w.prepare(p,e)
  review=w.review(op)
  v=Draft202012Validator(schema)
  errs=sorted(v.iter_errors(review),key=lambda x:list(map(str,x.path)))
  records.append({'profile':pf,'status':'SCHEMA_VALID' if not errs else 'SCHEMA_INVALID',
                  'schema':str(path),'sample':'real-signed Review fixture',
                  'errors':[{'path':list(map(str,err.path)),'message':err.message[:500]} for err in errs[:20]],
                  'total_errors':len(errs)})
 return records
if __name__=='__main__':print(json.dumps(probe(),ensure_ascii=False,indent=2))
