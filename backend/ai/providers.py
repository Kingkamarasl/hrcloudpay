"""The AI providers this project can talk to, and what each one can do.

Why a catalogue rather than a hardcoded provider
------------------------------------------------
``AIProviderConfig.provider`` was ``editable=False`` and every save wrote
``'nvidia_nim'`` back over whatever was there, so the assistant could only ever
run on NVIDIA. That was not a limitation anyone chose - it was the absence of a
place to express the choice.

Why one provider needs a second config
--------------------------------------
OpenRouter serves chat completions and nothing else. Its public catalogue was
checked live while building this: 465 models, none of them embeddings. So an
installation that switches chat to OpenRouter has just lost its embedding
provider, and the knowledge base indexes and semantic search go with it.

Rather than let that fail at query time, ``get_embeddings_config()`` resolves an
embeddings-capable configuration independently of whichever one is active for
chat. A platform admin configures OpenRouter for chat, leaves an NVIDIA row (or
any other embedding provider) configured underneath it, and the knowledge base
keeps working. With no embedding provider configured at all, indexing fails with
a message naming the fix rather than an HTTP 404 from a provider that never had
the endpoint.

Every provider here speaks the OpenAI ``/chat/completions`` schema, which is why
the transport in ``nvidia.py`` needed no rewrite - only the URL, the model and
the key change.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderSpec:
    """One provider's endpoints, defaults, and capabilities."""

    key: str
    label: str
    chat_api_url: str
    default_chat_model: str
    #: Blank when the provider has no embeddings endpoint. Not a guess - the
    #: catalogue says so.
    embeddings_api_url: str = ''
    default_embedding_model: str = ''
    provides_embeddings: bool = False
    #: Which models are worth offering by default. Free to leave the model field
    #: as anything the provider accepts; these are only the starting values.
    model_examples: tuple = ()
    api_key_hint: str = ''
    notes: str = ''
    #: Extra headers sent with every request. OpenRouter uses these for app
    #: attribution and rate limiting; it is optional, and sending them makes the
    #: traffic attributable to this installation rather than anonymous.
    extra_headers: dict = field(default_factory=dict)

    @property
    def default_display_name(self) -> str:
        return self.label


NVIDIA_NIM = ProviderSpec(
    key='nvidia_nim',
    label='NVIDIA NIM',
    chat_api_url='https://integrate.api.nvidia.com/v1/chat/completions',
    embeddings_api_url='https://integrate.api.nvidia.com/v1/embeddings',
    default_chat_model='nvidia/nemotron-3-super-120b-a12b',
    default_embedding_model='nvidia/nemotron-3-embed-1b',
    provides_embeddings=True,
    model_examples=(
        'nvidia/nemotron-3-super-120b-a12b',
        'nvidia/llama-3.3-nemotron-super-49b-v1.5',
    ),
    api_key_hint='NVIDIA API key from build.nvidia.com',
    notes='Serves both chat and embeddings, so it can run the knowledge base on its own.',
)

OPENROUTER = ProviderSpec(
    key='openrouter',
    label='OpenRouter',
    chat_api_url='https://openrouter.ai/api/v1/chat/completions',
    # No embeddings endpoint exists. Do not add one here without checking.
    embeddings_api_url='',
    default_embedding_model='',
    provides_embeddings=False,
    default_chat_model='anthropic/claude-sonnet-4.6',
    model_examples=(
        'anthropic/claude-sonnet-4.6',
        'anthropic/claude-sonnet-4.5',
        'google/gemini-2.5-flash',
        'deepseek/deepseek-chat-v3.1',
        'openai/gpt-4o-mini',
    ),
    api_key_hint='OpenRouter API key from openrouter.ai/keys',
    notes=(
        'Chat only - OpenRouter publishes no embedding model. Keep an NVIDIA row '
        'configured for the knowledge base to keep working.'
    ),
    extra_headers={
        # Optional, and deliberately overridable: OpenRouter uses the referer for
        # app attribution. Blank means the header is simply omitted rather than
        # sent empty, since an empty HTTP-Referer is worse than none.
    },
)

PROVIDERS = {spec.key: spec for spec in (NVIDIA_NIM, OPENROUTER)}
DEFAULT_PROVIDER = NVIDIA_NIM.key


def get_spec(key: str) -> ProviderSpec:
    """The spec for a provider key, falling back to the default.

    Falling back rather than raising: a row written before this catalogue
    existed, or by a hand-edited database, must not make the assistant
    unstartable. An unknown provider is an operator error to surface in the
    console, not a reason to refuse to serve chat.
    """
    return PROVIDERS.get(key) or PROVIDERS[DEFAULT_PROVIDER]


def as_choices() -> list:
    """Model choices for the ORM field."""
    return [(key, spec.label) for key, spec in PROVIDERS.items()]


def as_catalogue() -> list:
    """The catalogue as JSON, for the platform console.

    Sent to the browser rather than hardcoded in JSX so the provider list, the
    endpoints and the capability flags have exactly one definition - the same
    reason the marketing-page editor ships its field schema from the server.
    """
    return [
        {
            'key': spec.key,
            'label': spec.label,
            'chat_api_url': spec.chat_api_url,
            'embeddings_api_url': spec.embeddings_api_url,
            'default_chat_model': spec.default_chat_model,
            'default_embedding_model': spec.default_embedding_model,
            'provides_embeddings': spec.provides_embeddings,
            'model_examples': list(spec.model_examples),
            'api_key_hint': spec.api_key_hint,
            'notes': spec.notes,
        }
        for spec in PROVIDERS.values()
    ]