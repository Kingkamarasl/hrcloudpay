import hashlib
import re

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Company, User
from accounts.platform_models import AuditLog
from security.models import SecuritySession

PASSWORD = 'StrongPassword123!'


class PlatformUserUpdateTests(TestCase):
    def setUp(self):
        cache.clear()
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

    def make_user(self, username='tenantuser', **kwargs):
        kwargs.setdefault('company', self.company)
        kwargs.setdefault('email', f'{username}@example.com')
        kwargs.setdefault('role', 'hr')
        return User.objects.create_user(
            username=username, password=PASSWORD, **kwargs,
        )

    def detail_url(self, user):
        return reverse('platform-user-detail', args=[user.id])

    def patch_user(self, user, payload):
        return self.client.patch(self.detail_url(user), payload, format='json')

    def test_platform_admin_can_update_profile_and_tenant_role(self):
        target = self.make_user()

        response = self.patch_user(target, {
            'username': 'new-tenant-user',
            'email': 'new-tenant-user@example.com',
            'first_name': 'Alex',
            'last_name': 'Rivera',
            'role': 'department_manager',
            'managed_department': 'Operations',
        })

        self.assertEqual(response.status_code, 200, response.data)
        target.refresh_from_db()
        self.assertEqual(target.username, 'new-tenant-user')
        self.assertEqual(target.email, 'new-tenant-user@example.com')
        self.assertEqual(target.first_name, 'Alex')
        self.assertEqual(target.last_name, 'Rivera')
        self.assertEqual(target.role, 'department_manager')
        self.assertEqual(target.managed_department, 'Operations')
        self.assertEqual(response.data['first_name'], 'Alex')
        self.assertEqual(response.data['last_name'], 'Rivera')
        self.assertNotIn('password', response.data)

        entry = AuditLog.objects.get(
            actor=self.admin, target_type='user', target_id=str(target.id),
        )
        self.assertEqual(entry.action, 'permission_change')
        self.assertEqual(
            set(entry.metadata['changes']),
            {'username', 'email', 'first_name', 'last_name', 'role', 'managed_department'},
        )

    def test_no_op_profile_update_does_not_add_a_misleading_audit_entry(self):
        target = self.make_user()
        response = self.patch_user(target, {'email': target.email})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(AuditLog.objects.filter(
            actor=self.admin, target_type='user', target_id=str(target.id),
        ).exists())

    def test_password_and_platform_privilege_fields_are_not_editable(self):
        target = self.make_user()
        original_password = target.password

        response = self.patch_user(target, {
            'password': 'AnotherStrong123!',
            'email': 'stolen@example.com',
            'is_superuser': True,
            'is_staff': True,
            'company': None,
        })

        self.assertEqual(response.status_code, 400)
        target.refresh_from_db()
        self.assertEqual(target.password, original_password)
        self.assertEqual(target.email, 'tenantuser@example.com')
        self.assertFalse(target.is_superuser)
        self.assertFalse(target.is_staff)
        self.assertEqual(target.company, self.company)
        self.assertIn('password', response.data['fields'])
        self.assertIn('reset email action', response.data['detail'].lower())

    def test_duplicate_username_and_email_are_rejected_case_insensitively(self):
        target = self.make_user('target')
        self.make_user('already-used')

        username_response = self.patch_user(target, {'username': 'ALREADY-USED'})
        email_response = self.patch_user(target, {'email': 'ALREADY-USED@example.com'})

        self.assertEqual(username_response.status_code, 400)
        self.assertEqual(email_response.status_code, 400)
        target.refresh_from_db()
        self.assertEqual(target.username, 'target')
        self.assertEqual(target.email, 'target@example.com')

    def test_department_manager_requires_a_managed_department(self):
        target = self.make_user()

        response = self.patch_user(target, {'role': 'department_manager'})

        self.assertEqual(response.status_code, 400)
        self.assertIn('managed_department', response.data)

    def test_existing_tenant_owner_role_cannot_be_downgraded_here(self):
        owner = self.make_user('tenantowner', role='owner')

        response = self.patch_user(owner, {'role': 'hr'})

        self.assertEqual(response.status_code, 400)
        owner.refresh_from_db()
        self.assertEqual(owner.role, 'owner')

    def test_cannot_deactivate_self_or_the_last_active_superuser(self):
        self_response = self.patch_user(self.admin, {'is_active': False})
        self.assertEqual(self_response.status_code, 400)

        staff_actor = self.make_user('staffactor')
        staff_actor.is_staff = True
        staff_actor.save(update_fields=['is_staff'])
        self.client.force_authenticate(staff_actor)
        last_superuser_response = self.patch_user(self.admin, {'is_active': False})

        self.assertEqual(last_superuser_response.status_code, 400)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_deactivation_revokes_cookie_sessions_even_if_account_is_reactivated(self):
        target = self.make_user('sessionuser')
        raw_cookie = 'private-session-secret'
        session = SecuritySession.objects.create(
            user=target, company=self.company,
            secret_hash=hashlib.sha256(raw_cookie.encode()).hexdigest(),
            expires_at=timezone.now() + timezone.timedelta(hours=4),
        )
        target_client = APIClient()
        target_client.cookies['hrcloudpay_session'] = raw_cookie
        self.assertEqual(target_client.get(reverse('me')).status_code, 200)

        deactivated = self.patch_user(target, {'is_active': False})
        self.assertEqual(deactivated.status_code, 200, deactivated.data)
        session.refresh_from_db()
        self.assertIsNotNone(session.revoked_at)

        reactivated = self.patch_user(target, {'is_active': True})
        self.assertEqual(reactivated.status_code, 200, reactivated.data)
        self.assertNotEqual(
            target_client.get(reverse('me')).status_code, 200,
            'reactivating the account must not revive a previously issued session',
        )


class PlatformUserPasswordResetTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(
            username='platformadmin', password=PASSWORD,
            email='platform@example.com', role='owner',
            is_staff=True, is_superuser=True,
        )
        self.company = Company.objects.create(
            name='Acme Ltd', email='acme@example.com', is_active=True,
        )
        self.target = User.objects.create_user(
            username='reset-target', password=PASSWORD,
            email='reset-target@example.com', company=self.company,
            role='employee',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.url = reverse('platform-user-password-reset', args=[self.target.id])

    def test_reset_action_emails_a_valid_link_without_returning_or_auditing_secrets(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_str
        from django.utils.http import urlsafe_base64_decode
        from unittest.mock import patch

        with patch('accounts.password_reset.send_mail_logging_failure', return_value=1) as send:
            response = self.client.post(self.url, {}, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn(self.target.email, response.data['detail'])
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.kwargs['recipient_list'], [self.target.email])
        body = send.call_args.kwargs['message']
        match = re.search(r'/reset-password/([^/\s]+)/([^\s]+)', body)
        self.assertIsNotNone(match)
        uid, token = match.groups()
        self.assertEqual(force_str(urlsafe_base64_decode(uid)), str(self.target.id))
        self.assertTrue(default_token_generator.check_token(self.target, token))
        self.assertNotIn(token, str(response.data))

        entry = AuditLog.objects.get(
            actor=self.admin, target_type='user', target_id=str(self.target.id),
            action='security',
        )
        self.assertEqual(entry.metadata['method'], 'emailed_reset_link')
        self.assertNotIn(token, str(entry.metadata))
        self.assertNotIn('password', str(entry.metadata).lower())

    def test_inactive_user_cannot_receive_a_reset_link(self):
        from unittest.mock import patch

        self.target.is_active = False
        self.target.save(update_fields=['is_active'])
        with patch('accounts.password_reset.send_mail_logging_failure') as send:
            response = self.client.post(self.url, {}, format='json')

        self.assertEqual(response.status_code, 400)
        send.assert_not_called()

    def test_mail_failure_is_reported_without_exposing_a_reset_token(self):
        from unittest.mock import patch

        with patch('accounts.password_reset.send_mail_logging_failure', return_value=0):
            response = self.client.post(self.url, {}, format='json')

        self.assertEqual(response.status_code, 503)
        self.assertNotIn('token', str(response.data).lower())
        self.assertNotIn('/reset-password/', str(response.data))

    def test_non_platform_user_cannot_initiate_reset(self):
        self.client.force_authenticate(self.target)

        response = self.client.post(self.url, {}, format='json')

        self.assertEqual(response.status_code, 403)
