"""Same-process bridge shell: a minimal abstract interface over the trusted core.

Frontends and bridges depend on :mod:`competition.bridge.contract`; the concrete
:class:`competition.bridge.facade.TrustedFacade` adapts the unchanged trusted
initialization, CommonW and candidate ingress.  No existing module, wire field or
protocol byte is modified by this package.
"""
