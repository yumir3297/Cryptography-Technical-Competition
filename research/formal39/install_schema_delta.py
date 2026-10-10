"""Verify official Github-pinned schema blobs transported as deltas against PAY Schema.
The verified byte-exact Git blob is the authority, not this delta encoding.
"""
from __future__ import annotations
import base64,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BASE=json.dumps(json.loads((ROOT/'system_dev/v26/contracts/pay1.schema.json').read_text()),ensure_ascii=False,separators=(',',':')).encode('ascii')
DELTA={
'industrial.schema.json':('f937286b1be32b2a8356b991a93770abff430578', '''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'''),
}

def install():
 for name,(wanted,b64) in DELTA.items():
  p=base64.b64decode(b64);out=bytearray();i=0
  while i<len(p):
   x=p[i];i+=1
   if x!=255:out.append(x);continue
   cmd=p[i];i+=1
   if cmd==0:out.append(255)
   elif cmd==1:
    pos=(p[i]<<8)|p[i+1];size=(p[i+2]<<8)|p[i+3];i+=4
    out.extend(BASE[pos:pos+size])
   elif cmd==2:
    dist=(p[i]<<8)|p[i+1];size=p[i+2];i+=3
    for _ in range(size):out.append(out[-dist])
   else:raise ValueError('bad patch opcode')
  obj=json.loads(out.decode('ascii'))
  content=(json.dumps(obj,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
  actual=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
  if actual!=wanted:raise RuntimeError(f'{name}: checksum mismatch {actual} != {wanted}')
  destination=ROOT/'system_dev/v26/contracts'/name;destination.parent.mkdir(parents=True,exist_ok=True)
  destination.write_bytes(content)
  print('PINNED_SCHEMA_VERIFIED',name,len(content),actual)
if __name__=='__main__':install()
