import json
import time
import urllib.error
import urllib.request

from django.conf import settings

from .provider import AIConfigurationError, decrypt_api_key, get_active_config

# NVIDIA's shared inference tier intermittently answers HTTP 500 on a request
# that succeeded moments earlier. Measured against the live endpoint: the full
# 7-tool payload failed 2 of 6 attempts, failing in 0.7-1.0s, while two tools
# with byte-identical schemas went 4/4 and 2/4. That is a gateway hiccup, not
# schema validation, so a single attempt makes the assistant look unreliable.
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (0.5, 1.5)
# Stop starting new attempts once this much wall clock has been spent, so a slow
# upstream cannot multiply a request past the caller's own timeout.
RETRY_TIME_BUDGET_SECONDS = 20.0


class NVIDIAError(Exception):
    pass


class AIModelUnavailableError(NVIDIAError):
    """NVIDIA has retired, removed, or cannot serve the configured model.

    A distinct subclass because this is a configuration fault that no retry can
    fix, yet it was previously reported identically to a transient outage - the
    operator saw an HTTP 503 and an opaque provider dump. It subclasses
    ``NVIDIAError`` deliberately so every existing handler keeps working
    unchanged: the tool-calling fallback in ``generate_reply`` and the degraded
    knowledge index in ``knowledge_views`` both catch ``NVIDIAError``.
    """


def _provider_detail(body):
    """Pull the human-readable message out of an NVIDIA problem document."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return body[:300]
    if isinstance(data, dict):
        for key in ('detail', 'message', 'error'):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value[:300]
            if isinstance(value, dict):
                nested = value.get('message') or value.get('detail')
                if isinstance(nested, str) and nested:
                    return nested[:300]
    return body[:300]


def provider_error(code, body, model):
    """Build the right exception for an HTTP error from the NVIDIA API.

    404/410 mean the model id itself is unusable - retired, removed, or with no
    serving function behind it. The provider's own wording is preserved so a
    mistyped endpoint URL is still diagnosable, rather than being flattened into
    "model retired".
    """
    detail = _provider_detail(body)
    if code in (404, 410):
        return AIModelUnavailableError(
            f'AI model "{model}" is unavailable from NVIDIA (HTTP {code}): {detail}. '
            f'A site administrator must choose a current model in AI settings.'
        )
    return NVIDIAError(f'NVIDIA API error ({code}): {detail}')


def post_json(url, payload, *, api_key, timeout, model, label='NVIDIA API'):
    """POST JSON to an NVIDIA endpoint, retrying only genuinely transient failures.

    A 5xx, a 429, or a dropped connection is retried a bounded number of times
    with a short backoff. A 4xx is deterministic - a retired model, a bad key, a
    malformed request - and is raised immediately, so this never hides a
    configuration fault or turns one slow failure into a long wait.
    """
    body = json.dumps(payload).encode('utf-8')
    started = time.monotonic()
    last_error = None
    for attempt in range(MAX_ATTEMPTS):
        # Checked before issuing the request, not after it fails: once the budget
        # is spent the remaining attempts are abandoned and the failure that got
        # us here is reported, rather than each retry adding to the wait.
        if attempt and (time.monotonic() - started) > RETRY_TIME_BUDGET_SECONDS:
            break
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            },
            method='POST',
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            # HTTPError subclasses URLError, so it must be caught first.
            detail_body = exc.read().decode('utf-8', errors='replace')
            last_error = provider_error(exc.code, detail_body, model)
            if exc.code not in RETRYABLE_STATUS:
                raise last_error from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = NVIDIAError(f'Could not reach {label}: {exc}')
        except json.JSONDecodeError as exc:
            # A truncated or non-JSON body is not transient, so it is not retried.
            raise NVIDIAError(f'{label} returned an invalid response.') from exc
        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)])
    raise last_error if last_error else NVIDIAError(f'{label} did not respond.')


def chat_completion(messages, *, tools=None, model=None, temperature=None, max_tokens=None):
    """Call the chat completions endpoint.

    ``temperature`` and ``max_tokens`` default to the provider config when left as
    None. They previously defaulted to literal values that were then compared
    against, so a caller who genuinely asked for temperature 0.3 silently got the
    configured value instead.
    """
    try:
        config = get_active_config()
        api_key = decrypt_api_key(config)
    except AIConfigurationError as exc:
        raise NVIDIAError(str(exc)) from exc

    payload = {
        'model': model or config.chat_model,
        'messages': messages,
        'temperature': config.temperature if temperature is None else temperature,
        'top_p': 0.8,
        'max_tokens': config.max_tokens if max_tokens is None else max_tokens,
        'stream': False,
    }
    if tools:
        payload['tools'] = tools
        payload['tool_choice'] = 'auto'

    return post_json(
        config.chat_api_url, payload, api_key=api_key,
        timeout=config.request_timeout_seconds, model=payload['model'],
        label='NVIDIA AI',
    )


def chat(messages, **kwargs):
    data = chat_completion(messages, **kwargs)
    try:
        return data['choices'][0]['message']['content'].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise NVIDIAError('NVIDIA returned an unexpected response.') from exc
