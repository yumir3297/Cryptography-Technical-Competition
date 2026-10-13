"""Data-only competition candidate ingress; no signer, worker or tool capability.

Trusted startup chooses the profile and schema directory. An agent supplies
canonical JSON Action bytes. The trusted host separately obtains approval and
submits the full signed chain to W; parsing never grants execution authority.
"""
import copy
from competition.support.schema import CompetitionSchema
from competition.support.broker_policy import PROFILE_SCOPES
from competition.support.wire import require, load_canonical

class CandidateIngress:
    def __init__(self, schema_root):
        self.schemas={p:CompetitionSchema(schema_root,p) for p in PROFILE_SCOPES}

    def parse(self,profile,blob):
        require(type(profile) is str and profile in self.schemas,'PROFILE')
        require(type(blob) is bytes and len(blob)<=65536,'CANDIDATE_LIMIT')
        action=load_canonical(blob)
        self.schemas[profile].validate(action,'Action')
        require(action['scope']==PROFILE_SCOPES[profile],'BINDING')
        return copy.deepcopy(action)
