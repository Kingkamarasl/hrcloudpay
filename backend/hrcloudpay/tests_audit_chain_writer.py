"""Sealing audit rows on write, and the one-time backlog command.

`verify_chain` was already covered thoroughly by hrcloudpay/tests_audit_chain.py.
What is new here is the writer side and its edge cases: that a normal audit write
is chained, that editing a row does NOT silently re-seal it, that bulk_create is
still detectable as unchained, and that the backlog command reports honestly
about what it cannot retroactively guarantee.
"""
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase

from accounts.audit import audit
from accounts.audit_chain import GENESIS_HASH, compute_integrity_hash, verify_chain
from accounts.platform_models import AuditChainState, AuditLog


class SealingOnWriteTests(TestCase):
    def test_the_audit_helper_seals_what_it_writes(self):
        audit(message='salary updated', target_type='employee', target_id='7')

        row = AuditLog.objects.get()
        self.assertEqual(row.chain_sequence, 1)
        self.assertEqual(row.previous_hash, GENESIS_HASH)
        self.assertTrue(row.integrity_hash)

    def test_successive_writes_link_to_each_other(self):
        for i in range(4):
            audit(message=f'event {i}')

        rows = list(AuditLog.objects.order_by('chain_sequence'))
        self.assertEqual([r.chain_sequence for r in rows], [1, 2, 3, 4])
        for previous, current in zip(rows, rows[1:]):
            self.assertEqual(current.previous_hash, previous.integrity_hash)

    def test_the_chain_verifies_after_real_writes(self):
        for i in range(6):
            audit(message=f'event {i}', metadata={'n': i})

        result = verify_chain()

        self.assertTrue(result['ok'], result['problems'])
        self.assertEqual(result['checked'], 6)

    def test_the_stored_digest_matches_a_recomputation(self):
        """The writer and the verifier must agree on every field and coercion."""
        audit(message='leave approved', metadata={'days': '2'})

        row = AuditLog.objects.get()
        self.assertEqual(compute_integrity_hash(row), row.integrity_hash)

    def test_an_update_does_not_reseal(self):
        """Re-sealing on update would let anyone edit history undetected.

        If save() recomputed the digest, an actor with ORM access could change a
        salary-change message and leave the chain still verifying - which is the
        one thing an append-only log exists to prevent.
        """
        row = AuditLog.objects.create(action='salary_change', message='original')
        row.message = 'rewritten'
        row.save()

        row.refresh_from_db()
        result = verify_chain()

        self.assertNotEqual(row.integrity_hash, compute_integrity_hash(row))
        self.assertFalse(result['ok'])
        self.assertIn('hash_mismatch', [p['kind'] for p in result['problems']])

    def test_bulk_create_is_still_reported_as_unchained(self):
        """bulk_create bypasses save(), and must stay detectable."""
        AuditLog.objects.bulk_create([
            AuditLog(action='system', message='smuggled'),
        ])

        result = verify_chain()

        self.assertFalse(result['ok'])
        self.assertIn('unchained_record', [p['kind'] for p in result['problems']])

    def test_concurrent_writers_cannot_share_a_sequence(self):
        """The head is locked, so two writers serialise rather than collide."""
        from django.db import transaction

        with transaction.atomic():
            first = AuditLog.objects.create(action='system', message='a')
        with transaction.atomic():
            second = AuditLog.objects.create(action='system', message='b')

        self.assertNotEqual(first.chain_sequence, second.chain_sequence)
        self.assertEqual(
            sorted([first.chain_sequence, second.chain_sequence]), [1, 2])

    def test_the_head_state_tracks_the_last_record(self):
        audit(message='one')
        audit(message='two')

        state = AuditChainState.objects.get(key='global')
        self.assertEqual(state.last_sequence, 2)
        self.assertEqual(state.last_hash, AuditLog.objects.get(
            chain_sequence=2).integrity_hash)

    def test_the_first_write_on_a_migrated_database_is_sequence_one(self):
        """0005_tamper_evident_audit creates the head row at sequence 0."""
        state = AuditChainState.objects.get(key='global')
        self.assertEqual(state.last_sequence, 0)
        self.assertEqual(state.last_hash, GENESIS_HASH)

        audit(message='first after migration')

        self.assertEqual(AuditLog.objects.get().chain_sequence, 1)


class SealBacklogCommandTests(TestCase):
    def _unchained(self, count=3):
        """Rows that bypassed save(), the way a pre-writer database has."""
        AuditLog.objects.bulk_create([
            AuditLog(action='system', message=f'legacy {i}')
            for i in range(count)
        ])

    def test_dry_run_writes_nothing(self):
        self._unchained()
        out = StringIO()

        call_command('seal_audit_backlog', '--dry-run', stdout=out)

        self.assertEqual(AuditLog.objects.filter(chain_sequence__isnull=True).count(), 3)
        self.assertIn('Would seal 3', out.getvalue())

    def test_it_seals_the_backlog_so_the_chain_verifies(self):
        self._unchained()

        out = StringIO()
        call_command('seal_audit_backlog', stdout=out)

        self.assertEqual(AuditLog.objects.filter(chain_sequence__isnull=True).count(), 0)
        self.assertTrue(verify_chain()['ok'], verify_chain()['problems'])
        # The command must not imply it verified rows it could not have.
        self.assertIn('were not verified at the time', out.getvalue())

    def test_it_says_so_when_there_is_nothing_to_do(self):
        out = StringIO()
        call_command('seal_audit_backlog', stdout=out)

        self.assertIn('nothing to do', out.getvalue())

    def test_it_leaves_already_sealed_rows_alone(self):
        audit(message='already sealed')
        self._unchained(2)

        call_command('seal_audit_backlog', stdout=StringIO())

        sealed_first = AuditLog.objects.get(chain_sequence=1)
        self.assertEqual(sealed_first.message, 'already sealed')
        self.assertTrue(verify_chain()['ok'], verify_chain()['problems'])