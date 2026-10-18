"""Trusted side of the ZJJ-CORE demonstration: orchestrator + Resolver + W.

The diagram's three trusted lanes -- 受信编排器, Resolver and W -- run here as one
process.  The package exposes the *challenge/signature interface* a caller (or an
external role client) uses: the service hands out a core challenge and accepts the
proof back; it never signs on a caller's behalf.  This round a local signer
answers those challenges so the three normal paths run before the external role
clients are connected; the interface itself is unchanged when they are.
"""
