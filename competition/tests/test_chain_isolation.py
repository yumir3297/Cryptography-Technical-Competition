"""Architecture guard for the official CommonW chain.

The repository once carried two parallel W implementations: the shared
competition core (``core/common_w.py`` and friends) and an earlier set of
research vertical slices (scene/pay acceptance and recovery).  The slices have
been retired; this test keeps them retired by asserting that production code no
longer reaches them, directly or transitively.
"""
import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Modules that belonged to the retired research vertical-slice chain.
LEGACY = frozenset({
    'competition.core.acceptance',
    'competition.core.industrial_authorization_bridge',
    'competition.core.trusted_clock',
    'competition.support.scene_authority',
    'competition.support.scene_recovery',
    'competition.support.scene_verifier',
    'competition.support.durable_pay',
    'competition.support.dispatch_guard',
    'competition.support.pay_recovery',
    'competition.support.authority_guards',
    'competition.support.legacy_clock',
    'competition.support.scene_fixtures',
    'competition.profiles.industrial_seed',
})

# Entry points of the three official competition demonstration paths.
ENTRIES = ('competition.run_w_slice', 'competition.run_security_checks')


def _module_file(module):
    path = ROOT.joinpath(*module.split('.'))
    for candidate in (path.with_suffix('.py'), path / '__init__.py'):
        if candidate.is_file():
            return candidate
    return None


def _imports_of(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('competition'):
            found.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith('competition'):
                    found.add(alias.name)
    return found


def _closure(entries):
    seen, pending = set(), list(entries)
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        path = _module_file(module)
        if path is None:
            continue
        for dependency in _imports_of(path):
            if dependency not in seen:
                pending.append(dependency)
    return seen


class ChainIsolation(unittest.TestCase):
    def test_entry_closure_is_legacy_free(self):
        closure = _closure(ENTRIES)
        leaked = sorted(closure & LEGACY)
        self.assertEqual(leaked, [], f'official entry points still depend on legacy modules: {leaked}')

    def test_no_production_import_of_legacy(self):
        offenders = {}
        for path in (ROOT / 'competition').rglob('*.py'):
            relative = path.relative_to(ROOT).as_posix()
            if '__pycache__' in path.parts or '/evidence/' in relative or path.name.startswith('test_'):
                continue
            module = relative[:-3].replace('/', '.')
            if module in LEGACY:
                continue
            for dependency in _imports_of(path):
                if dependency in LEGACY:
                    offenders.setdefault(dependency, []).append(relative)
        self.assertEqual(offenders, {}, f'production code imports retired modules: {offenders}')


if __name__ == '__main__':
    unittest.main()
