"""Load the retained R2 message schemas for the three competition profiles."""
from pathlib import Path
import json
from jsonschema import Draft202012Validator
from competition.support.wire import ProtocolError,require

COMPETITION_PROTO='ZJJ-CORE-COMP-1'

CONTRACTS={'PAY-1':'pay1','IND-DEMO-1':'industrial','MED-DEMO-1':'medical'}
UPSTREAM_HEAD='0ad0ddc3a1f97a2e6da340337cf9a53426aaa45c'

# Validating one retained contract file against the jsonschema meta-schema costs
# about a fifth of a second, and every TrustedState construction builds three of
# them, so the same immutable file was meta-checked dozens of times per process
# for an answer that cannot change.  The check is kept -- it is what catches a
# corrupted or swapped installation -- but done once per file version instead of
# once per construction.  The parsing itself is not cached: CompetitionSchema
# edits the definitions it loads.
CHECKED_SCHEMAS=set()

def _checked_schema(path,schema):
    status=path.stat();version=(str(path),status.st_mtime_ns,status.st_size)
    if version not in CHECKED_SCHEMAS:
        Draft202012Validator.check_schema(schema)
        CHECKED_SCHEMAS.add(version)

class UpstreamSchema:
    def __init__(self,root,profile):
        require(profile in CONTRACTS,'PROFILE')
        self.profile=profile
        self.path=Path(root)/'system_dev'/'v26'/'contracts'/(CONTRACTS[profile]+'.schema.json')
        if not self.path.is_file():raise ProtocolError('SCHEMA_NOT_INSTALLED')
        self.schema=json.loads(self.path.read_text(encoding='utf-8'))
        _checked_schema(self.path,self.schema)
        self.defs=self.schema['$defs']
    def validate(self,value,def_name='Envelope'):
        require(def_name in self.defs,'UNKNOWN_SCHEMA_DEF')
        validator=Draft202012Validator({'$schema':self.schema['$schema'],
                                        '$defs':self.defs,'$ref':'#/$defs/'+def_name})
        errors=list(validator.iter_errors(value))
        if errors:
            errors.sort(key=lambda e:(list(map(str,e.path)),e.message))
            first=errors[0]
            raise ProtocolError('UPSTREAM_SCHEMA_REJECT:'+def_name+':'+'.'.join(map(str,first.path)))
        return True


class CompetitionSchema(UpstreamSchema):
    """R2 field definitions with an explicit, signed competition protocol id.

    The retained R2 source files are immutable. This view changes only the
    Envelope protected.proto const; Record and Action hashes stay R2 2.6.  It
    also adds the optional GoalFloor record and the optional COMMIT.goal witness
    used when the competition integration enables the goal-floor guard.  Both
    are additive: existing records remain valid without them.
    """
    def __init__(self,root,profile):
        super().__init__(root,profile)
        from competition.support.wire import TYPES
        for name in TYPES:
            self.defs[name]['properties']['protected']['properties']['proto']['const'] = COMPETITION_PROTO
        self.defs['Record_GOAL_FLOOR'] = {
            'type': 'object',
            'properties': {
                'version': {'const': '2.6'},
                'profile': {'const': profile},
                'kind': {'const': 'GOAL_FLOOR'},
                'scope': {'$ref': '#/$defs/Scope'},
                'value': {
                    'type': 'object',
                    'properties': {
                        'model': {'const': 'goal-floor-v1'},
                        'group': {'$ref': '#/$defs/Id'},
                        'epoch': {'$ref': '#/$defs/Positive'},
                        'resource_key': {'type': 'array', 'items': {'$ref': '#/$defs/Id'},
                                         'minItems': 1, 'maxItems': 8, 'uniqueItems': True},
                        'unit': {'type': 'string', 'enum': ['UNIT', 'ORDER', 'CNY_MINOR']},
                        'capacity': {'$ref': '#/$defs/Positive'},
                        'deps': {'type': 'array', 'minItems': 1, 'maxItems': 16,
                                 'items': {
                                     'type': 'object',
                                     'properties': {
                                         'namespace': {'type': 'string', 'enum': ['POLICY', 'TASK', 'INCIDENT']},
                                         'key': {'type': 'array', 'items': {'type': 'string'},
                                                 'minItems': 1, 'maxItems': 8},
                                         'revision': {'$ref': '#/$defs/Positive'},
                                         'ref': {'$ref': '#/$defs/B32'}},
                                     'required': ['namespace', 'key', 'revision', 'ref'],
                                     'additionalProperties': False}},
                        'actions': {'type': 'array', 'minItems': 1, 'maxItems': 64,
                                    'items': {
                                        'type': 'object',
                                        'properties': {
                                            'name': {'$ref': '#/$defs/Id'},
                                            'profile': {'const': profile},
                                            'action_digest': {'$ref': '#/$defs/B32'},
                                            'obligation': {'type': 'string', 'maxLength': 64,
                                                           'pattern': '^$|^[a-z0-9][a-z0-9._:-]{0,63}$'},
                                            'cost': {'$ref': '#/$defs/Positive'}},
                                        'required': ['name', 'profile', 'action_digest',
                                                     'obligation', 'cost'],
                                        'additionalProperties': False}}
                    },
                    'required': ['model', 'group', 'epoch', 'resource_key', 'unit',
                                 'capacity', 'deps', 'actions'],
                    'additionalProperties': False}
            },
            'required': ['version', 'profile', 'kind', 'scope', 'value'],
            'additionalProperties': False}
        commit = self.defs['Record_COMMIT']['properties']['value']
        commit['properties']['goal'] = {
            'type': 'object',
            'properties': {
                'mode': {'type': 'string', 'enum': ['shadow', 'enforce']},
                'decision': {'type': 'string', 'enum': ['T', 'F']},
                'reason': {'type': 'string', 'maxLength': 128},
                'goal_refs': {'type': 'array', 'items': {'$ref': '#/$defs/B32'},
                              'minItems': 0, 'maxItems': 64, 'uniqueItems': True},
                'deps': {'type': 'array', 'minItems': 0, 'maxItems': 64, 'items': {
                    'type': 'object',
                    'properties': {
                        'namespace': {'type': 'string', 'enum': ['POLICY', 'TASK', 'INCIDENT']},
                        'key': {'type': 'array', 'items': {'type': 'string'},
                                'minItems': 1, 'maxItems': 8},
                        'revision': {'$ref': '#/$defs/Positive'},
                        'ref': {'$ref': '#/$defs/B32'}},
                    'required': ['namespace', 'key', 'revision', 'ref'],
                    'additionalProperties': False}},
                'matched': {'type': 'array', 'maxItems': 64, 'items': {
                    'type': 'object',
                    'properties': {
                        'group': {'$ref': '#/$defs/Id'},
                        'goal_ref': {'$ref': '#/$defs/B32'},
                        'epoch': {'$ref': '#/$defs/Positive'},
                        'action': {'$ref': '#/$defs/Id'},
                        'obligation': {'type': 'string', 'maxLength': 64},
                        'cost': {'$ref': '#/$defs/Positive'}},
                    'required': ['group', 'goal_ref', 'epoch', 'action', 'obligation', 'cost'],
                    'additionalProperties': False}},
                'capacity': {'$ref': '#/$defs/N'},
                'spent': {'$ref': '#/$defs/N'},
                'reserved': {'$ref': '#/$defs/N'},
                'candidate_cost': {'$ref': '#/$defs/Positive'},
                'remaining_floor': {'$ref': '#/$defs/N'},
                'total': {'$ref': '#/$defs/N'},
                'headroom': {'type': 'string', 'pattern': '^-?[0-9]+$'},
                'state_ref': {'$ref': '#/$defs/B32'},
                'check_ref': {'$ref': '#/$defs/B32'}
            },
            'required': ['mode', 'decision', 'reason', 'goal_refs', 'deps', 'matched',
                         'capacity', 'spent', 'reserved', 'candidate_cost',
                         'remaining_floor', 'total', 'headroom', 'state_ref', 'check_ref'],
            'additionalProperties': False}
        self.defs['Record_INCIDENT'] = {
            'type': 'object',
            'properties': {
                'version': {'const': '2.6'},
                'profile': {'const': profile},
                'kind': {'const': 'INCIDENT'},
                'scope': {'$ref': '#/$defs/Scope'},
                'value': {
                    'type': 'object',
                    'properties': {
                        'incident_id': {'$ref': '#/$defs/Id'},
                        'zone': {'$ref': '#/$defs/Id'},
                        'asset': {'$ref': '#/$defs/Id'},
                        'severity': {'type': 'string',
                                     'enum': ['LOW', 'HIGH', 'CRITICAL']},
                        'status': {'type': 'string',
                                   'enum': ['TRIGGERED', 'CONTAINED', 'RESTORED', 'CLOSED']},
                        'required_actions': {'type': 'array', 'items': {'$ref': '#/$defs/Id'},
                                             'minItems': 1, 'maxItems': 8},
                        'iat': {'$ref': '#/$defs/N'},
                        'exp': {'$ref': '#/$defs/N'}},
                    'required': ['incident_id', 'zone', 'asset', 'severity', 'status',
                                 'required_actions', 'iat', 'exp'],
                    'additionalProperties': False}
            },
            'required': ['version', 'profile', 'kind', 'scope', 'value'],
            'additionalProperties': False}
