"""Data-only IND proposal contract. Parsing grants no execution authority."""
import copy
from competition.support.wire import load_canonical, require

class CandidateProposal:
    FIELDS = frozenset(('request_id', 'unit_id', 'route'))

    @classmethod
    def parse(cls, value):
        if type(value) is bytes:
            require(len(value) <= 65536, 'CANDIDATE_LIMIT')
            value = load_canonical(value)
        require(type(value) is dict and set(value) == cls.FIELDS, 'PROPOSAL_FIELDS')
        require(all(type(v) is str and 0 < len(v) <= 128 for v in value.values()),
                'PROPOSAL_VALUE')
        require(value['route'] in ('INSPECT', 'RELEASE', 'QUARANTINE'), 'PROPOSAL_ROUTE')
        return copy.deepcopy(value)
