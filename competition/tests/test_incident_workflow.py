"""Fourth workflow: security incident response on the common W core.

The official R2 wire profile is reused (IND-DEMO-1); the business layer adds a
C-certified INCIDENT record, a second signed containment tool ledger and a
priority GoalFloor.  It is deliberately reported as a workflow extension, not a
new official R2 Profile.
"""
import json
import tempfile
import unittest
from pathlib import Path

from competition.core.trusted_state import prefix
from competition.evaluation.fixtures import accept, execute_and_settle
from competition.evaluation.incident import (incident_action, install_incident_tool,
                                             publish_incident, set_incident_status)
from competition.evaluation.package import build_anchor, build_package
from competition.evaluation.verify import verify_package
from competition.profiles.w_seed import initialize
from competition.support.goal_seed import current_goal, goal_claim, publish_goal, update_goal
from competition.support.wire import ProtocolError

P = 'IND-DEMO-1'
ROOT = Path(__file__).resolve().parents[2]


class IncidentWorkflowTests(unittest.TestCase):
    def test_priority_containment_state_change_and_offline_audit(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT / '.runtime')
        self.addCleanup(folder.cleanup)
        run = initialize(Path(folder.name), resource_capacity={P: 2}, goal_mode='enforce')
        self.addCleanup(run.close)
        install_incident_tool(run)
        critical_a = publish_incident(run, incident_id='inc-001', asset='asset-db-01',
                                      severity='CRITICAL')
        critical_b = publish_incident(run, incident_id='inc-002', asset='asset-db-02',
                                      severity='CRITICAL')
        low = publish_incident(run, incident_id='inc-003', asset='asset-web-03', severity='LOW')
        a = incident_action(run, incident=critical_a, principal='soc-a')
        b = incident_action(run, incident=critical_b, principal='soc-b')
        c = incident_action(run, incident=low, principal='soc-c')
        a = run.fork_operation(P, a)
        b = run.fork_operation(P, b)
        c = run.fork_operation(P, c)
        with run.store.db() as db:
            resource = json.loads(db.execute(
                "SELECT key FROM w_resource WHERE profile=? AND key LIKE '%quarantine%'",
                (P,)).fetchone()[0])
        rules = [{'name': 'contain-db1', 'op': a, 'obligation': 'contain-db1', 'cost': 1},
                 {'name': 'contain-db2', 'op': b, 'obligation': 'contain-db2', 'cost': 1},
                 {'name': 'contain-web3', 'op': c, 'obligation': '', 'cost': 1}]
        incident_ids = ['inc-001', 'inc-002', 'inc-003']
        publish_goal(run, P, goal_claim(run, P, 'incident-priority', rules, capacity=2,
                                        resource_key=resource, unit='UNIT',
                                        incident_deps=incident_ids))

        # A locally legal low-priority containment is stopped by the certified
        # capacity reserved for the two critical incidents.
        before = run.w.counts()
        with self.assertRaises(ProtocolError) as error:
            accept(run, P, c)
        self.assertEqual(error.exception.code, 'GOAL_CAPACITY_FLOOR')
        self.assertEqual(run.w.counts(), before)

        # Critical containment completes and C advances the incident state.
        accept(run, P, a)
        execute_and_settle(run, P, a)
        set_incident_status(run, critical_a, 'CONTAINED')
        with run.store.db() as db:
            self.assertEqual(run.store.current(db, P, 'INCIDENT', prefix(P) + ['inc-001'])
                             ['record']['value']['status'], 'CONTAINED')

        # The old GoalFloor bound the incident's previous ref; it is now stale.
        with self.assertRaises(ProtocolError) as error:
            accept(run, P, b)
        self.assertEqual(error.exception.code, 'GOAL_DEPS_STALE')
        self.assertEqual(run.w.counts()['accepts'], 1)

        # C re-certifies epoch 2 against the current incident state, and the
        # remaining critical containment becomes admissible.
        current, revision = current_goal(run, P, 'incident-priority')
        epoch2 = goal_claim(run, P, 'incident-priority', rules, capacity=2,
                            resource_key=resource, unit='UNIT', epoch=str(revision + 1),
                            incident_deps=incident_ids)
        update_goal(run, P, 'incident-priority', epoch2)
        accept(run, P, b)
        execute_and_settle(run, P, b)
        set_incident_status(run, critical_b, 'CONTAINED')

        oid = b['action']['operation_id']
        package = build_package(run, P, oid)
        anchor = build_anchor(run)
        result = verify_package(package, anchor)
        self.assertEqual(result['status'], 'PASS', json.dumps(result, ensure_ascii=False)[:1200])
        incidents = [c for c in package['controls'] if c['namespace'] == 'INCIDENT']
        self.assertEqual(len(incidents), 3)
        self.assertEqual(run.w.counts()['goal_done'], 2)
        self.assertEqual(run.w.counts()['settlements'], 2)


if __name__ == '__main__':
    unittest.main()
