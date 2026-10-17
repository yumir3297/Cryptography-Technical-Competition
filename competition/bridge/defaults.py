"""Wire fields the bridge shell fills in; a caller supplies intent only.

The concrete values are the trusted demonstration corpus created by
``competition.profiles.w_seed.initialize`` (``WRun.operations``), which the
trusted bootstrap has already bound to the fixed schemas.  This module therefore
records *which* fields the shell owns instead of copying their values, so the
trusted corpus stays the single source of truth and cannot drift from it.
"""

# The only caller-facing input.  Everything else is filled by the shell.
CALLER_INTENT_FIELDS = ('profile', 'operation_id')

# Filled by the shell from the trusted fixed corpus, never taken from the caller.
SHELL_FILLED_ACTION_FIELDS = (
    'scope', 'holder', 'holder_kid', 'executor',
    'tool', 'tool_version', 'destination', 'payload',
)

# Re-derived by the core on every guard.  The shell backfills the exact
# recomputed values (via the trusted adapter) rather than accepting caller
# copies, which the guard would reject with BINDING / ASSESSMENT_MISMATCH.
CORE_REDERIVED_OP_FIELDS = ('ctx', 'required', 'deps', 'basis', 'assessment')

# Signed by the trusted bootstrap; never a caller input.
TRUSTED_SIGNED_OP_FIELDS = (
    'reviews', 'authorization', 'issue', 'permit',
    'challenge_request', 'challenge', 'proof',
)
