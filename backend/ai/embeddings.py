import math

from .nvidia import NVIDIAError, post_json
from .provider import AIConfigurationError, decrypt_api_key, get_embeddings_config

# Verified live against the NVIDIA catalog. The previous default,
# nvidia/llama-3.2-nemoretriever-300m-embed-v2, reached end of life on 2026-07-20
# and now answers HTTP 410, so every embedding call failed on a fresh install.
DEFAULT_EMBEDDING_MODEL = 'nvidia/nemotron-3-embed-1b'

# The embeddings endpoint rejects oversized payloads. A reindex of a whole tenant's
# knowledge base is unbounded, so requests are chunked rather than sent in one go.
EMBED_BATCH_SIZE = 32


def _embed_batch(batch, *, input_type, config, api_key):
    payload = {
        'input': batch,
        'model': config.embedding_model or DEFAULT_EMBEDDING_MODEL,
        'input_type': input_type,
        'encoding_format': 'float',
        'truncate': 'END',
    }
    # Same bounded retry and the same retired-model classification as the chat
    # path, so a transient 500 does not fail a whole indexing run and a dead
    # model is reported as a configuration fault rather than a generic outage.
    data = post_json(
        config.embeddings_api_url, payload, api_key=api_key,
        timeout=config.request_timeout_seconds, model=payload['model'],
        label='NVIDIA embeddings',
    )
    rows = sorted(data.get('data', []), key=lambda row: row.get('index', 0))
    vectors = [row.get('embedding') for row in rows]
    if len(vectors) != len(batch) or any(not isinstance(v, list) for v in vectors):
        raise NVIDIAError('NVIDIA returned an unexpected embeddings response.')
    return vectors


def embed_texts(texts, *, input_type='passage'):
    """Embed texts, batching requests so large callers cannot exceed payload limits.

    Returns vectors in the same order as ``texts``. Raises ``NVIDIAError`` if any
    batch fails; callers treat that as a degraded index rather than partial data.
    """
    cleaned = [str(t).strip() for t in texts if str(t).strip()]
    if not cleaned:
        return []
    try:
        # Not get_active_config: the active provider may be OpenRouter, which has
        # no embedding endpoint. Resolving an embeddings-capable configuration
        # keeps the knowledge base working while chat runs somewhere else.
        config = get_embeddings_config()
        api_key = decrypt_api_key(config)
    except AIConfigurationError as exc:
        raise NVIDIAError(str(exc)) from exc
    vectors = []
    for start in range(0, len(cleaned), EMBED_BATCH_SIZE):
        vectors.extend(_embed_batch(cleaned[start:start + EMBED_BATCH_SIZE], input_type=input_type, config=config, api_key=api_key))
    return vectors


def cosine_similarity(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def embedding_is_current(chunk, model_name, dimension):
    """Whether a stored chunk vector can be compared against the active model.

    Changing the configured embedding model leaves every previously stored vector
    in a different space. ``cosine_similarity`` returns 0.0 on a dimension mismatch
    rather than raising, so without this check a model change silently degrades
    semantic search to keyword-only with nothing to indicate why.
    """
    vector = chunk.embedding
    if not vector:
        return False
    if chunk.embedding_model and model_name and chunk.embedding_model != model_name:
        return False
    return not dimension or len(vector) == dimension


def document_needs_reindex(document, model_name):
    """True when any chunk of ``document`` cannot be compared against ``model_name``."""
    if not model_name:
        return False
    return any(
        not chunk.embedding or (chunk.embedding_model and chunk.embedding_model != model_name)
        for chunk in document.chunks.only('embedding', 'embedding_model')
    )
