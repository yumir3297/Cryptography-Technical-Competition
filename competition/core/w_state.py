"""W-owned mutable state anchored to the unchanged C-certified genesis."""
import copy
import json
from competition.core.trusted_state import enc
from competition.support.wire import require

class WState:
    def __init__(self, source, overlay=None):
        self.source=source; self.overlay=overlay or {}
    def __getattr__(self,name): return getattr(self.source,name)
    def current(self,c,p,ns,key):
        base=self.source.current(c,p,ns,key)
        row=c.execute('SELECT * FROM w_mutable WHERE profile=? AND namespace=? AND key=?',(p,ns,enc(key))).fetchone()
        if row:
            require(base['ref']==row['genesis_ref'] and base['revision']==row['genesis_revision'],'STATE_GENESIS_CHANGED')
            record=json.loads(row['record'])
            require(self.source.row_ref(ns,key,row['revision'],record)==row['ref'],'STATE_INTEGRITY')
            result={'revision':row['revision'],'ref':row['ref'],'record':record,'certificate':base['certificate']}
        else: result=base
        witness=self.overlay.get((p,ns,enc(key)))
        if witness:
            result={**result,'revision':int(witness['revision']),'ref':witness['ref'],'record':{**result['record'],'value':copy.deepcopy(witness['row'])}}
        return result
    def put(self,c,p,ns,key,record,revision):
        base=self.source.current(c,p,ns,key)
        current=self.current(c,p,ns,key)
        require(revision==current['revision']+1,'NONMONOTONIC')
        ref=self.source.row_ref(ns,key,revision,record)
        c.execute('INSERT INTO w_mutable VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(profile,namespace,key) DO UPDATE SET revision=excluded.revision,ref=excluded.ref,record=excluded.record',
                  (p,ns,enc(key),revision,ref,enc(record),base['revision'],base['ref']))
        return ref
