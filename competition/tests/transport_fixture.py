"""TEST-ONLY server bootstrap; runtime keys remain in private test directories."""
import json
import os
import sys
from pathlib import Path
from competition.w_cases import recover_fixture
from competition.application.trusted_action_resolver import TrustedActionResolver
from competition.application.operation_orchestrator import OperationOrchestrator
from competition.tests.resolver_fixtures import P

def main(metadata,token_file,ready_file,crash):
    from competition.application.request_bound_w import RequestBoundW
    from competition.application.operation_service import OperationService
    from competition.application.http_service import create_server
    run=recover_fixture(metadata)
    try:
        resolver=TrustedActionResolver(run.store,run.operations[P]['task_id'])
        run.w=RequestBoundW(run.w,resolver.requests)
        flow=OperationOrchestrator(run.w,resolver.requests)
        class TestService(OperationService):
            def invoke(self,method,params):
                if crash=='accept' and method=='accept':
                    # Deliberate process exit strictly after persistent W COMMIT.
                    return self.w.accept(P,params['ticket_id'],params['proof'],crash_after_commit=True)
                return super().invoke(method,params)
        service=TestService(resolver,flow)
        server=create_server(service,Path(token_file).read_text().strip())
        Path(ready_file).write_text(json.dumps({'port':server.server_address[1]}))
        try:server.serve_forever(poll_interval=.05)
        finally:server.server_close()
    finally:run.close()

if __name__=='__main__':main(*sys.argv[1:])
