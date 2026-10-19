"""Shared competition scene constants and record helpers.

Extracted from the retired ``scene_authority`` research module so the official
CommonW chain owns these values without depending on a vertical slice.  Names,
values and behaviour are preserved byte-for-byte from the original source.
"""
import json

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

PROFILES = {'IND-DEMO-1': ('industrial', 'IND_EVIDENCE', 'UNIT', 'IND_TASK', 'IND_UNIT'),
            'MED-DEMO-1': ('medical', 'MED_EVIDENCE', 'ENCOUNTER', 'MED_TASK', 'MED_ENCOUNTER')}
MAPPING = {'DEMO_NORMAL': 'RELEASE', 'DEMO_DEFECT': 'QUARANTINE', 'DEMO_UNCERTAIN': 'INSPECT'}
DEST = {'RELEASE': 'ind-release-bin', 'QUARANTINE': 'ind-quarantine-bin', 'INSPECT': 'ind-inspection-bay'}
TEMPLATES = {'DEMO_A': 'DEMO-ORDER-A', 'DEMO_B': 'DEMO-ORDER-B'}
EVID_FIELDS = {
    'IND-DEMO-1': {'evidence_id', 'evidence_revision', 'unit_ref', 'unit_id', 'batch_id', 'line_id', 'station_id',
                   'inspection_cycle', 'phase', 'sampled_at', 'known_at', 'quality_flag', 'label'},
    'MED-DEMO-1': {'evidence_id', 'evidence_revision', 'record_id', 'record_revision', 'encounter_ref',
                   'synthetic_patient_id', 'encounter_id', 'record_status', 'completeness', 'event_at', 'known_at',
                   'template_label'}}
ACTION_FIELDS = {
    'IND-DEMO-1': {'line_id', 'station_id', 'unit_id', 'batch_id', 'inspection_cycle', 'phase', 'route'},
    'MED-DEMO-1': {'synthetic_patient_id', 'encounter_id', 'order_group_id', 'phase', 'template_id', 'record_ref',
                   'destination_system'}}
ROLES = {'IND-DEMO-1': {'H': 'HOLDER', 'G': 'ISSUER', 'X': 'EXECUTOR', 'U': 'LINE_OPERATOR', 'V': 'QUALITY_REVIEWER',
                        'E': 'SOURCE'},
         'MED-DEMO-1': {'H': 'HOLDER', 'G': 'ISSUER', 'X': 'EXECUTOR', 'U': 'MEDICAL_AUTHORIZER',
                        'V': 'CLINICAL_REVIEWER', 'E': 'SOURCE'}}
PURPOSES = {'H': ['IssueRequest', 'ChallengeRequest', 'CommitProof', 'StatusQuery', 'READ'],
            'G': ['Permit', 'Result', 'READ'], 'X': ['Challenge', 'Acceptance', 'Result', 'READ'],
            'U': ['Authorization', 'READ'], 'V': ['Review', 'READ'], 'E': ['SOURCE', 'READ']}


def _json(obj): return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _pub(k): return k.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _clone(obj): return json.loads(_json(obj))


def _rowkey(ns, key): return _json([ns, key])


def _rec(profile, kind, scope, value): return {'version': '2.6', 'profile': profile, 'kind': kind, 'scope': scope, 'value': value}
