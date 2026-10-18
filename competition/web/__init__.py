"""The trusted side's HTTP entry, and who may open a session on it.

``app``
    :func:`~competition.web.app.make_app` -- the minimal interface carried over
    HTTP, with a session in front and every body held to one exact field set.
``session``
    :class:`~competition.web.session.Sessions` -- a caller proves the key it
    holds once and carries a bearer token after; the deployment's caller list
    decides who may open a session and which side of the flow it may drive.

Three things this layer deliberately is not.  It is not a second protocol: every
route calls the same ``TrustedService`` the command line calls, and the
signatures still travel in the body.  It is not a signer: no route here produces
a business signature, and only the endpoints can.  And it is not where
initialization, enrollment or the internal read steps live -- the interface
reference rules those out as unauthenticated external routes, and they are not
the entry's to publish.
"""
