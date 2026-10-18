"""One-time synthetic bootstrap. Not an identity provider or approval service."""
import argparse
import json
import os
import secrets
from pathlib import Path

def provision(destination, *, port=18765):
    from competition.profiles.w_seed import initialize
    from competition.application.request_store import RequestStore
    from competition.w_cases import save_recovery_fixture
    from competition.support.wire import b64, require
    require(type(port) is int and 0 <= port <= 65535, 'LOCAL_BINDING_REQUIRED')
    home=Path(destination).resolve()
    home.mkdir(mode=0o700,parents=True,exist_ok=False)
    previous=os.umask(0o077)
    run=None
    try:
        state=home/'runtime';state.mkdir(mode=0o700)
        run=initialize(state)
        RequestStore(run.store)  # Establish the application schema only during provisioning.
        save_recovery_fixture(run,home/'lab-metadata.json')
        actors={p:{a:{'name':v.name,'kid':v.kid,'public_key':b64(v.pub),
                     'roles':sorted(v.roles),'purposes':sorted(v.purposes)}
                   for a,v in roster.items()} for p,roster in run.store.actors.items()}
        config={'version':1,'mode':'local-industrial-simulator','profile':'IND-DEMO-1',
                'host':'127.0.0.1','port':port,'runtime_dir':str(state.resolve()),
                'task_id':run.operations['IND-DEMO-1']['task_id'],
                'root_public':b64(run.store.root_public),'actors':actors,
                'worker_certificate':run.worker_certificate,'delivery_public':b64(run.delivery_public)}
        path=home/'service.json'
        with path.open('x') as stream:json.dump(config,stream,ensure_ascii=False,indent=2)
        with (home/'transport-token').open('x') as stream:stream.write(secrets.token_urlsafe(32))
        return str(path)
    finally:
        if run:run.close()
        os.umask(previous)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination');parser.add_argument('--port',type=int,default=18765)
    args=parser.parse_args()
    print(json.dumps({'service_config':provision(args.destination,port=args.port),
                      'scope':'Fresh local simulator; existing installations are never reset'}))

if __name__=='__main__':main()
