"""What an agent may propose, and nothing else.

The trusted entry already accepts only the business fields of a profile, then
fills scope, principals, holders, tool, destination, task and scene key from the
profile corpus.  This module repeats that rule at the agent boundary so a model
gets a precise, bounded error before a request reaches the trusted side.

There is deliberately no field for a role, a key, an approval, a permit, a tool,
a scope or an operation id.  A candidate that carries one is refused rather than
silently stripped.
"""
import hashlib
import re

from competition.server.service import INTENT_FIELDS
from competition.support.scene_contract import DEST
from competition.support.wire import canonical

# The model-facing catalogue.  Descriptions are deliberately short: the tool
# result is context the model pays for on every turn.
PROFILES = {
    'IND-DEMO-1': {
        'scenario': 'industrial',
        'summary': 'Industrial line sort: propose a route for one unit in one inspection cycle.',
        'fields': ('line_id', 'station_id', 'unit_id', 'batch_id',
                   'inspection_cycle', 'phase', 'route'),
    },
    'PAY-1': {
        'scenario': 'payment',
        'summary': 'Synthetic payment: propose one order settlement in minor currency units.',
        'fields': ('order_id', 'stage', 'payer', 'payee', 'amount_minor'),
    },
    'MED-DEMO-1': {
        'scenario': 'medical',
        'summary': 'Synthetic medical order: propose one order group for a patient encounter.',
        'fields': ('synthetic_patient_id', 'encounter_id', 'template_id'),
    },
}

FIELD_DESCRIPTIONS = {
    'line_id': 'Production line identifier.',
    'station_id': 'Station identifier.',
    'unit_id': 'Unit identifier.',
    'batch_id': 'Batch identifier.',
    'inspection_cycle': 'Inspection cycle number, decimal text.',
    'phase': 'Inspection phase, for example INITIAL.',
    'route': 'One of RELEASE, QUARANTINE, INSPECT.',
    'order_id': 'Order identifier.',
    'stage': 'Order stage, for example pay.',
    'payer': 'Payer account label.',
    'payee': 'Payee account label.',
    'amount_minor': 'Positive integer amount in minor units, as decimal text.',
    'synthetic_patient_id': 'Synthetic patient identifier.',
    'encounter_id': 'Synthetic encounter identifier.',
    'template_id': 'Fixed template identifier; the trusted adapter recomputes its binding.',
}

# The route values the industrial adapter accepts.  Imported rather than copied
# so a changed destination table cannot leave the agent with a stale enum.
ROUTES = tuple(sorted(DEST))

# The field each profile uses for a positive integer, if any.
POSITIVE_INT = {'amount_minor': re.compile(r'0|[1-9][0-9]*')}


class PolicyError(ValueError):
    """A candidate or a step refused at the agent boundary."""

    def __init__(self, code, message=None):
        self.code = code
        self.message = message or code
        super().__init__(self.message)


def profiles():
    """The catalogue as plain JSON-ready data."""
    rows = []
    for profile in sorted(PROFILES):
        row = PROFILES[profile]
        rows.append({
            'profile': profile,
            'scenario': row['scenario'],
            'summary': row['summary'],
            'intent_fields': [
                {'name': name,
                 'type': 'string',
                 'required': True,
                 'description': FIELD_DESCRIPTIONS.get(name, '')}
                for name in row['fields']
            ],
        })
    return rows


def _check_text(profile, name, value):
    if type(value) is not str:
        raise PolicyError('INTENT_FIELD_TYPE', '%s.%s must be a string' % (profile, name))
    if not 1 <= len(value) <= 128:
        raise PolicyError('INTENT_FIELD_LENGTH',
                          '%s.%s must be 1..128 characters' % (profile, name))
    if value != value.strip() or not value.isascii() or not value.isprintable():
        raise PolicyError('INTENT_FIELD_CHARS',
                          '%s.%s must be trimmed printable ASCII' % (profile, name))
    return value


def validate_intent(profile, intent):
    """Return a detached, validated intent; refuse anything the adapter cannot bind.

    Every field the profile lists is required.  The trusted side could fill a
    missing field from its seeded template, but a candidate that omits it would
    then be proposing a value the model never saw.  Requiring the complete
    business intent keeps the proposal honest and makes the journal digest
    meaningful.
    """
    if profile not in INTENT_FIELDS:
        raise PolicyError('PROFILE', 'unknown profile: %r' % (profile,))
    if type(intent) is not dict:
        raise PolicyError('INTENT_FIELDS', 'intent must be an object')
    expected = set(INTENT_FIELDS[profile])
    unknown = sorted(set(intent) - expected)
    if unknown:
        raise PolicyError('INTENT_FIELDS',
                          'unknown intent field(s): %s' % ', '.join(unknown))
    missing = sorted(expected - set(intent))
    if missing:
        raise PolicyError('INTENT_FIELDS',
                          'missing intent field(s): %s' % ', '.join(missing))
    clean = {}
    for name in INTENT_FIELDS[profile]:
        value = _check_text(profile, name, intent[name])
        if name in POSITIVE_INT:
            if not POSITIVE_INT[name].fullmatch(value) or int(value) <= 0:
                raise PolicyError('INTENT_AMOUNT',
                                  '%s.amount_minor must be a positive decimal integer' % profile)
            if int(value) > 9223372036854775807:
                raise PolicyError('INTENT_AMOUNT', 'amount_minor is too large')
        if name == 'route' and value not in ROUTES:
            raise PolicyError('INTENT_ROUTE', 'route must be one of ' + ', '.join(ROUTES))
        clean[name] = value
    return clean


def intent_digest(profile, intent):
    """One stable identity for a business intent, for duplicate suppression."""
    return hashlib.sha256(canonical({'profile': profile, 'intent': intent})).hexdigest()


# The steps this gateway is allowed to call.  It is a constant, not a
# configuration value: a deployment may not widen the agent boundary by setting
# an environment variable.  prepare/accept/claim/exec/settle/cancel belong to
# the independent operator and executor processes.  There is no full audit
# either: the H audit projection carries the COMMIT and business payload, and
# the agent gets reference-level evidence from the ``zjj_status`` view instead.
ALLOWED_STEPS = frozenset({'status'})

# The one step the agent boundary may trigger itself, plus the read steps above.
# ``submit`` is not in STEPS; it is the propose path.
def require_step(step):
    if step not in ALLOWED_STEPS:
        raise PolicyError('AGENT_STEP', 'the agent gateway may not drive %r' % (step,))
    return step
