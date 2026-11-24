"""Reusable evaluation scenarios built through the real C/W/tool paths."""
import copy
import json
import tempfile
from pathlib import Path

from competition.profiles.w_scenarios import register_ind_unit
from competition.support.goal_seed import goal_claim, publish_goal

IND = 'IND-DEMO-1'


def ind_three_actions(run):
    second = register_ind_unit(run, unit_id='unit-b', batch_id='batch-b',
                               principal='principal-b')
    third = register_ind_unit(run, unit_id='unit-c', batch_id='batch-c',
                              principal='principal-c')
    second = run.fork_operation(IND, second)
    third = run.fork_operation(IND, third)
    first = run.fork_operation(IND)
    return first, second, third


def ind_goal(run, ops, *, group='goal-1', capacity=2, epoch='1'):
    rules = [{'name': 'inspect-a', 'op': ops[0], 'obligation': 'unit-a', 'cost': 1},
             {'name': 'inspect-b', 'op': ops[1], 'obligation': 'unit-b', 'cost': 1},
             {'name': 'inspect-c', 'op': ops[2], 'obligation': '', 'cost': 1}]
    claim = goal_claim(run, IND, group, rules, capacity=capacity, epoch=epoch)
    publish_goal(run, IND, claim)
    return claim


def accept(run, profile, op):
    ticket = run.w.prepare(profile, op, run.identity_proof(profile, op))
    return run.w.accept(profile, ticket['ticket_id'],
                        run.accept_proof(profile, ticket['ticket_id']))


def execute_and_settle(run, profile, op):
    oid = op['action']['operation_id']
    run.w.claim(profile, oid, run.worker_proof(profile, oid, 'CLAIM'))
    response = run.w.execute_once(profile, oid, run.worker_proof(profile, oid, 'EXECUTE'))
    settled = run.w.settle(profile, oid, response, run.worker_proof(profile, oid, 'SETTLE'))
    return response, settled


def goal_package(run, ops, *, mode='enforce'):
    """Accept, execute and settle the first required action under an active goal."""
    accept(run, IND, ops[0])
    response, settled = execute_and_settle(run, IND, ops[0])
    return ops[0]['action']['operation_id']
