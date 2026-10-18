"""The agent-side boundary: an MCP entry for candidates and status, plus a push feed.

The agent does not sign, approve, claim or execute.  It proposes a business
intent through :class:`~competition.agent.service.GatewayService`; the trusted
side decides, and two independent callers (``operator`` and ``executor``) walk
the H and worker sides of the flow.  This package owns only the agent-facing
gateway, its journal, and the MCP surface.  The dsh plugin that feeds status back
into a session lives beside it in ``dsh-plugin/``.
"""
