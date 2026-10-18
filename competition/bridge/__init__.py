"""Same-process bridge shell: an explicit interface over the trusted core.

Frontends and bridges depend on :mod:`competition.bridge.contract`; the concrete
:class:`competition.bridge.facade.TrustedFacade` exposes the core's own
challenge/signature steps verbatim and adds one assembly method, ``build_op``.
The caller owns its keys, answers challenges itself and passes proofs back; the
shell never signs on the caller's behalf.  No existing module, wire field or
protocol byte is modified by this package.
"""
