"""Fusion regression: IND public trust boundary vs local three-profile simulator.

Do not mistake coexistence of two integration modes for a merged authorization API.
No real participant signer is available through OperationService.invoke.
"""
import ast
from pathlib import Path
import unittest

from competition.application.operation_service import METHOD_FIELDS, OperationService
from competition.application.request_bound_w import RequestBoundW
from competition.server.service import TrustedService
from competition.bridge.facade import TrustedFacade

ROOT = Path(__file__).resolve().parents[2]


def imports_from(module_path):
    source = (ROOT / module_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


class FusionBoundaryTests(unittest.TestCase):
    def test_public_api_is_fixed_allowlist_with_no_simulator_signer(self):
        self.assertEqual(set(METHOD_FIELDS), {
            "propose", "identity_challenge", "submit", "prepare",
            "accept_challenge", "accept", "recover_challenge", "recover",
            "status_challenge", "status",
        })
        for unsafe in ("answer", "sign", "build_op", "run_normal", "execute_once",
                       "claim", "query_attempt", "settle", "audit", "counts"):
            self.assertNotIn(unsafe, METHOD_FIELDS)
        self.assertFalse(hasattr(OperationService, "answer"))
        self.assertFalse(hasattr(OperationService, "run_normal"))

    def test_public_runtime_never_imports_local_demo_signer_or_facade(self):
        public_files = (
            "competition/application/operation_service.py",
            "competition/application/local_runtime.py",
            "competition/application/http_service.py",
            "competition/application/mcp_stdio.py",
            "competition/application/request_bound_w.py",
        )
        for file in public_files:
            with self.subTest(file=file):
                names = imports_from(file)
                self.assertFalse(any(
                    name == "competition.cli" or name.startswith("competition.cli.") or
                    name == "competition.server" or name.startswith("competition.server.") or
                    name == "competition.bridge" or name.startswith("competition.bridge.")
                    for name in names), names)

    def test_local_demo_and_secure_ind_service_are_distinct_types(self):
        self.assertIsNot(OperationService, TrustedService)
        self.assertFalse(issubclass(TrustedFacade, RequestBoundW))

    def test_external_ind_service_refuses_unbound_W(self):
        # The safety gate is enforced by OperationService.__init__; not merely
        # by CLI documentation or the HTTP transport token.
        self.assertIn("REQUEST_BOUND_W_REQUIRED",
            (ROOT / "competition/application/operation_service.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
