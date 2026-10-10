// Independent Node/OpenSSL positive signature/hash cross-check, not a second
// complete authority/strict-subgroup/protocol implementation. Public test keys.
import fs from 'node:fs';
import crypto from 'node:crypto';

let checks = 0;
function check(ok, label) { checks++; if (!ok) throw new Error(label); }
function stable(x) {
  if (typeof x === 'string' || typeof x === 'boolean') return JSON.stringify(x);
  if (Array.isArray(x)) return '[' + x.map(stable).join(',') + ']';
  if (x && typeof x === 'object') {
    const keys = Object.keys(x).sort();
    if (keys.some(k => !/^[\x00-\x7f]*$/.test(k))) throw new Error('non-ASCII key');
    return '{' + keys.map(k => JSON.stringify(k) + ':' + stable(x[k])).join(',') + '}';
  }
  throw new Error('forbidden scalar');
}
const enc = x => Buffer.from(stable(x), 'utf8');
const hash = x => crypto.createHash('sha256').update(enc(x)).digest('base64url');
const sigInput = o => enc(['ZJJ-TIME-SIG-PROPOSED-v2',o.protected,o.body]);
const objRef = (domain,o) => hash([domain,o.protected,o.body]);
const vectors = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const profiles = [];
for (const v of vectors) {
  profiles.push(v.profile);
  const q = v.query, p = v.package.observation, c = v.package.archive.original_core;
  const record = v.package.archive.commit;
  check(enc(q).equals(Buffer.from(v.query_wire_base64,'base64url')), 'query canonical bytes');
  check(enc(v.package).equals(Buffer.from(v.package_wire_base64,'base64url')), 'package canonical bytes');
  for (const [name,obj] of [['holder',q],['observer',p]]) {
    const key = crypto.createPrivateKey({key:Buffer.concat([
      Buffer.from('302e020100300506032b657004220420','hex'),
      Buffer.from(v.public_test_seeds_hex[name],'hex')]),format:'der',type:'pkcs8'});
    const pk = crypto.createPublicKey(key);
    const rawPk = pk.export({format:'der',type:'spki'}).subarray(-32);
    check(hash(['ZJJ-KEY-v1','Ed25519',rawPk.toString('base64url')]) === obj.protected.kid, 'current kid');
    check(crypto.verify(null,sigInput(obj),pk,Buffer.from(obj.sig,'base64url')), 'signature equation');
    check(crypto.sign(null,sigInput(obj),key).toString('base64url') === obj.sig, 'independent deterministic sign');
    check(!crypto.verify(null,Buffer.concat([sigInput(obj),Buffer.from('changed')]),pk,Buffer.from(obj.sig,'base64url')), 'tamper rejected');
    check(!crypto.verify(null,enc(['ZJJ-SIG-v1',obj.protected,obj.body]),pk,Buffer.from(obj.sig,'base64url')), 'R2 domain rejected');
  }
  check(objRef('ZJJ-TIME-QUERY-PROPOSED-v2',q) === v.query_ref && p.body.query_ref === v.query_ref,'query ref');
  check(objRef('ZJJ-TIME-OBS-PROPOSED-v2',p) === v.observation_ref,'observation ref');
  check(objRef('ZJJ-OBJ-v1',c) === v.original_acceptance_ref,'original R2 ref');
  check(hash(['ZJJ-RECORD-v1','2.6',record.profile,'COMMIT',record.scope,record.value]) === p.body.fact.commit_record_ref,'R2 commit ref');
  check(hash(['ZJJ-ACTION-v1','2.6',v.profile,record.value.action]) === p.body.fact.action_hash,'R2 AH');
  check(hash(['ZJJ-TIME-CORE-PROPOSED-v2',c]) === p.body.fact.original_core_digest,'core digest');
  check(hash(['ZJJ-ACCEPT-FACT-PROPOSED-v2',p.body.fact]) === v.fact_id,'fact id');
  check(!Object.hasOwn(c,'sig') && p.body.fact.accepted_at === '100' && p.body.iat === '1101','old unsigned fact/new time separated');
}
check(new Set(profiles).size === 3,'three profile vectors');
process.stdout.write(JSON.stringify({passed:true,checks,profiles,node:process.version,
  limits:'Positive vector signing/hash checks plus tamper/domain negatives; not authority, full schema, subgroup-rejection parity or complete protocol interoperability.'})+'\n');
