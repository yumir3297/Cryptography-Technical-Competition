"""C-authenticated trusted-time interval, fail-closed monotone local W clock.

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
    c.execute('INSERT OR IGNORE INTO r2_clock VALUES(1,0)')

def checked_clock(c,cert,root_pub,profile,scope,op,purpose):
    require(type(cert) is dict and set(cert)=={'claim','signature'},'CLOCK_FIELDS')
    cl=cert['claim'];require(type(cl) is dict and set(cl)==
            {'profile','scope','operation_id','purpose','sequence','lo','hi'},'CLOCK_FIELDS')
    require((cl['profile'],cl['scope'],cl['operation_id'],cl['purpose'])==(profile,scope,op,purpose),'CLOCK_BINDING')
    strict_verify(root_pub,raw(cert['signature'],64),canonical([DOMAIN,cl]))
    require(all(number(cl[k]) for k in ('sequence','lo','hi')) and int(cl['sequence'])>0,'CLOCK_RANGE')
    lo=int(cl['lo']);hi=int(cl['hi']);require(lo<=hi,'CLOCK_RANGE')
    old=c.execute('SELECT sequence FROM r2_clock WHERE id=1').fetchone()[0]
    require(int(cl['sequence'])>old,'CLOCK_REPLAY')
    return lo,hi,int(cl['sequence'])

def consume_clock(c,sequence):
    require(c.execute('UPDATE r2_clock SET sequence=? WHERE id=1 AND sequence<?',(sequence,sequence)).rowcount==1,'CLOCK_REPLAY')
