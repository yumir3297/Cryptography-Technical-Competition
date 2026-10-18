"""The deployment: one machine, a handful of services, and what each one runs.

``endpoints``
    the signing services, one process per endpoint, each with its own key
    (:mod:`competition.deploy.endpoints`).
``trusted``
    the trusted entry: the W itself, initialized once against those endpoints
    (:mod:`competition.deploy.trusted`).
``caller_h`` / ``caller_worker``
    the two sides of the flow, each with a credential of its own
    (:mod:`competition.deploy.demo`).
``operator`` / ``executor``
    the independent H-side and worker-side callers that drive an operation the
    agent gateway submitted (:mod:`competition.deploy.operator` and
    :mod:`competition.deploy.executor`).
``caddy``
    the one external door.

Everything here is packaging.  What each service runs is the same code the rest
of the repository is tested through; the deployment adds addresses, volumes and a
start-up order, and no protocol.

The one thing worth stating outright, because it looks like a shortcut and is not:
the trusted side can read the endpoints' key files, and the X receipt child and
the tool child do read theirs.  The repository defines process separation as
"responsibility constraint and fault reproduction" rather than permission
isolation, puts the trusted OS and file manager outside the attacker set, and says
outright that this is a development condition and not a place to add facility
(FINAL_PROTOCOL_HANDOFF's scope notes, N-01, and
``competition/docs/final/security-boundaries.md``).  So this deployment does what
that asks and no more.
"""
from competition.core.trusted_state import PROFILE_SCOPES
from competition.server.roster import ALIASES


def places():
    """Every endpoint on this machine, in the order the manifest lists them.

    The worker is one capability across the profiles and a tool exists once per
    profile, so the ones with a face are the eighteen aliases plus the worker, and
    the three tools are credentials without a service.
    """
    for profile in sorted(PROFILE_SCOPES):
        for role in ALIASES:
            yield profile, role
    yield None, 'worker'
    for profile in sorted(PROFILE_SCOPES):
        yield profile, 'tool'


def serves(role):
    """The tool has no face of its own: the trusted side runs it as a child process."""
    return role != 'tool'


def expected_manifest():
    """How many lines a complete manifest has."""
    return sum(1 for _ in places())
