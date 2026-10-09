"""Executable *proposed* DENY-range guard. NOT a ZJJ backend transaction.

Models one W-linearizable ApprovalIndex with a predicate version; it demonstrates
why reading only caller-submitted Review refs cannot protect against a concurrent
newly published DENY. Real implementations must provide SERIALIZABLE predicate
protection / range-version CAS across control-publish and Commit.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ReadWitness:
    basis: str
    purpose: str
    publish_revision: int
    approved: bool


class ApprovalIndex:
    def __init__(self):
        self.events = []
        self.version = {}   # (basis,purpose) -> monotone integer
        self.accepted = set()

    def publish(self, basis, purpose, verdict, subject):
        if verdict not in ('APPROVE','DENY'):
            raise ValueError('VERDICT')
        key=(basis,purpose)
        self.version[key] = self.version.get(key,0)+1
        self.events.append((key, verdict, subject, self.version[key]))

    def prepare(self, basis, purpose):
        key=(basis,purpose)
        current=[e for e in self.events if e[0]==key]
        approve=any(e[1]=='APPROVE' for e in current)
        deny=any(e[1]=='DENY' for e in current)
        return ReadWitness(basis,purpose,self.version.get(key,0),approve and not deny)

    def commit(self, witness, operation, valid_independent_u=True):
        key=(witness.basis,witness.purpose)
        # A separate manager must serialize this predicate read/CAS and the
        # publication itself; sequential model demonstrates required outcome.
        if self.version.get(key,0)!=witness.publish_revision:return 'STALE'
        if not witness.approved or not valid_independent_u:return 'REJECT'
        if operation in self.accepted:return 'EXISTING'
        self.accepted.add(operation)
        return 'ACCEPTED'

    def naive_selected_refs_only(self, selected_approve_present, operation):
        # Intentional flawed baseline; counterexample demonstration only.
        if selected_approve_present:
            self.accepted.add(operation)
            return 'ACCEPTED'
        return 'REJECT'
