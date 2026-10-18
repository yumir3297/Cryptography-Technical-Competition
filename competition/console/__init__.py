"""The human console: the two sides of the flow, with a page in front of them.

The flow has two sides and the entry says so: the holder proposes and reads, the
worker claims, executes and settles, and neither stands in for the other.  This
package is those two sides presented as one page -- the caller side of
:mod:`competition.web`, reached the way any caller reaches it.

It is deliberately not part of the trusted side.  A caller holds its own key and
makes no business signature; the trusted entry holds no caller's key.  So the
console is its own service with its own two credentials, and the page talks to it
rather than to the entry.

Three pieces:

``control``
    :class:`~competition.console.control.Console` -- the holder and worker
    callers, the credentials they announce, and the few calls a page makes.
``app``
    :func:`~competition.console.app.make_app` and ``serve`` -- the HTTP face:
    the page's own JSON calls, and the built page itself.
``__main__``
    the process entry point.

No protocol is defined here.  Every call is one
:class:`~competition.caller.flow.Caller` call, and every signature still comes
from the endpoint that owns its step.
"""
