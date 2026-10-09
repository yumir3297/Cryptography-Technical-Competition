"""Load the *actual* ZJJ schemas after the patch is merged into upstream repo.

No local substitute is silently labeled as an official schema. When the upstream
contracts cannot be found, callers receive a clear SCHEMA_NOT_INSTALLED status.
"""
from pathlib import Path
import json
from jsonschema import Draft202012Validator
from research.reference_executor.wire import ProtocolError,require

CONTRACTS={'PAY-1':'pay1','IND-DEMO-1':'industrial','MED-DEMO-1':'medical'}
UPSTREAM_HEAD='0ad0ddc3a1f97a2e6da340337cf9a53426aaa45c'

class UpstreamSchema:
    def __init__(self,root,profile):
        require(profile in CONTRACTS,'PROFILE')
        self.profile=profile
        self.path=Path(root)/'system_dev'/'v26'/'contracts'/(CONTRACTS[profile]+'.schema.json')
        if not self.path.is_file():raise ProtocolError('SCHEMA_NOT_INSTALLED')
        self.schema=json.loads(self.path.read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(self.schema)
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
