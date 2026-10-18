"""Diagnostic child wrapper: exact original time returns and signing policy.

Logs acquisition spans and origins outside protocol messages. No private values,
no time adjustment, no healthy rewrite, no retries. This is test instrumentation.
"""
import collections
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))

def main(kind,*args):
    if kind=='runtime':
        import subprocess
        import runpy
        popen=subprocess.Popen
        def observed(command,*pos,**kwargs):
            if type(command) is list and len(command)>=4 and command[1]=='-m':
                if command[2]=='competition.core.signing' and command[3]=='C':
                    command=[command[0],str(Path(__file__).resolve()),'C',*command[4:]]
                elif command[2]=='competition.core.common_receipt':
                    command=[command[0],str(Path(__file__).resolve()),'X',*command[3:]]
            return popen(command,*pos,**kwargs)
        subprocess.Popen=observed
        name,*tail=args;sys.argv=[name,*tail];runpy.run_module(name,run_name='__main__')
        return
    if kind=='C':
        from competition.core import signing as module
    else:
        from competition.core import common_receipt as module
    actual_time=module.time
    captures=collections.deque(maxlen=8)
    origins=[]
    class ObservedTime:
        def __getattr__(self,name):return getattr(actual_time,name)
        def time_ns(self):
            before=actual_time.monotonic_ns();value=actual_time.time_ns();after=actual_time.monotonic_ns()
            capture={'clock':'wall','value':str(value),'mono_before':str(before),'mono_after':str(after)}
            captures.append(capture)
            if len(origins)<2:origins.append(capture)
            return value
        def monotonic_ns(self):
            value=actual_time.monotonic_ns();capture={'clock':'mono','value':str(value)}
            captures.append(capture)
            if len(origins)<2:origins.append(capture)
            return value
    module.time=ObservedTime()
    output=os.environ['ZJJ_CLOCK_OBSERVATION_FILE']
    def emit(data):
        row={'pid':os.getpid(),'role':kind,'test':os.environ.get('ZJJ_DIAGNOSTIC_TEST','unknown'),
             'origins':origins,'captures':list(captures),**data}
        with open(output,'a',encoding='utf-8') as stream:stream.write(json.dumps(row)+'\n')
    if kind=='C':
        original=module.canonical
        def canonical(value):
            result=original(value)
            if type(value) is list and value[0]=='ZJJ-COMP-EVENT-CLOCK-v1':
                emit({'claim':value[1]})
            return result
        module.canonical=canonical
        module.worker('C',*args)
    else:
        original=module._sign_committed
        def sign(*values):
            try:return original(*values)
            except BaseException as exc:
                emit({'code':getattr(exc,'code',type(exc).__name__),
                    'origin_wall':str(values[6]),'origin_mono':str(values[7]),'floor':str(values[8]),
                    'operation_id':values[1].get('operation_id')})
                raise
        module._sign_committed=sign
        module.worker(*args)

if __name__=='__main__':main(*sys.argv[1:])
