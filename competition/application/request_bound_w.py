"""Mandatory request boundary for the IND application service; raw W stays internal."""
from competition.core.common_w import CommonW
from competition.application.request_store import RequestStore
from competition.support.wire import require

class RequestBoundW(CommonW):
    def __init__(self, core, requests):
        require(type(requests) is RequestStore and requests.state is core.source,
                'REQUEST_STORE_REQUIRED')
        require(type(core) is CommonW,'W_CORE_REQUIRED')
        super().__init__(core.source,core.delivery_key,core.worker_certificate,
                         core.x_signers,core.tool_gateways)
        self._requests = requests
        self._clock_lock = core._clock_lock

    @property
    def requests(self):
        return self._requests

    def _check_current_submission(self,c,p,op):
        self._requests.check_current(c,p,op)
