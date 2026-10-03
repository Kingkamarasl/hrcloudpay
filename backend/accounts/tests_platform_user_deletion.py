"""Tests for the platform-admin user deletion endpoint.

Deleting a User is the most destructive thing this application can do, because
53 relations point at that row. These tests exist to pin the *refusals* far more
tightly than the success path: the failure mode being guarded against is not
that delete stops working, but that it silently starts working on a user whose
payroll approvals or audit entries would be erased with them.

A note on the deactivation test at the end. "Deactivate first" is only a safe
recommendation if deactivating actually revokes access. That is not obvious from
the model, so it is asserted against the real login endpoint and the real session
cookie rather than against `force_authenticate`, which bypasses the
authentication layer entirely and would pass even if deactivation did nothing.
"""
import json
from datetime import date

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Company, User
from accounts.platform_models import AuditLog
from ai.models import AIDraft, KnowledgeDocument
from payroll.models import PayrollRun
from security.models import SecuritySession

PASSWORD = 'StrongPassword123!'


class PlatformUserDeletionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='platformadmin', password=PASSWORD,
            email='platform@example.com', role='owner',
            is_staff=True, is_superuser=True,
        )
        self.company = Company.objects.create(
            name='Acme Ltd', email='acme@example.com', is_active=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def url_for(self, user):
        return reverse('platform-user-detail', args=[user.id])

    def make_user(self, username='tenantuser', **kwargs):
        kwargs.setdefault('company', self.company)
        return User.objects.create_user(
            username=username, password=PASSWORD,
            email=f'{username}@example.com', **kwargs
        )

    def delete_as_admin(self, user, confirm=None):
        """DELETE the target. ``confirm`` defaults to the correct username so
        each test only has to state the confirmation case it cares about."""
        return self.client.delete(
            self.url_for(user),
            data=json.dumps({'confirm_username': user.username if confirm is None else confirm}),
            content_type='application/json',
        )

    # ---- the refusals -------------------------------------------------

    def test_cannot_delete_your_own_account(self):
        response = self.client.delete(self.url_for(self.admin))

        self.assertEqual(response.status_code, 400)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_cannot_delete_the_last_active_superuser(self):
        """Deleting the only superuser would leave nobody able to administer the
        platform, so it is refused and the message names the way out.

        The actor has to be a staff user who is *not* a superuser, otherwise the
        actor themselves counts as an active superuser and the guard never
        engages - the request would be refused by the self-delete rule instead,
        and this test would pass without ever reaching the code it names.
        """
        staff_not_super = self.make_user('staffonly', is_superuser=False)
        staff_not_super.is_staff = True
        staff_not_super.save(update_fields=['is_staff'])

        self.assertEqual(
            User.objects.filter(is_superuser=True, is_active=True).count(), 1)
        self.client.force_authenticate(staff_not_super)

        response = self.delete_as_admin(self.admin)

        self.assertEqual(response.status_code, 400)
        self.assertIn('superuser', response.data['detail'].lower())
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_a_superuser_is_deletable_once_another_one_exists(self):
        """The counterpart to the guard above: the refusal is about being the
        last one, not about being a superuser. Otherwise it would read as
        "superusers can never be deleted", which is a different and wrong rule.
        """
        replacement = self.make_user('secondadmin', is_superuser=True)
        replacement.is_staff = True
        replacement.save(update_fields=['is_staff'])
        self.client.force_authenticate(replacement)

        response = self.delete_as_admin(self.admin)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(pk=self.admin.pk).exists())

    def test_an_inactive_superuser_does_not_count_as_a_replacement(self):
        """Counting only active superusers is the point of the guard. A
        deactivated superuser must not satisfy it, or the platform could be
        left with no usable administrator while the check reports that it is
        fine."""
        dormant = self.make_user('dormantsuper', is_superuser=False)
        dormant.is_superuser = True
        dormant.is_active = False
        dormant.save(update_fields=['is_superuser', 'is_active'])
        staff_not_super = self.make_user('staffonly', is_superuser=False)
        staff_not_super.is_staff = True
        staff_not_super.save(update_fields=['is_staff'])
        self.client.force_authenticate(staff_not_super)

        response = self.delete_as_admin(self.admin)

        self.assertEqual(response.status_code, 400)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_refuses_to_delete_a_user_who_approved_payroll(self):
        approver = self.make_user('payrollapprover')
        PayrollRun.objects.create(
            company=self.company,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
            status='approved', approved_by=approver, approved_at=timezone.now(),
        )

        response = self.delete_as_admin(approver)

        self.assertEqual(response.status_code, 409)
        self.assertTrue(User.objects.filter(pk=approver.pk).exists())
        self.assertEqual(
            PayrollRun.objects.get(approved_by=approver).approved_by, approver,
        )
        blockers = response.data['blockers']
        self.assertTrue(any(b['model'] == 'payroll.PayrollRun' for b in blockers))
        self.assertTrue(all(b['why'] for b in blockers), 'every blocker explains itself')
        self.assertEqual(response.data['alternative']['action'], 'deactivate')

    def test_refuses_to_delete_a_user_named_in_the_audit_log(self):
        actor = self.make_user('auditeduser')
        AuditLog.objects.create(actor=actor, action='login', message='Signed in')

        response = self.delete_as_admin(actor)

        self.assertEqual(response.status_code, 409)
        self.assertTrue(User.objects.filter(pk=actor.pk).exists())
        self.assertEqual(AuditLog.objects.get(actor=actor).actor, actor)

    def test_protected_ai_draft_is_a_409_not_a_500(self):
        """AIDraft.created_by is on_delete=PROTECT.

        Without the blocker check a naive delete() raises ProtectedError and the
        caller gets an opaque 500. This asserts the conflict is caught and
        explained instead.
        """
        author = self.make_user('aidrafter')
        AIDraft.objects.create(
            company=self.company, created_by=author, type='employment_letter',
            title='Offer letter', context='{}', content='Dear candidate',
        )

        response = self.delete_as_admin(author)

        self.assertEqual(response.status_code, 409)
        self.assertTrue(AIDraft.objects.filter(created_by=author).exists())

    def test_protected_knowledge_document_is_a_409_not_a_500(self):
        uploader = self.make_user('kbuser')
        KnowledgeDocument.objects.create(
            company=self.company, created_by=uploader, title='Handbook',
            description='Employee handbook', source_type='document',
            content='Policy text', file_name='handbook.pdf', mime_type='application/pdf',
            extraction_status='complete', is_active=True, lifecycle_status='active',
            version=1, processing_error='', allowed_roles=['hr'],
        )

        response = self.delete_as_admin(uploader)

        self.assertEqual(response.status_code, 409)
        self.assertTrue(KnowledgeDocument.objects.filter(created_by=uploader).exists())

    def test_every_blocker_is_reported_together(self):
        """An administrator fixing this should see the whole picture in one
        response, not discover the payroll blocker after fixing the AI one."""
        approver = self.make_user('busyuser')
        PayrollRun.objects.create(
            company=self.company, period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28), status='approved', approved_by=approver,
        )
        AIDraft.objects.create(
            company=self.company, created_by=approver, type='hr_report',
            title='Quarterly', context='{}', content='Numbers',
        )

        response = self.delete_as_admin(approver)

        self.assertEqual(response.status_code, 409)
        models_named = {b['model'] for b in response.data['blockers']}
        self.assertEqual(models_named, {'payroll.PayrollRun', 'ai.AIDraft'})

    def test_deletion_requires_the_exact_username(self):
        target = self.make_user('confirmme')

        response = self.delete_as_admin(target, confirm='')
        self.assertEqual(response.status_code, 400)

        # A case difference is refused too: the confirmation is a deliberate
        # speed bump, and a near-miss should not slip through it.
        response = self.delete_as_admin(target, confirm='ConfirmMe')
        self.assertEqual(response.status_code, 400)

        response = self.delete_as_admin(target, confirm='someone_else')
        self.assertEqual(response.status_code, 400)

        self.assertTrue(User.objects.filter(pk=target.pk).exists())
        self.assertEqual(response.data['expected_username'], 'confirmme')

    def test_blockers_are_checked_before_confirmation_is_asked_for(self):
        """A user who cannot be deleted should not first be made to type their
        username, because that prompt is never going to succeed."""
        approver = self.make_user('blockedfirst')
        PayrollRun.objects.create(
            company=self.company, period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31), status='approved', approved_by=approver,
        )

        response = self.delete_as_admin(approver, confirm='deliberately-wrong')

        self.assertEqual(response.status_code, 409)

    def test_tenant_user_cannot_delete_anyone(self):
        target = self.make_user('victim')
        tenant_admin = self.make_user('tenantboss', role='owner')
        self.client.force_authenticate(tenant_admin)

        response = self.delete_as_admin(target)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(User.objects.filter(pk=target.pk).exists())

    def test_anonymous_cannot_delete(self):
        target = self.make_user('anonvictim')
        self.client.force_authenticate(None)

        response = self.delete_as_admin(target)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(User.objects.filter(pk=target.pk).exists())

    # ---- the success path ----------------------------------------------

    def test_deletes_a_user_with_no_regulated_history(self):
        target = self.make_user('testaccount')

        response = self.delete_as_admin(target)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(pk=target.pk).exists())
        self.assertEqual(response.data['deleted_user_id'], target.id)

    def test_deleting_a_user_ends_their_security_sessions(self):
        """A deleted user must not keep a working session cookie.

        Asserts the session row is gone rather than that `revoked_at` was set:
        security.SecuritySession.user is on_delete=CASCADE, so the row is
        removed entirely. The view also revokes explicitly before deleting,
        which is belt-and-braces against that FK later being changed to
        SET_NULL, but the observable guarantee - and the only one worth a test -
        is that no session survives.
        """
        target = self.make_user('sessionowner')
        SecuritySession.objects.create(
            user=target, company=self.company, secret_hash='deadbeef',
            expires_at=timezone.now() + timezone.timedelta(days=30),
        )

        self.delete_as_admin(target)

        self.assertFalse(
            SecuritySession.objects.filter(user=target).exists(),
            'no session may outlive the user it authenticates',
        )

    def test_deletion_is_written_to_the_audit_log(self):
        target = self.make_user('deleteme')

        self.delete_as_admin(target)

        entry = AuditLog.objects.filter(
            actor=self.admin, action='delete', target_id=target.id,
        ).first()
        self.assertIsNotNone(entry, 'the deletion itself must leave an audit record')
        self.assertIn('deleteme', entry.message)

    def test_deleting_a_user_does_not_touch_their_company_or_employees(self):
        """Deleting a login must not delete the person. Employee.user is
        SET_NULL, so the employee record survives and simply becomes unlinked -
        which is the point, and worth pinning because 'delete user' reading as
        'delete employee' is an easy and expensive misreading."""
        from employees.models import Employee

        target = self.make_user('emlinked')
        employee = Employee.objects.create(
            company=self.company, user=target,
            first_name='Real', last_name='Person',
        )

        self.delete_as_admin(target)

        employee.refresh_from_db()
        self.assertIsNotNone(employee.pk)
        self.assertIsNone(employee.user_id)
        self.assertTrue(Company.objects.filter(pk=self.company.pk).exists())


class DeactivationRevokesAccessTests(TestCase):
    """The premise behind 'deactivate rather than delete' is that deactivating
    actually revokes access. If it did not, the deletion endpoint would be the
    only real way to remove someone and the safe-recommendation would be a lie.

    Deliberately does not use force_authenticate: that bypasses
    SecurityCookieAuthentication, which is the code that performs the check.
    """

    def setUp(self):
        self.company = Company.objects.create(
            name='Acme Ltd', email='acme@example.com', is_active=True,
        )
        self.user = User.objects.create_user(
            username='sessionuser', password=PASSWORD,
            email='sessionuser@example.com', company=self.company, role='hr',
        )
        self.client = Client()

    def test_an_existing_login_stops_working_once_deactivated(self):
        # security/urls.py registers this path without a name, so it cannot be
        # reversed; the literal path is what the SPA actually calls.
        login = self.client.post(
            '/api/auth/security/login/',
            data=json.dumps({'username': 'sessionuser', 'password': PASSWORD}),
            content_type='application/json',
        )
        self.assertEqual(login.status_code, 200, login.content)
        self.assertIn('hrcloudpay_session', self.client.cookies)

        self.assertEqual(self.client.get(reverse('me')).status_code, 200)

        User.objects.filter(pk=self.user.pk).update(is_active=False)

        self.assertNotEqual(
            self.client.get(reverse('me')).status_code, 200,
            'a deactivated user must not keep API access on an old session cookie',
        )