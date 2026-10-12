"""Document the current real-time acceptance blocker, without claiming a fix."""
import tempfile
import unittest
from pathlib import Path

from competition.support.scene_fixtures import build_scene, prepare_approved
from competition.support.authority_guards import HardenedSceneW
from competition.support.scene_verifier import VerifierOnlySceneW
from competition.support.tool_final import Controller
from competition.support.legacy_clock import seal
from competition.support.wire import ProtocolError, sid


class NonZeroLatencyKnownGap(unittest.TestCase):
    def test_legacy_scene_finalization_rejects_one_second_elapsed(self):
        for profile in ("IND-DEMO-1", "MED-DEMO-1"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as td:
                issuer, action, task, scene, _ = build_scene(
                    Path(td) / "w.sqlite", profile, authority_class=HardenedSceneW,
                )
                op = prepare_approved(issuer, action, task, scene)
                w = VerifierOnlySceneW(
                    Path(td) / "w.sqlite", profile,
                    root_public=issuer.root_public, actors=issuer.actors,
                )
                c = Controller(issuer.controller)
                oid = action["operation_id"]
                req = w.prepare_accept(
                    op, clock=seal(c, profile, w.scope, oid, "PREPARE", 1, 106, 106),
                )
                signed = issuer.actors["X"].sign(
                    profile, "Acceptance", w.scope, req["acceptance_payload"],
                    refs=req["refs"], aud=req["aud"], at=req["signed_at"],
                    iid=sid(106008),
                )
                # Signed C time advances by just one second. The legacy verifier
                # MUST fail closed, but this is a DELIVERY BLOCKER, not a PASS.
                with self.assertRaises(ProtocolError) as caught:
                    w.finalize_accept(
                        req["ticket"], signed,
                        clock=seal(c, profile, w.scope, oid, "FINALIZE", 2, 107, 107),
                    )
                self.assertEqual(caught.exception.code, "TIME_CHANGED")
                self.assertEqual(w.snapshot()["accepts"], 0)
                self.assertEqual(w.snapshot()["reserved"], 0)


if __name__ == "__main__":
    unittest.main()
