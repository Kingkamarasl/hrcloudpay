"""Choosing an AI provider, and what happens to the ones that cannot embed.

The provider field used to be `editable=False` and every save wrote
`'nvidia_nim'` back over it, so the assistant could only ever run on NVIDIA.
These pin the two things that were previously not expressible: that the console
can choose, and that a chat-only provider does not quietly take the knowledge
base down with it.

OpenRouter is the reason for the second half. Its published catalogue was checked
live while building this - 465 models, none of them embeddings - so switching chat
to it means losing the embedding provider unless another configuration is kept
underneath.
"""
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework.test import APIClient

from ai import providers
from ai.models import AIProviderConfig
from ai.provider import (
    AIConfigurationError,
    get_active_config,
    get_embeddings_config,
)

from django.test import TestCase

CONFIG_URL = '/api/auth/platform/ai-config/'
SECRET = 'sk-or-not-a-real-key'


def configured(provider='nvidia_nim', **overrides):
    from ai.provider import _fernet

    row = AIProviderConfig.objects.create(
        provider=provider,
        display_name=providers.get_spec(provider).label,
        provides_embeddings=providers.get_spec(provider).provides_embeddings,
    )
    row.api_key_encrypted = _fernet().encrypt(SECRET.encode()).decode()
    for key, value in overrides.items():
        setattr(row, key, value)
    row.save()
    return row


class ProviderCatalogueTests(TestCase):
    def test_openrouter_is_offered_and_can_do_chat(self):
        spec = providers.get_spec('openrouter')

        self.assertEqual(spec.label, 'OpenRouter')
        self.assertIn('openrouter.ai', spec.chat_api_url)

    def test_openrouter_is_declared_as_unable_to_embed(self):
        """Not an inference from a blank URL - a stated capability, so the
        console can warn before anything is indexed."""
        spec = providers.get_spec('openrouter')

        self.assertFalse(spec.provides_embeddings)
        self.assertEqual(spec.embeddings_api_url, '')

    def test_nvidia_can_do_both(self):
        spec = providers.get_spec('nvidia_nim')

        self.assertTrue(spec.provides_embeddings)
        self.assertIn('embeddings', spec.embeddings_api_url)

    def test_an_unknown_provider_falls_back_rather_than_raising(self):
        """A hand-edited row must not make the assistant unstartable."""
        self.assertEqual(providers.get_spec('nope').key, 'nvidia_nim')

    def test_every_provider_offers_a_chat_url_and_a_model(self):
        for spec in providers.PROVIDERS.values():
            self.assertTrue(spec.chat_api_url, spec.key)
            self.assertTrue(spec.default_chat_model, spec.key)


class MultipleRowsAreAllowedTests(TestCase):
    """Two configurations must both be creatable.

    A unique constraint on is_active was tried here and is wrong for this
    schema: is_active defaults to True, so it means no second row can ever
    exist at all. It broke a data migration that moves existing rows onto the
    live models, and would break any future code path that provisions a
    second configuration. The single-active guarantee is enforced in the save
    path instead, where activating one row can be understood to imply
    something about the others.
    """

    def test_a_second_configuration_can_be_created(self):
        first = AIProviderConfig.objects.create(provider='nvidia_nim')
        second = AIProviderConfig.objects.create(provider='openrouter')

        self.assertEqual(AIProviderConfig.objects.count(), 2)
        self.assertTrue(first.is_active)
        self.assertTrue(second.is_active)


class EmbeddingResolutionTests(TestCase):
    def test_the_active_provider_is_used_when_it_can_embed(self):
        row = configured('nvidia_nim')

        self.assertEqual(get_embeddings_config().id, row.id)

    def test_a_chat_only_active_provider_falls_back_to_one_that_can_embed(self):
        """The whole point. OpenRouter active, NVIDIA underneath: the knowledge
        base must keep working rather than posting to an endpoint that has never
        existed."""
        nvidia = configured('nvidia_nim', is_active=False)
        configured('openrouter', is_active=True)

        resolved = get_embeddings_config()

        self.assertEqual(resolved.id, nvidia.id)
        self.assertTrue(resolved.provides_embeddings)

    def test_chat_still_resolves_to_the_active_provider(self):
        """The two resolutions are independent on purpose: chat follows the
        admin's choice, embeddings follow what can actually embed."""
        configured('nvidia_nim', is_active=False)
        openrouter = configured('openrouter', is_active=True)

        self.assertEqual(get_active_config().id, openrouter.id)

    def test_with_no_embedding_provider_the_error_names_the_fix(self):
        configured('openrouter', is_active=True)

        with self.assertRaises(AIConfigurationError) as caught:
            get_embeddings_config()

        # The message has to say what to do. A bare "no configuration" sends an
        # operator looking for a toggle that does not exist.
        self.assertIn('embedding', str(caught.exception).lower())

    def test_a_provider_with_no_key_is_not_offered_as_the_embedder(self):
        """A row with an empty key cannot embed, and returning it would fail at
        the HTTP layer instead of at resolution."""
        AIProviderConfig.objects.create(
            provider='nvidia_nim', is_active=False, provides_embeddings=True,
            api_key_encrypted='',
        )
        configured('openrouter', is_active=True)

        with self.assertRaises(AIConfigurationError):
            get_embeddings_config()


class PlatformAiConfigApiTests(TestCase):
    def setUp(self):
        self.admin = __import__('accounts.models', fromlist=['User']).User.objects.create_superuser(
            username='root', email='root@example.com',
            password='Str0ngPass-2026!', company=None,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_the_catalogue_is_returned_for_the_console(self):
        """The provider list is defined server-side and sent to the browser, so
        the endpoints and capability flags cannot drift between the two."""
        response = self.client.get(CONFIG_URL)

        self.assertEqual(response.status_code, 200, response.data)
        keys = {p['key'] for p in response.data['providers']}
        self.assertEqual(keys, set(providers.PROVIDERS))
        openrouter = next(p for p in response.data['providers']
                          if p['key'] == 'openrouter')
        self.assertFalse(openrouter['provides_embeddings'])

    def test_choosing_openrouter_is_persisted(self):
        """The regression. Every save used to write 'nvidia_nim' back."""
        configured('nvidia_nim')

        response = self.client.post(
            CONFIG_URL, {'provider': 'openrouter', 'api_key': SECRET},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        row = AIProviderConfig.objects.first()
        self.assertEqual(row.provider, 'openrouter')
        self.assertEqual(row.display_name, 'OpenRouter')

    def test_choosing_a_provider_applies_its_endpoints_and_models(self):
        configured('nvidia_nim')

        self.client.post(CONFIG_URL, {'provider': 'openrouter'}, format='json')

        row = AIProviderConfig.objects.first()
        self.assertEqual(row.chat_api_url, providers.OPENROUTER.chat_api_url)
        self.assertEqual(row.chat_model, providers.OPENROUTER.default_chat_model)
        self.assertFalse(row.provides_embeddings)

    def test_switching_clears_the_previous_providers_embeddings_url(self):
        """Otherwise the row looks configured and the knowledge base posts to a
        host that never had the path - reported as an outage rather than as a
        missing capability."""
        configured('nvidia_nim')

        self.client.post(CONFIG_URL, {'provider': 'openrouter'}, format='json')

        self.assertEqual(AIProviderConfig.objects.first().embeddings_api_url, '')

    def test_an_explicitly_chosen_model_survives_a_later_save(self):
        """The preset must not overwrite an operator's deliberate choice on the
        next unrelated save."""
        configured('nvidia_nim')

        self.client.post(
            CONFIG_URL,
            {'provider': 'openrouter', 'chat_model': 'google/gemini-2.5-flash'},
            format='json',
        )
        self.client.post(CONFIG_URL, {'temperature': 0.7}, format='json')

        self.assertEqual(
            AIProviderConfig.objects.first().chat_model, 'google/gemini-2.5-flash')

    def test_the_console_is_told_whether_an_embedder_exists(self):
        configured('openrouter', is_active=False)
        configured('nvidia_nim', is_active=True)

        response = self.client.get(CONFIG_URL)

        self.assertTrue(response.data['embeddings_configured'])
        self.assertEqual(response.data['embeddings_provider'], 'NVIDIA NIM')

    def test_the_console_reports_no_embedder_when_there_is_none(self):
        configured('openrouter', is_active=True)

        response = self.client.get(CONFIG_URL)

        self.assertFalse(response.data['embeddings_configured'])
        self.assertIsNone(response.data['embeddings_provider'])

    def test_an_unknown_provider_is_ignored_rather_than_saved(self):
        configured('nvidia_nim')

        self.client.post(CONFIG_URL, {'provider': 'made-up'}, format='json')

        self.assertEqual(AIProviderConfig.objects.first().provider, 'nvidia_nim')

    def test_the_api_key_is_never_returned(self):
        configured('nvidia_nim')

        body = str(self.client.get(CONFIG_URL).data)

        self.assertNotIn(SECRET, body)
        self.assertTrue(self.client.get(CONFIG_URL).data['api_key_set'])

    def test_a_tenant_admin_cannot_see_or_change_it(self):
        from accounts.models import Company, User

        company = Company.objects.create(
            name='Acme', email='acme@example.com', is_active=True, plan='starter')
        worker = User.objects.create_user(
            username='owner', email='owner@example.com',
            password='Str0ngPass-2026!', company=company, role='owner',
        )
        self.client.force_authenticate(worker)

        self.assertEqual(self.client.get(CONFIG_URL).status_code, 403)
        self.assertEqual(
            self.client.post(CONFIG_URL, {'provider': 'openrouter'},
                             format='json').status_code,
            403,
        )