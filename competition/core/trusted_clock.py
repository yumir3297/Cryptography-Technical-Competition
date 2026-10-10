"""Competition Edition C-authenticated trusted-time interval with durable lower floor.

The controller time assertion is a laboratory oracle, *not* an NTP, TEE,
quorum timestamp, or externally audited trustworthy clock.
"""
from research.reference_executor.wire import require,canonical,b64,raw,strict_verify,number

DOMAIN='ZJJ-C-TRUSTED-CLOCK-RESEARCH-v1'

def seal(controller,profile,scope,operation_id,purpose,seq,lo,hi):
    require(type(seq) is int and seq>0 and type(lo) is int and type(hi) is int and 0<=lo<=hi,'CLOCK_RANGE')
    claim={'profile':profile,'scope':scope,'operation_id':operation_id,'purpose':purpose,
           'sequence':str(seq),'lo':str(lo),'hi':str(hi)}
    return {'claim':claim,'signature':b64(controller.key.sign(canonical([DOMAIN,claim])))}

def prepare_table(c):
    c.execute('''CREATE TABLE IF NOT EXISTS r2_clock(
                id INTEGER PRIMARY KEY CHECK(id=1),sequence INTEGER NOT NULL)''')
    # Legacy research databases have only (id, sequence). Preserve their state.
    cols={row[1] for row in c.execute('PRAGMA table_info(r2_clock)')}
    if 'time_floor' not in cols:
        c.execute('ALTER TABLE r2_clock ADD COLUMN time_floor INTEGER NOT NULL DEFAULT 0')
    c.execute('INSERT OR IGNORE INTO r2_clock(id,sequence,time_floor) VALUES(1,0,0)')

def checked_clock(c,cert,root_pub,profile,scope,op,purpose):
    require(type(cert) is dict and set(cert)=={'claim','signature'},'CLOCK_FIELDS')
    cl=cert['claim'];require(type(cl) is dict and set(cl)==
            {'profile','scope','operation_id','purpose','sequence','lo','hi'},'CLOCK_FIELDS')
    require((cl['profile'],cl['scope'],cl['operation_id'],cl['purpose'])==(profile,scope,op,purpose),'CLOCK_BINDING')
    strict_verify(root_pub,raw(cert['signature'],64),canonical([DOMAIN,cl]))
    require(all(number(cl[k]) for k in ('sequence','lo','hi')) and int(cl['sequence'])>0,'CLOCK_RANGE')
    lo=int(cl['lo']);hi=int(cl['hi'])
    # Accepted signed intervals must have a bounded uncertainty and never
    # move below a previously established lower bound. This is a lab clock
    # adapter, NOT an authenticated wall-clock freshness attestation.
    require(lo<=hi and hi-lo<=2,'CLOCK_UNKNOWN')
    prepare_table(c)
    old,floor=c.execute('SELECT sequence,time_floor FROM r2_clock WHERE id=1').fetchone()
    require(int(cl['sequence'])>old,'CLOCK_REPLAY')
    require(lo>=floor,'CLOCK_ROLLBACK')
    # Must be called inside the caller's BEGIN IMMEDIATE decision transaction:
    # a rejected decision rolls back the new floor as well.
    c.execute('UPDATE r2_clock SET time_floor=MAX(time_floor,?) WHERE id=1',(lo,))
    return lo,hi,int(cl['sequence'])

def consume_clock(c,sequence):
    require(c.execute('UPDATE r2_clock SET sequence=? WHERE id=1 AND sequence<?',(sequence,sequence)).rowcount==1,'CLOCK_REPLAY')
