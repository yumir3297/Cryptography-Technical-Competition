// Independent JS canonical bytes, digest and Node/OpenSSL signature checks.
// This is a vector checker, not a protocol handler or strict-point validator.
import fs from 'node:fs';
import {createHash,createPrivateKey,createPublicKey,sign,verify} from 'node:crypto';
function canonical(v) {
  if(typeof v==='string') {
    for(const c of v)if(c.codePointAt(0)>=0xd800&&c.codePointAt(0)<=0xdfff)throw Error('UNICODE');
    return JSON.stringify(v);
  }
  if(typeof v==='boolean')return JSON.stringify(v);
  if(Array.isArray(v))return '['+v.map(canonical).join(',')+']';
  if(!v||typeof v!=='object')throw Error('WIRE_TYPE');
  const keys=Object.keys(v).sort();
  if(keys.some(k=>!/^[\x00-\x7f]*$/.test(k)))throw Error('KEY_ENCODING');
  return '{'+keys.map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';
}
const enc=v=>Buffer.from(canonical(v),'utf8');
const hash=v=>createHash('sha256').update(enc(v)).digest('base64url');
const data=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const key=createPrivateKey({key:Buffer.concat([Buffer.from('302e020100300506032b657004220420','hex'),Buffer.from(data.test_seed,'hex')]),format:'der',type:'pkcs8'});
const pub=createPublicKey(key);
const results=[];
for(const v of data.envelopes) {
  const o=v.envelope; const bytes=enc(['ZJJ-SIG-v1',o.protected,o.body]);
  if(enc(o).toString('base64')!==v.wire_base64||bytes.toString('base64')!==v.to_sign_base64||hash(['ZJJ-OBJ-v1',o.protected,o.body])!==v.ref)throw Error('BYTES');
  if(sign(null,bytes,key).toString('base64url')!==o.sig||!verify(null,bytes,pub,Buffer.from(o.sig,'base64url')))throw Error('SIGNATURE');
  results.push(v.id);
}
for(const v of data.records) {
  const o=v.record;
  if(enc(o).toString('base64')!==v.wire_base64||hash(['ZJJ-RECORD-v1',o.version,o.profile,o.kind,o.scope,o.value])!==v.ref)throw Error('RECORD');
  results.push(v.id);
}
for(const v of data.actions) {
  if(hash(['ZJJ-ACTION-v1','2.6',v.profile,v.action])!==v.hash)throw Error('ACTION');
  results.push(v.id);
}
for(const v of data.tool_evidence??[]) {
  const r=v.record;const val=r.value;const {attestation,...unsigned}=val;
  const bytes=enc(['ZJJ-TOOL-FINAL-v2','2.6',r.profile,r.scope,unsigned,{issuer:attestation.issuer,kid:attestation.kid}]);
  const fields=['ledger_id','operation_id','action_hash','dispatch_attempt','tool','tool_version','destination','outcome','effect_id','no_late_effect','final_seq','finalized_at'];
  const fact=Object.fromEntries(fields.map(k=>[k,val[k]]));
  if(bytes.toString('base64')!==v.to_sign_base64||hash(['ZJJ-TOOL-FACT-v1','2.6','tool-final-v2',r.profile,r.scope,fact])!==v.fact_id)throw Error('TOOL_FACT');
  const toolPub=createPublicKey({key:Buffer.concat([Buffer.from('302a300506032b6570032100','hex'),Buffer.from(v.public_key,'base64url')]),format:'der',type:'spki'});
  if(!verify(null,bytes,toolPub,Buffer.from(attestation.sig,'base64url')))throw Error('TOOL_SIGNATURE');
  results.push(v.id);
}
process.stdout.write(JSON.stringify({node:process.version,checked:results.length,ids:results,scope:'Restricted JCS bytes, domain-separated hashes, deterministic Ed25519 signing and valid-key verification. Not JS structural schema, strict subgroup rejection, state semantics or whole-protocol interoperation.'}));
