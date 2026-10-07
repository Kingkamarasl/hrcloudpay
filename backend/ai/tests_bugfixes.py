"""
Regression tests for the AI feature bug-fix pass.

Each test corresponds to a specific defect that was confirmed against the running
code before being fixed. They are deliberately behavioural (HTTP status, returned
rows, stored values) rather than assertions about implementation shape.
"""
import json
import tempfile
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.apps import apps as django_apps
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.billing import AI_MINIMUM_PLAN, AI_PLANS
from accounts.models import ROLE_CHOICES, Company, User
from accounts.platform_models import AuditLog, Subscription
from ai.access import ALL_COMPANY_ROLES, parse_allowed_roles
from ai.models import AIDraft, AIConversation, AIMessage, KnowledgeChunk, KnowledgeDocument
from ai.tools import detect_and_run, employee_lookup, execute_ai_tool, person_from_prompt

PASSWORD = 'StrongPassword123!'

# The plan the gate names as its entry point, so this fixture keeps testing AI
# behaviour and cannot quietly end up on a plan that stopped carrying AI.
AI_TEST_PLAN = AI_MINIMUM_PLAN
assert AI_TEST_PLAN in AI_PLANS, 'the AI entry plan must be one of the AI plans'


def make_company(name, email):
    """Company + active subscription so IsCompanyActive passes.

    The plan is named explicitly because AI is now a paid feature from the
    Professional plan up (`accounts.billing.AI_PLANS`). This fixture used to
    inherit the model default of `starter` and relied on the fact that no AI
    endpoint checked the plan at all, so every test here passed. That reliance
    is now the bug, not the fix: these tests are about draft access, knowledge
    lifecycle and conversation metadata, not about who may buy which plan, so
    they ask for a plan that carries AI and leave the plan boundary itself to
    `ai.tests_plan_gate`.
    """
    company = Company.objects.create(
        name=name, email=email, is_active=True, plan=AI_TEST_PLAN,
    )
    Subscription.objects.create(
        company=company, status='active',
        started_at=timezone.now(), renews_at=timezone.now() + timedelta(days=30),
    )
    return company


def make_user(company, username, role, email=None):
    return User.objects.create_user(
        username=username, email=email or f'{username}@example.com',
        password=PASSWORD, company=company, role=role,
    )


class AITestBase(TestCase):
    def setUp(self):
        self.company = make_company('Acme AI', 'ai-acme@example.com')
        self.other_company = make_company('Other Co', 'ai-other@example.com')
        self.hr = make_user(self.company, 'hr', 'hr')
        self.employee = make_user(self.company, 'joe', 'employee')
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def as_user(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client


# --------------------------------------------------------------------------
# CRITICAL: the platform AI settings save returned 500 after committing.
# --------------------------------------------------------------------------
class PlatformAIConfigTests(TestCase):
    """The site-wide AI settings page 500'd on save.

    ``PlatformAIConfigView.post`` passed the ``AIProviderConfig`` instance as the
    ``company`` argument of ``audit()``, but ``AuditLog.company`` is a
    ``ForeignKey('accounts.Company')``. Django raised ``ValueError`` from inside
    ``AuditLog.objects.create()``. Because ``config.save()`` had already run on the
    previous line and nothing wrapped the pair in a transaction, the settings were
    committed and the request still reported failure - so the admin was told the
    save failed when it had not, and the page never updated.
    """

    URL = '/api/auth/platform/ai-config/'

    def setUp(self):
        self.company = make_company('Platform Co', 'plat@example.com')
        self.platform_admin = User.objects.create_user(
            username='platadmin', email='platadmin@example.com', password=PASSWORD,
            company=self.company, role='owner', is_staff=True, is_superuser=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.platform_admin)
        self.payload = {
            'display_name': 'NVIDIA NIM',
            'chat_api_url': 'https://integrate.api.nvidia.com/v1/chat/completions',
            'embeddings_api_url': 'https://integrate.api.nvidia.com/v1/embeddings',
            'chat_model': 'nvidia/nemotron-3-super-120b-a12b',
            'embedding_model': 'nvidia/nemotron-3-embed-1b',
            'temperature': 0.3, 'max_tokens': 1200, 'request_timeout_seconds': 90,
            'is_active': True, 'api_key': 'nvapi-test-key',
        }

    def test_saving_ai_settings_does_not_error(self):
        response = self.client.post(self.URL, self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['api_key_set'])

    def test_saving_ai_settings_writes_an_audit_row_without_a_company(self):
        """The provider config is site-wide, so company must be null on the audit row."""
        self.client.post(self.URL, self.payload, format='json')
        entry = AuditLog.objects.filter(action='platform_ai_config').latest('id')
        self.assertIsNone(entry.company)
        self.assertEqual(entry.target_type, 'ai_provider_config')
        self.assertTrue(entry.metadata['api_key_changed'])

    def test_saving_ai_settings_persists_the_change(self):
        self.client.post(self.URL, self.payload, format='json')
        self.client.post(self.URL, {**self.payload, 'chat_model': 'qwen/updated'}, format='json')
        response = self.client.get(self.URL)
        self.assertEqual(response.data['chat_model'], 'qwen/updated')

    def test_a_second_save_reports_success(self):
        """Re-saving used to 500 again, leaving the page permanently stuck."""
        self.assertEqual(self.client.post(self.URL, self.payload, format='json').status_code, 200)
        self.assertEqual(
            self.client.post(self.URL, {**self.payload, 'api_key': ''}, format='json').status_code, 200,
        )

    def test_invalid_numeric_field_is_a_400_not_a_500(self):
        response = self.client.post(self.URL, {**self.payload, 'max_tokens': 'lots'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_connection_test_reports_provider_failure_without_500(self):
        from ai.nvidia import NVIDIAError
        with patch('ai.nvidia.chat_completion', side_effect=NVIDIAError('bad key')):
            response = self.client.post('/api/auth/platform/ai-config/test/', {}, format='json')
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.data['success'])

    def test_connection_test_succeeds(self):
        with patch('ai.nvidia.chat_completion', return_value={
            'choices': [{'message': {'content': 'HRCloudPay NVIDIA AI connection successful.'}}],
        }):
            response = self.client.post('/api/auth/platform/ai-config/test/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['success'])

    def test_non_platform_admin_cannot_save_ai_settings(self):
        plain = make_user(self.company, 'plain', 'hr')
        self.assertEqual(
            self.as_user(plain).post(self.URL, self.payload, format='json').status_code, 403,
        )

    def as_user(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client


# --------------------------------------------------------------------------
# CRITICAL 1 + 2: employee_lookup crashed (Q aliased to `models`) and returned
# null on the tool-calling path.
# --------------------------------------------------------------------------
class EmployeeLookupTests(AITestBase):
    def setUp(self):
        super().setUp()
        from employees.models import Employee
        Employee.objects.create(
            company=self.company, employee_code='E1', first_name='Awa', last_name='Diallo',
            email='awa@example.com', base_salary=1000, department='Sales',
        )

    def test_tool_calling_path_finds_employee_by_bare_name(self):
        """The model is told to send a bare name; that path returned None before."""
        result = execute_ai_tool(self.hr, 'employee_lookup', '{"query": "Awa Diallo"}')
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['employees'][0]['name'], 'Awa Diallo')

    def test_router_path_finds_employee(self):
        name, result = detect_and_run(self.hr, 'find details for Awa Diallo')
        self.assertEqual(name, 'employee_lookup')
        self.assertEqual(result['count'], 1)

    def test_chained_lookup_phrases_are_stripped(self):
        for prompt in ('about Awa Diallo', 'find details for Awa Diallo',
                       'search for Awa Diallo', 'profile of Awa Diallo'):
            with self.subTest(prompt=prompt):
                self.assertEqual(person_from_prompt(prompt), 'Awa Diallo')

    def test_broad_prompts_do_not_resolve_to_a_person(self):
        """'Who is currently on leave?' must not be parsed as a person name."""
        for prompt in ('How many employees do we have?', 'Who is currently on leave?',
                       'Which contracts expire soon?', 'Give me a payroll overview.'):
            with self.subTest(prompt=prompt):
                self.assertIsNone(person_from_prompt(prompt))

    def test_router_falls_through_when_nobody_matches(self):
        name, _ = detect_and_run(self.hr, 'details for Nobody Whatsoever')
        self.assertNotEqual(name, 'employee_lookup')

    def test_tool_call_does_not_500_on_bad_arguments(self):
        for args in ('not json', '{"query": null}', '{"days": "abc"}', '[]', '{"days": null}'):
            with self.subTest(args=args):
                result = execute_ai_tool(self.hr, 'expiring_contracts', args)
                self.assertIsInstance(result, dict)

    def test_empty_query_reports_an_error_instead_of_null(self):
        result = execute_ai_tool(self.hr, 'employee_lookup', '{"query": ""}')
        self.assertIn('error', result)

    def test_employee_role_is_scoped_to_their_own_record(self):
        """The employee role may call the tool but must only ever see themselves."""
        from employees.models import Employee
        mine = Employee.objects.create(
            company=self.company, employee_code='E2', first_name='Mary', last_name='Moe',
            email='mary@example.com', base_salary=900, department='Sales', user=self.employee,
        )
        colleague = employee_lookup(self.employee, 'Awa Diallo')
        self.assertEqual(colleague.get('count', 0), 0, 'an employee read a colleague record')
        self.assertEqual(employee_lookup(self.employee, mine.full_name).get('count'), 1)

    def test_lookup_matches_a_full_name(self):
        """A whole-name query is not a substring of either name column."""
        self.assertEqual(employee_lookup(self.hr, 'Awa Diallo')['count'], 1)
        self.assertEqual(employee_lookup(self.hr, 'Diallo Awa')['count'], 1)
        self.assertEqual(employee_lookup(self.hr, 'awa@example.com')['count'], 1)
        self.assertEqual(employee_lookup(self.hr, 'Awa')['count'], 1)


# --------------------------------------------------------------------------
# CRITICAL 3: drafts exposed company-wide.
# --------------------------------------------------------------------------
class AIDraftAccessTests(AITestBase):
    def setUp(self):
        super().setUp()
        self.draft = AIDraft.objects.create(
            company=self.company, created_by=self.hr, type='warning_letter',
            title='Warning: repeated lateness',
            context='Employee Awa Diallo was late 9 times.',
            content='Dear Awa Diallo, this letter records your repeated lateness...',
            status='pending',
        )

    def test_employee_cannot_list_drafts(self):
        response = self.as_user(self.employee).get('/api/ai/drafts/list/')
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('Awa Diallo', str(response.data))

    def test_employee_cannot_read_a_warning_letter(self):
        response = self.as_user(self.employee).get(f'/api/ai/drafts/{self.draft.id}/')
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('Awa Diallo', str(response.data))

    def test_employee_cannot_create_a_draft(self):
        with patch('ai.actions.chat', return_value='DRAFT'):
            response = self.as_user(self.employee).post(
                '/api/ai/drafts/', {'type': 'warning_letter', 'context': 'Subject.'}, format='json',
            )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(AIDraft.objects.filter(created_by=self.employee).exists())

    def test_department_manager_cannot_read_drafts(self):
        manager = make_user(self.company, 'mgr', 'department_manager')
        self.assertEqual(self.as_user(manager).get('/api/ai/drafts/list/').status_code, 403)

    def test_finance_can_read_and_review_drafts(self):
        finance = make_user(self.company, 'fin', 'finance')
        client = self.as_user(finance)
        self.assertEqual(client.get('/api/ai/drafts/list/').status_code, 200)
        self.assertEqual(
            client.patch(f'/api/ai/drafts/{self.draft.id}/', {'status': 'approved'}, format='json').status_code, 200,
        )

    def test_hr_can_still_read_drafts(self):
        self.assertEqual(self.client.get('/api/ai/drafts/list/').status_code, 200)


# --------------------------------------------------------------------------
# CRITICAL 4 + 5: the role allow-list failed open, and used a phantom role.
# --------------------------------------------------------------------------
class KnowledgeRoleVocabularyTests(AITestBase):
    def test_role_list_matches_the_user_model(self):
        self.assertEqual(ALL_COMPANY_ROLES, [role for role, _ in ROLE_CHOICES])

    def test_no_phantom_roles(self):
        real = {role for role, _ in ROLE_CHOICES}
        self.assertNotIn('manager', ALL_COMPANY_ROLES)
        self.assertTrue(set(ALL_COMPANY_ROLES) <= real)

    def test_finance_and_department_manager_are_grantable(self):
        self.assertEqual(parse_allowed_roles(['finance']), ['finance'])
        self.assertEqual(parse_allowed_roles(['department_manager']), ['department_manager'])

    def test_empty_or_absent_selection_is_rejected(self):
        for value in (None, '', [], 'manager', '   '):
            with self.subTest(value=value):
                self.assertIsNone(parse_allowed_roles(value))

    def test_duplicate_roles_are_collapsed(self):
        self.assertEqual(parse_allowed_roles('hr,hr,owner'), ['hr', 'owner'])

    def test_default_access_roles_constant_is_in_sync(self):
        self.assertEqual(KnowledgeDocument.DEFAULT_ACCESS_ROLES, ALL_COMPANY_ROLES)


class KnowledgeAllowedRolesTests(AITestBase):
    def test_posting_finance_roles_succeeds(self):
        response = self.client.post('/api/ai/knowledge/', {
            'title': 'Payroll policy', 'content': 'x', 'source_type': 'policy',
            'allowed_roles': 'finance',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['allowed_roles'], ['finance'])

    def test_omitting_allowed_roles_is_rejected_not_widened(self):
        response = self.client.post('/api/ai/knowledge/', {
            'title': 'Policy', 'content': 'x', 'source_type': 'policy',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(KnowledgeDocument.objects.filter(title='Policy').exists())

    def test_unchecking_every_role_does_not_grant_company_wide_access(self):
        """An empty selection used to widen to the whole company."""
        response = self.client.post('/api/ai/knowledge/', {
            'title': 'Restricted', 'content': 'x', 'source_type': 'policy',
            'allowed_roles': '',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(KnowledgeDocument.objects.filter(title='Restricted').exists())

    def test_role_scoped_document_is_hidden_from_other_roles(self):
        doc = KnowledgeDocument.objects.create(
            company=self.company, created_by=self.hr, title='Board minutes',
            content='secret', allowed_roles=['owner'],
            lifecycle_status='active',
        )
        KnowledgeChunk.objects.create(document=doc, content='secret', chunk_index=0)
        employee_response = self.as_user(self.employee).get('/api/ai/knowledge/')
        self.assertNotIn('Board minutes', str(employee_response.data))

    def test_search_hides_a_role_scoped_hit(self):
        doc = KnowledgeDocument.objects.create(
            company=self.company, created_by=self.hr, title='Board minutes',
            content='annual leave is 25 days', allowed_roles=['owner'],
            lifecycle_status='active', is_active=True,
        )
        KnowledgeChunk.objects.create(document=doc, content='annual leave is 25 days', chunk_index=0)
        with patch('ai.knowledge_views.embed_texts', side_effect=Exception('no provider')):
            response = self.as_user(self.employee).post(
                '/api/ai/knowledge/search/', {'query': 'leave'}, format='json',
            )
        self.assertEqual(response.data['results'], [])

    def test_employee_cannot_manage_knowledge(self):
        self.assertEqual(
            self.as_user(self.employee).post(
                '/api/ai/knowledge/', {'title': 'x', 'content': 'y'}, format='json',
            ).status_code,
            403,
        )


# --------------------------------------------------------------------------
# HIGH: file orphan on delete, silent truncation, unbounded conversations.
# --------------------------------------------------------------------------
class KnowledgeLifecycleTests(AITestBase):
    def test_delete_removes_the_stored_file(self):
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            doc = KnowledgeDocument.objects.create(
                company=self.company, created_by=self.hr, title='Handbook', content='x',
                lifecycle_status='active',
            )
            doc.source_file.save('handbook.pdf', ContentFile(b'%PDF-1.4 fake'), save=True)
            path = doc.source_file.name
            self.assertTrue(default_storage.exists(path))
            response = self.client.delete(f'/api/ai/knowledge/{doc.id}/')
            self.assertEqual(response.status_code, 204)
            self.assertFalse(default_storage.exists(path), f'orphaned file left on storage: {path}')

    def test_oversized_pasted_content_is_rejected(self):
        response = self.client.post('/api/ai/knowledge/', {
            'title': 'Huge', 'content': 'x' * 200_001, 'source_type': 'policy',
            'allowed_roles': 'hr',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('200,000', response.data['detail'])

    def test_embedding_failure_marks_the_document_failed(self):
        """'Needs attention' and 'Retry index' were dead UI: nothing ever set 'failed'."""
        from ai.nvidia import NVIDIAError
        with patch('ai.knowledge_views.embed_texts', side_effect=NVIDIAError('provider down')):
            response = self.client.post('/api/ai/knowledge/', {
                'title': 'Policy', 'content': 'Annual leave is 25 days.', 'source_type': 'policy',
                'allowed_roles': 'hr',
            }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['lifecycle_status'], 'failed')
        self.assertTrue(response.data['needs_reindex'])

    def test_reindex_recovers_a_failed_document(self):
        doc = KnowledgeDocument.objects.create(
            company=self.company, created_by=self.hr, title='Policy', content='leave policy',
            allowed_roles=['hr'], lifecycle_status='failed', is_active=True,
            processing_error='provider down',
        )
        KnowledgeChunk.objects.create(document=doc, content='leave policy', chunk_index=0)
        with patch('ai.knowledge_views.embed_texts', return_value=[[0.1, 0.2, 0.3]]):
            response = self.client.post('/api/ai/knowledge/reindex/', {'document_id': doc.id}, format='json')
        self.assertEqual(response.status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.lifecycle_status, 'active')
        self.assertEqual(doc.processing_error, '')

    def test_failed_document_is_still_retrievable_by_keyword(self):
        """A recoverable indexing error must not make the document vanish."""
        doc = KnowledgeDocument.objects.create(
            company=self.company, created_by=self.hr, title='Policy', content='x',
            allowed_roles=['hr'], lifecycle_status='failed', is_active=True,
        )
        KnowledgeChunk.objects.create(document=doc, content='annual leave is 25 days', chunk_index=0)
        with patch('ai.knowledge_views.embed_texts', side_effect=Exception('no provider')):
            response = self.client.post(
                '/api/ai/knowledge/search/', {'query': 'annual leave'}, format='json',
            )
        self.assertEqual(len(response.data['results']), 1)

    def test_empty_patch_writes_no_audit_event(self):
        doc = KnowledgeDocument.objects.create(
            company=self.company, created_by=self.hr, title='Policy', content='x',
            allowed_roles=['hr'], lifecycle_status='active',
        )
        before = AuditLog.objects.count()
        response = self.client.patch(f'/api/ai/knowledge/{doc.id}/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AuditLog.objects.count(), before)

    def test_version_group_from_another_tenant_is_rejected(self):
        foreign = KnowledgeDocument.objects.create(
            company=self.other_company, created_by=make_user(self.other_company, 'ohr', 'hr'),
            title='Foreign', content='x', allowed_roles=['hr'], lifecycle_status='active',
            version_group=uuid4(),
        )
        response = self.client.post('/api/ai/knowledge/', {
            'title': 'Mine', 'content': 'x' * 10, 'source_type': 'policy',
            'allowed_roles': 'hr', 'version_group': str(foreign.version_group),
        }, format='json')
        self.assertEqual(response.status_code, 400)
        # The foreign document must be untouched, not archived by the rejected upload.
        foreign.refresh_from_db()
        self.assertEqual(foreign.lifecycle_status, 'active')

    def test_malformed_version_group_is_a_400_not_a_500(self):
        """An unparseable id used to raise an uncaught ORM ValidationError."""
        response = self.client.post('/api/ai/knowledge/', {
            'title': 'Mine', 'content': 'x' * 10, 'source_type': 'policy',
            'allowed_roles': 'hr', 'version_group': 'not-a-uuid',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_resubmitting_a_title_supersedes_the_previous_version(self):
        """Two active copies of one policy let the assistant answer from the old one."""
        first = self.client.post('/api/ai/knowledge/', {
            'title': 'Leave Policy', 'content': 'Annual leave is 20 days.', 'source_type': 'policy',
            'allowed_roles': 'hr',
        }, format='json')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.data['version'], 1)
        group = first.data['version_group']

        second = self.client.post('/api/ai/knowledge/', {
            'title': 'Leave Policy', 'content': 'Annual leave is 25 days.', 'source_type': 'policy',
            'allowed_roles': 'hr',
        }, format='json')
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.data['version'], 2)
        self.assertEqual(second.data['version_group'], group, 'title match must continue the same chain')

        old = KnowledgeDocument.objects.get(id=first.data['id'])
        self.assertEqual(old.lifecycle_status, 'archived')
        self.assertFalse(old.is_active)
        active = KnowledgeDocument.objects.filter(
            company=self.company, title='Leave Policy', is_active=True,
        )
        self.assertEqual(active.count(), 1, 'retrieval does not prefer newer versions, so only one may stay active')

    def test_a_document_whose_index_failed_can_still_be_superseded(self):
        """Keying the chain on is_active, not on a healthy index status."""
        from ai.nvidia import NVIDIAError
        with patch('ai.knowledge_views.embed_texts', side_effect=NVIDIAError('provider down')):
            first = self.client.post('/api/ai/knowledge/', {
                'title': 'Leave Policy', 'content': 'Annual leave is 20 days.', 'source_type': 'policy',
                'allowed_roles': 'hr',
            }, format='json')
        self.assertEqual(first.data['lifecycle_status'], 'failed')
        second = self.client.post('/api/ai/knowledge/', {
            'title': 'Leave Policy', 'content': 'Annual leave is 25 days.', 'source_type': 'policy',
            'allowed_roles': 'hr',
        }, format='json')
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.data['version'], 2)
        self.assertEqual(
            KnowledgeDocument.objects.filter(company=self.company, title='Leave Policy', is_active=True).count(), 1,
        )


class EmbeddingBatchingTests(AITestBase):
    def test_large_inputs_are_split_into_batches(self):
        import json
        import urllib.request

        from ai import embeddings
        texts = [f'text {i}' for i in range(embeddings.EMBED_BATCH_SIZE * 2 + 5)]
        calls = []

        def fake_urlopen(request, timeout=None):
            body = json.loads(request.data.decode())
            calls.append(len(body['input']))
            return FakeResponse({'data': [
                {'index': i, 'embedding': [0.1, 0.2]} for i in range(len(body['input']))
            ]})

        with patch.object(urllib.request, 'urlopen', fake_urlopen), \
             patch.object(embeddings, 'get_embeddings_config') as cfg, \
             patch.object(embeddings, 'decrypt_api_key', return_value='k'):
            cfg.return_value.embeddings_api_url = 'https://example.test/e'
            cfg.return_value.embedding_model = 'm'
            cfg.return_value.request_timeout_seconds = 5
            vectors = embeddings.embed_texts(texts)

        self.assertEqual(len(vectors), len(texts))
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(size <= embeddings.EMBED_BATCH_SIZE for size in calls))

    def test_short_response_is_rejected_rather_than_silently_truncating(self):
        import urllib.request

        from ai import embeddings
        from ai.nvidia import NVIDIAError
        with patch.object(embeddings, 'get_embeddings_config') as cfg, \
             patch.object(embeddings, 'decrypt_api_key', return_value='k'), \
             patch.object(urllib.request, 'urlopen',
                          lambda request, timeout=None: FakeResponse({'data': [{'index': 0, 'embedding': [0.1]}]})):
            cfg.return_value.embeddings_api_url = 'https://example.test/e'
            cfg.return_value.embedding_model = 'm'
            cfg.return_value.request_timeout_seconds = 5
            with self.assertRaises(NVIDIAError):
                embeddings.embed_texts(['a', 'b'])

    def test_stale_model_vectors_are_not_compared(self):
        from ai.embeddings import embedding_is_current
        chunk = KnowledgeChunk(document=None, content='x', chunk_index=0,
                               embedding=[0.1, 0.2], embedding_model='old-model')
        self.assertFalse(embedding_is_current(chunk, 'new-model', 2))
        chunk.embedding_model = 'new-model'
        self.assertTrue(embedding_is_current(chunk, 'new-model', 2))
        self.assertFalse(embedding_is_current(chunk, 'new-model', 8))


class FakeResponse:
    def __init__(self, payload):
        import json
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


# --------------------------------------------------------------------------
# HIGH: unbounded conversation payloads and lost turns.
# --------------------------------------------------------------------------
class ConversationTests(AITestBase):
    def test_list_endpoint_omits_message_bodies(self):
        conversation = AIConversation.objects.create(company=self.company, user=self.hr, title='Long chat')
        for i in range(120):
            AIMessage.objects.create(
                conversation=conversation, role='user' if i % 2 == 0 else 'assistant', content=f'm{i}',
            )
        response = self.client.get('/api/ai/conversations/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('messages', response.data[0])
        self.assertIn('id', response.data[0])

    def test_detail_endpoint_caps_the_thread(self):
        from ai.views import CONVERSATION_MESSAGE_LIMIT
        conversation = AIConversation.objects.create(company=self.company, user=self.hr, title='Long')
        for i in range(CONVERSATION_MESSAGE_LIMIT + 50):
            AIMessage.objects.create(conversation=conversation, role='user', content=f'm{i}')
        response = self.client.get(f'/api/ai/conversations/{conversation.id}/')
        self.assertEqual(len(response.data['messages']), CONVERSATION_MESSAGE_LIMIT)

    def test_failed_turn_keeps_the_question_in_history(self):
        from ai.nvidia import NVIDIAError
        with patch('ai.services.chat_completion', side_effect=NVIDIAError('provider down')):
            response = self.client.post(
                '/api/ai/conversations/', {'message': 'What is our leave policy?'}, format='json',
            )
        self.assertEqual(response.status_code, 503)
        self.assertTrue(
            AIMessage.objects.filter(role='user', content='What is our leave policy?').exists(),
            'the user question vanished from history when the provider failed',
        )

    def test_prompt_is_not_sent_to_the_model_twice(self):
        captured = {}

        def fake_chat_completion(messages, **kwargs):
            captured['messages'] = messages
            return {'choices': [{'message': {'content': 'Answer.'}}]}

        with patch('ai.services.chat_completion', fake_chat_completion):
            response = self.client.post(
                '/api/ai/conversations/', {'message': 'How many employees do we have?'}, format='json',
            )
        self.assertEqual(response.status_code, 201)
        sent = [m for m in captured['messages'] if m.get('role') == 'user']
        self.assertEqual(sum(1 for m in sent if m['content'] == 'How many employees do we have?'), 1)

    def test_response_metadata_is_present_for_the_verified_badge(self):
        with patch('ai.services.chat_completion', return_value={'choices': [{'message': {'content': 'Answer.'}}]}):
            response = self.client.post('/api/ai/conversations/', {'message': 'Hi'}, format='json')
        self.assertEqual(response.status_code, 201)
        # The client decides "verified" from metadata.tools, which must be present on
        # the live response and identical to what a later read returns.
        self.assertIn('metadata', response.data['message'])
        self.assertNotIn('tool', response.data['message'])


class AIToolRobustnessTests(AITestBase):
    def test_router_failure_degrades_to_a_text_answer(self):
        """A bug in the deterministic router must not surface as an HTTP 500."""
        # An empty message with no tool_calls makes the tool-calling loop fall
        # through to the deterministic router instead of answering directly.
        empty = {'choices': [{'message': {'content': ''}}]}
        with patch('ai.services.chat_completion', return_value=empty), \
             patch('ai.services.detect_and_run', side_effect=RuntimeError('router bug')), \
             patch('ai.services.chat', return_value='Fallback answer.'):
            response = self.client.post('/api/ai/conversations/', {'message': 'How many employees?'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['message']['content'], 'Fallback answer.')

# --------------------------------------------------------------------------
# NVIDIA retired both models this app shipped with on 2026-07-20. Every chat
# and embedding call answered HTTP 410, and a fresh install defaulted to them.
# --------------------------------------------------------------------------
RETIRED_CHAT_MODEL = 'qwen/qwen3.5-122b-a10b'
RETIRED_EMBEDDING_MODEL = 'nvidia/llama-3.2-nemoretriever-300m-embed-v2'
LIVE_CHAT_MODEL = 'nvidia/nemotron-3-super-120b-a12b'
LIVE_EMBEDDING_MODEL = 'nvidia/nemotron-3-embed-1b'
GONE_BODY = json.dumps({
    'type': 'about:blank', 'title': 'Gone', 'status': 410,
    'detail': f"The model '{RETIRED_CHAT_MODEL}' has reached its end of life on "
              '2026-07-20T00:00:00Z and is no longer available.',
})


def http_error(code, body):
    """Build a urllib HTTPError carrying a provider body."""
    import urllib.error

    err = urllib.error.HTTPError('https://example.test', code, 'msg', {}, None)
    err.read = lambda: body.encode()
    return err


class LiveModelDefaultsTests(TestCase):
    """A new workspace must not boot pointed at a retired model."""

    def test_chat_default_is_not_a_retired_model(self):
        from ai.models import AIProviderConfig
        self.assertEqual(AIProviderConfig._meta.get_field('chat_model').default, LIVE_CHAT_MODEL)

    def test_embedding_default_is_not_a_retired_model(self):
        from ai.models import AIProviderConfig
        self.assertEqual(
            AIProviderConfig._meta.get_field('embedding_model').default, LIVE_EMBEDDING_MODEL,
        )

    def test_embeddings_fallback_constant_is_not_retired(self):
        from ai.embeddings import DEFAULT_EMBEDDING_MODEL
        self.assertEqual(DEFAULT_EMBEDDING_MODEL, LIVE_EMBEDDING_MODEL)

    def test_no_retired_model_string_remains_in_shipped_ai_code(self):
        """No retired id may remain as live code, e.g. as a default or a constant.

        Comments are excluded deliberately: explaining *why* the default changed is
        worth keeping, and the id only has to be matched to be replaced, never
        called.
        """
        import io
        import pathlib
        import tokenize

        import ai

        offenders = []
        for path in pathlib.Path(ai.__file__).parent.rglob('*.py'):
            if 'migrations' in path.parts or path.name.startswith('tests'):
                continue  # immutable history + the 0012 rewrite; tests name them as fixtures
            source = path.read_text(encoding='utf-8', errors='replace')
            code = ''.join(
                tok.string for tok in tokenize.generate_tokens(io.StringIO(source).readline)
                if tok.type != tokenize.COMMENT
            )
            for retired in (RETIRED_CHAT_MODEL, RETIRED_EMBEDDING_MODEL):
                if retired in code:
                    offenders.append(f'{path.name}: {retired}')
        self.assertEqual(offenders, [], f'retired model ids still used in code: {offenders}')

    def test_data_migration_moves_existing_rows_onto_live_models(self):
        """An already-provisioned workspace otherwise keeps calling the dead model."""
        from importlib import import_module

        from ai.models import AIProviderConfig

        AIProviderConfig.objects.create(
            display_name='Legacy', api_key_encrypted='x', is_active=True,
            chat_model=RETIRED_CHAT_MODEL, embedding_model=RETIRED_EMBEDDING_MODEL,
        )
        AIProviderConfig.objects.create(
            display_name='Custom', api_key_encrypted='x', is_active=True,
            chat_model='vendor/hand-picked', embedding_model='vendor/hand-picked-embed',
        )

        module = import_module('ai.migrations.0012_move_retired_nvidia_models')
        module.move_to_live_models(django_apps, None)

        legacy = AIProviderConfig.objects.get(display_name='Legacy')
        self.assertEqual(legacy.chat_model, LIVE_CHAT_MODEL)
        self.assertEqual(legacy.embedding_model, LIVE_EMBEDDING_MODEL)
        custom = AIProviderConfig.objects.get(display_name='Custom')
        self.assertEqual(custom.chat_model, 'vendor/hand-picked')
        self.assertEqual(custom.embedding_model, 'vendor/hand-picked-embed',
                         'a deliberate custom choice must not be overwritten')


class RetiredModelErrorTests(AITestBase):
    """A retired model is a configuration fault, not a transient outage."""

    def test_gone_response_becomes_a_model_unavailable_error(self):
        import urllib.request

        from ai.nvidia import AIModelUnavailableError, chat_completion
        from ai.models import AIProviderConfig

        AIProviderConfig.objects.create(
            display_name='P', api_key_encrypted='x', is_active=True,
            chat_model=RETIRED_CHAT_MODEL, request_timeout_seconds=5,
        )
        with patch('ai.nvidia.decrypt_api_key', return_value='k'), \
             patch.object(urllib.request, 'urlopen', side_effect=http_error(410, GONE_BODY)):
            with self.assertRaises(AIModelUnavailableError) as ctx:
                chat_completion([{'role': 'user', 'content': 'hi'}])
        message = str(ctx.exception)
        self.assertIn(RETIRED_CHAT_MODEL, message)
        self.assertIn('AI settings', message)
        self.assertNotIn('about:blank', message, 'raw provider dump leaked to the user')

    def test_model_unavailable_is_still_an_nvidia_error(self):
        """Every existing handler catches NVIDIAError and must keep working."""
        from ai.nvidia import AIModelUnavailableError, NVIDIAError
        self.assertTrue(issubclass(AIModelUnavailableError, NVIDIAError))

    def test_retired_model_is_not_retried(self):
        """A dead model fails fast rather than burning three attempts."""
        import urllib.request

        from ai.nvidia import AIModelUnavailableError, chat_completion
        from ai.models import AIProviderConfig

        AIProviderConfig.objects.create(
            display_name='P', api_key_encrypted='x', is_active=True,
            chat_model=RETIRED_CHAT_MODEL, request_timeout_seconds=5,
        )
        calls = []

        def counting(*a, **k):
            calls.append(1)
            raise http_error(410, GONE_BODY)

        with patch('ai.nvidia.decrypt_api_key', return_value='k'), \
             patch('ai.nvidia.time.sleep'), \
             patch.object(urllib.request, 'urlopen', counting):
            with self.assertRaises(AIModelUnavailableError):
                chat_completion([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(len(calls), 1, 'a deterministic 410 must not be retried')

    def test_rate_limit_is_not_mislabelled_as_a_retired_model(self):
        from ai.nvidia import AIModelUnavailableError, NVIDIAError, provider_error
        err = provider_error(429, json.dumps({'error': {'message': 'slow down'}}), 'some/model')
        self.assertNotIsInstance(err, AIModelUnavailableError)
        self.assertIn('slow down', str(err))
        self.assertIsInstance(err, NVIDIAError)

    def test_missing_serving_function_is_reported_as_a_model_problem(self):
        """The catalog lists models whose function is gone; they answer 404."""
        from ai.nvidia import AIModelUnavailableError, provider_error
        err = provider_error(404, json.dumps({
            'status': 404, 'title': 'Not Found', 'detail': "Function 'abc-123' not found",
        }), 'nvidia/ghost-model')
        self.assertIsInstance(err, AIModelUnavailableError)
        self.assertIn('abc-123', str(err), 'provider detail must survive for diagnosis')

    def test_bare_text_error_body_does_not_crash_the_parser(self):
        from ai.nvidia import NVIDIAError, provider_error
        err = provider_error(500, 'upstream connect error', 'm')
        self.assertIsInstance(err, NVIDIAError)
        self.assertIn('upstream connect error', str(err))


class TransientProviderRetryTests(AITestBase):
    """NVIDIA's shared tier intermittently 500s the same request that just worked."""

    def setUp(self):
        super().setUp()
        from ai.models import AIProviderConfig
        self.config = AIProviderConfig.objects.create(
            display_name='P', api_key_encrypted='x', is_active=True,
            chat_model='live/model', request_timeout_seconds=5,
        )

    def _chat(self, urlopen):
        import urllib.request

        from ai.nvidia import chat_completion
        with patch('ai.nvidia.decrypt_api_key', return_value='k'), \
             patch('ai.nvidia.time.sleep'), \
             patch.object(urllib.request, 'urlopen', urlopen):
            return chat_completion([{'role': 'user', 'content': 'hi'}])

    def test_transient_500_is_retried_and_can_succeed(self):
        ok = {'choices': [{'message': {'content': 'recovered'}}]}
        state = {'n': 0}

        def flaky(request, timeout=None):
            state['n'] += 1
            if state['n'] == 1:
                raise http_error(500, 'upstream boom')
            return FakeResponse(ok)

        self.assertEqual(self._chat(flaky)['choices'][0]['message']['content'], 'recovered')
        self.assertEqual(state['n'], 2)

    def test_persistent_500_eventually_raises(self):
        state = {'n': 0}

        def always_fails(request, timeout=None):
            state['n'] += 1
            raise http_error(503, 'still down')

        from ai.nvidia import NVIDIAError
        with self.assertRaises(NVIDIAError):
            self._chat(always_fails)
        self.assertEqual(state['n'], 3, 'should try the configured number of attempts')

    def test_bad_request_is_not_retried(self):
        state = {'n': 0}

        def bad_request(request, timeout=None):
            state['n'] += 1
            raise http_error(400, '{"detail":"malformed"}')

        from ai.nvidia import NVIDIAError
        with self.assertRaises(NVIDIAError):
            self._chat(bad_request)
        self.assertEqual(state['n'], 1, 'a deterministic 400 must fail on the first attempt')

    def test_auth_failure_is_not_retried(self):
        state = {'n': 0}

        def unauthorized(request, timeout=None):
            state['n'] += 1
            raise http_error(401, '{"detail":"bad key"}')

        from ai.nvidia import NVIDIAError
        with self.assertRaises(NVIDIAError):
            self._chat(unauthorized)
        self.assertEqual(state['n'], 1)

    def test_dropped_connection_is_retried(self):
        import urllib.error

        state = {'n': 0}

        def drops(request, timeout=None):
            state['n'] += 1
            if state['n'] == 1:
                raise urllib.error.URLError('connection reset')
            return FakeResponse({'choices': [{'message': {'content': 'ok'}}]})

        self.assertEqual(self._chat(drops)['choices'][0]['message']['content'], 'ok')
        self.assertEqual(state['n'], 2)

    def test_time_budget_bounds_the_retry_loop(self):
        """A slow upstream must not multiply the request past the budget."""
        import ai.nvidia as nvidia_mod
        with patch.object(nvidia_mod, 'RETRY_TIME_BUDGET_SECONDS', 0.0):
            state = {'n': 0}

            def always_fails(request, timeout=None):
                state['n'] += 1
                raise http_error(500, 'down')

            from ai.nvidia import NVIDIAError
            with self.assertRaises(NVIDIAError):
                self._chat(always_fails)
            self.assertEqual(state['n'], 1, 'exhausted budget must not start another attempt')
