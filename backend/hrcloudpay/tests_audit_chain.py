"""Regression tests for audit chain verification.

The health check used to report the chain as "healthy" by testing only for
blank `integrity_hash` values, which cannot detect a modified record. These
tests assert the verifier actually catches each tampering class, and - for the
health endpoint - that it reports failure when the chain is broken.

Tests that need to tamper with the chain bypass `save()`/`delete()` on purpose:
that is exactly the hole the verifier exists to close.
"""

import json

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from accounts.audit_chain import GENESIS_HASH, compute_integrity_hash, verify_chain
from accounts.models import Company, User
from accounts.platform_models import AuditChainState, AuditLog


class AuditChainWriteTests(TestCase):
    def test_records_are_linked_into_a_single_chain(self):
        first = AuditLog.objects.create(action='login', message='first')
        second = AuditLog.objects.create(action='logout', message='second')

        self.assertEqual(first.chain_sequence, 1)
        self.assertEqual(first.previous_hash, GENESIS_HASH)
        self.assertEqual(second.chain_sequence, 2)
        self.assertEqual(second.previous_hash, first.integrity_hash)

    def test_fresh_chain_verifies(self):
        for i in range(5):
            AuditLog.objects.create(action='system', message=f'event {i}')

        result = verify_chain()

        self.assertTrue(result['ok'], result['problems'])
        self.assertEqual(result['checked'], 5)

    def test_empty_chain_verifies(self):
        result = verify_chain()

        self.assertTrue(result['ok'], result['problems'])
        self.assertEqual(result['checked'], 0)

    def test_writer_and_verifier_agree_on_the_digest(self):
        """The writer and verifier must not drift: recomputing the stored row
        must reproduce its digest exactly."""
        record = AuditLog.objects.create(
            action='salary_change', message='salary updated', metadata={'amount': 100},
        )
        reloaded = AuditLog.objects.get(pk=record.pk)

        self.assertEqual(compute_integrity_hash(reloaded), reloaded.integrity_hash)


class AuditChainTamperDetectionTests(TestCase):
    """Each test performs the real tampering and asserts the verifier catches it."""

    def setUp(self):
        self.records = [
            AuditLog.objects.create(action='system', message=f'event {i}')
            for i in range(4)
        ]

    def _verify(self):
        return verify_chain()

    def test_modified_message_is_detected(self):
        """The core case: a raw UPDATE of a hashed field."""
        target = self.records[1]
        AuditLog.objects.filter(pk=target.pk).update(message='salary was never changed')

        result = self._verify()

        self.assertFalse(result['ok'])
        kinds = [p['kind'] for p in result['problems']]
        self.assertIn('hash_mismatch', kinds)
        mismatch = next(p for p in result['problems'] if p['kind'] == 'hash_mismatch')
        self.assertEqual(mismatch['sequence'], 2)

    def test_modified_metadata_is_detected(self):
        target = self.records[2]
        AuditLog.objects.filter(pk=target.pk).update(metadata={'approved_by': 'forged'})

        result = self._verify()

        self.assertFalse(result['ok'])
        self.assertIn('hash_mismatch', [p['kind'] for p in result['problems']])

    def test_rewriting_actor_is_detected(self):
        target = self.records[1]
        company = Company.objects.create(name='Acme', email='acme@example.com')
        impostor = User.objects.create(username='impostor', email='i@example.com', company=company)
        AuditLog.objects.filter(pk=target.pk).update(actor_id=impostor.id)

        result = self._verify()

        self.assertFalse(result['ok'])
        self.assertIn('hash_mismatch', [p['kind'] for p in result['problems']])

    def test_deleted_record_breaks_the_link(self):
        """Deleting from the middle leaves a sequence gap and a dangling link."""
        AuditLog.objects.filter(pk=self.records[1].pk).delete()

        result = self._verify()

        self.assertFalse(result['ok'])
        self.assertIn('sequence_gap', [p['kind'] for p in result['problems']])

    def test_truncated_tail_is_detected(self):
        """Deleting only the last records leaves the head state ahead of the data.

        Sequence numbers stay contiguous, so only reconciling against
        AuditChainState catches this.
        """
        AuditLog.objects.filter(pk=self.records[3].pk).delete()

        result = self._verify()

        self.assertFalse(result['ok'])
        self.assertIn('truncated_chain', [p['kind'] for p in result['problems']])

    def test_unchained_record_is_detected(self):
        """bulk_create bypasses save(), so the row never enters the chain."""
        AuditLog.objects.bulk_create([
            AuditLog(action='system', message='smuggled in', integrity_hash='a' * 64),
        ])

        result = self._verify()

        self.assertFalse(result['ok'])
        self.assertIn('unchained_record', [p['kind'] for p in result['problems']])

    def test_forged_head_state_is_detected(self):
        """A DB-level attacker who edits the head state to match a rewritten
        record still leaves the earlier records' links intact-but-divergent."""
        target = self.records[3]
        AuditLog.objects.filter(pk=target.pk).update(message='forged')
        forged = compute_integrity_hash(AuditLog.objects.get(pk=target.pk))
        # A naive attacker updates only the head state, forgetting the link.
        AuditChainState.objects.filter(key='global').update(
            last_hash=forged, last_sequence=target.chain_sequence,
        )

        result = self._verify()

        self.assertFalse(result['ok'])
        self.assertIn('head_state_mismatch', [p['kind'] for p in result['problems']])

    def test_competent_forgery_is_still_detected(self):
        """The case that matters: an attacker with raw DB access who rewrites a
        record's contents AND recomputes that record's own digest, so every
        self-consistency check on the tampered row passes.

        A hash chain protects *backward*, so the tampering shows up as a stale
        back-link on the following record: sequence 3 still points at sequence
        2's original digest. Rewriting sequence 3 too just moves the break one
        record along, and rewriting back to the genesis hash is not something
        the attacker can do without also having to forge the untouched prefix.

        The last record is deliberately NOT used here - it has no successor, so
        its own back-link is the only thing protecting it.
        """
        target = self.records[1]
        AuditLog.objects.filter(pk=target.pk).update(message='salary forged to 1')
        repaired = compute_integrity_hash(AuditLog.objects.get(pk=target.pk))
        AuditLog.objects.filter(pk=target.pk).update(integrity_hash=repaired)

        # The tampered record is now entirely self-consistent...
        self.assertEqual(
            compute_integrity_hash(AuditLog.objects.get(pk=target.pk)),
            AuditLog.objects.get(pk=target.pk).integrity_hash,
        )
        result = self._verify()

        # ...and the forgery is still caught, reported on its successor.
        self.assertFalse(result['ok'])
        broken = next(p for p in result['problems'] if p['kind'] == 'broken_link')
        self.assertEqual(broken['sequence'], 3)

    def test_errors_are_capped(self):
        for record in self.records:
            AuditLog.objects.filter(pk=record.pk).update(message='all rewritten')

        result = verify_chain(max_errors=2)

        self.assertFalse(result['ok'])
        self.assertEqual(len(result['problems']), 2)

    def test_limited_walk_does_not_claim_a_truncation(self):
        """A sampled walk must not report tail truncation it did not check."""
        AuditLog.objects.create(action='system', message='event 4')
        result = AuditLog.objects.count()
        self.assertEqual(result, 5)

        limited = verify_chain(limit=2)

        self.assertTrue(limited['ok'], limited['problems'])
        self.assertTrue(limited['truncated'])
        self.assertEqual(limited['checked'], 2)


class SystemHealthAuditCheckTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='root', email='root@example.com', password='pw-ThatIsLong-1',
        )
        self.client.force_login(self.superuser)

    def test_reports_healthy_on_an_intact_chain(self):
        for i in range(3):
            AuditLog.objects.create(action='system', message=f'event {i}')

        response = self.client.get('/api/auth/platform/system-health/')

        self.assertEqual(response.status_code, 200)
        audit_check = next(c for c in response.json()['checks'] if c['key'] == 'audit')
        self.assertEqual(audit_check['status'], 'healthy')
        self.assertIn('recomputed', audit_check['detail'])

    def test_reports_critical_when_the_chain_is_tampered(self):
        """This is the regression: the old check could not fail here."""
        record = AuditLog.objects.create(action='salary_change', message='salary to 50000')
        AuditLog.objects.filter(pk=record.pk).update(message='salary to 1')

        response = self.client.get('/api/auth/platform/system-health/')

        self.assertEqual(response.status_code, 200)
        audit_check = next(c for c in response.json()['checks'] if c['key'] == 'audit')
        self.assertEqual(audit_check['status'], 'critical')
        self.assertIn('integrity failure', audit_check['detail'].lower())

    def test_security_center_reports_verification_instead_of_a_row_count(self):
        """`immutable_audit_records` was AuditLog.objects.count() - a row count
        presented as immutability."""
        AuditLog.objects.create(action='system', message='event')

        response = self.client.get('/api/auth/platform/security-center/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('immutable_audit_records', payload)
        self.assertEqual(payload['audit_records_total'], 1)
        self.assertTrue(payload['audit_chain_verified'])


class VerifyAuditChainCommandTests(TestCase):
    def test_succeeds_on_an_intact_chain(self):
        for i in range(3):
            AuditLog.objects.create(action='system', message=f'event {i}')

        out = StringIO()
        call_command('verify_audit_chain', stdout=out)

        self.assertIn('Audit chain verified', out.getvalue())

    def test_fails_on_a_tampered_chain(self):
        record = AuditLog.objects.create(action='system', message='original')
        AuditLog.objects.filter(pk=record.pk).update(message='edited')

        err = StringIO()
        with self.assertRaises(CommandError):
            call_command('verify_audit_chain', stderr=err)

        self.assertIn('hash_mismatch', err.getvalue())

    def test_json_output_is_machine_readable(self):
        for i in range(2):
            AuditLog.objects.create(action='system', message=f'event {i}')

        out = StringIO()
        call_command('verify_audit_chain', '--json', stdout=out)

        payload = json.loads(out.getvalue())
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['checked'], 2)
