"""Single source of truth for the audit chain's integrity hash.

``AuditLog.save()`` writes the digest and :func:`verify_chain` re-derives it.
If those two ever disagree by a single field or a single ``str()`` coercion the
chain reports tampering that never happened, so both import the payload builder
from here rather than each spelling out the digest independently.

Adding a field to ``chain_payload`` changes every digest ever written, so that
is a deliberate, breaking act: existing chains must be rebuilt from that point.
"""

import hashlib
import hmac
import json

# AuditChainState.last_hash default: the hash the first record links back to.
GENESIS_HASH = '0' * 64

# Every model field covered by the digest. Reported by the verifier so a
# mismatch can be diagnosed without re-reading the whole row.
HASHED_FIELDS = (
    'chain_sequence',
    'previous_hash',
    'actor_id',
    'company_id',
    'action',
    'target_type',
    'target_id',
    'message',
    'metadata',
    'request_id',
    'user_agent',
    'created_at',
)


def _reader(row):
    """Read a field from either a model instance or a plain dict."""
    if isinstance(row, dict):
        return row.get
    return lambda key: getattr(row, key)


def chain_payload(row):
    """Build the canonical payload covered by one record's digest.

    Accepts a model instance or a dict of the same keys so the writer and the
    verifier cannot drift on field set, ordering, or coercion.
    """
    get = _reader(row)
    created_at = get('created_at')
    return {
        'sequence': get('chain_sequence'),
        'previous_hash': get('previous_hash'),
        'actor_id': get('actor_id'),
        'company_id': get('company_id'),
        'action': get('action'),
        'target_type': get('target_type'),
        'target_id': get('target_id'),
        'message': get('message'),
        'metadata': get('metadata') or {},
        'request_id': get('request_id'),
        'user_agent': get('user_agent'),
        'created_at': created_at.isoformat() if hasattr(created_at, 'isoformat') else created_at,
    }


def compute_integrity_hash(row) -> str:
    """SHA-256 of the canonical payload, as stored in ``integrity_hash``."""
    payload = chain_payload(row)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _problem(kind, sequence, detail, **extra):
    return {'kind': kind, 'sequence': sequence, 'detail': detail, **extra}


def verify_chain(limit=None, start_sequence=1, max_errors=100, batch_size=500):
    """Walk the chain and re-derive every digest.

    Detects the tampering the ORM-level ``save()``/``delete()`` guards miss:
    a raw ``UPDATE`` of a hashed field, a ``bulk_create`` that bypassed
    ``save()`` entirely, a deleted row, and a truncated tail.

    ``limit`` bounds the walk (used for the cheap health check); when it is
    ``None`` the whole chain is walked and the recorded head state is
    reconciled against the last record seen, which is what catches tail
    truncation.

    Returns a dict with ``ok``, ``checked``, ``problems`` (capped at
    ``max_errors``) and a ``truncated`` flag telling the caller whether the walk
    covered everything.
    """
    from .platform_models import AuditChainState, AuditLog

    problems = []
    checked = 0
    expected = start_sequence
    prev_hash = GENESIS_HASH
    last_sequence = None
    last_hash = None
    head_sequence = None

    qs = AuditLog.objects.order_by('chain_sequence', 'id')
    if start_sequence and start_sequence > 1:
        qs = qs.filter(chain_sequence__gte=start_sequence)
    if limit:
        qs = qs[:limit]

    for row in qs.iterator(chunk_size=batch_size):
        sequence = row.chain_sequence
        if sequence is None:
            # bulk_create()/raw insert bypassed save(), so the row is not in
            # the chain at all and nothing downstream can vouch for it.
            if len(problems) < max_errors:
                problems.append(_problem(
                    'unchained_record', None,
                    f'audit log id={row.pk} has no chain sequence (written outside save())',
                    id=row.pk,
                ))
            continue

        if head_sequence is None:
            head_sequence = sequence
        if last_sequence is not None and sequence <= last_sequence:
            if len(problems) < max_errors:
                problems.append(_problem(
                    'duplicate_sequence', sequence,
                    f'chain sequence {sequence} is used more than once', id=row.pk,
                ))
        elif sequence != expected:
            if len(problems) < max_errors:
                problems.append(_problem(
                    'sequence_gap', sequence,
                    f'expected chain sequence {expected}, found {sequence} (row inserted or deleted)',
                    id=row.pk,
                ))
        # Track the sequence actually seen so one gap does not cascade into
        # an error on every following record.
        expected = sequence + 1

        if not row.integrity_hash:
            if len(problems) < max_errors:
                problems.append(_problem(
                    'missing_hash', sequence, 'record has no integrity hash', id=row.pk,
                ))
        else:
            if not hmac.compare_digest(compute_integrity_hash(row), row.integrity_hash):
                if len(problems) < max_errors:
                    problems.append(_problem(
                        'hash_mismatch', sequence,
                        'stored digest does not match the record contents '
                        '(a hashed field was modified after it was written)',
                        id=row.pk, hashed_fields=list(HASHED_FIELDS),
                    ))
            if row.previous_hash != prev_hash:
                if len(problems) < max_errors:
                    problems.append(_problem(
                        'broken_link', sequence,
                        'previous_hash does not match the preceding record', id=row.pk,
                    ))

        prev_hash = row.integrity_hash
        last_sequence = sequence
        last_hash = row.integrity_hash
        checked += 1

    state = AuditChainState.objects.filter(key='global').first()
    state_sequence = state.last_sequence if state else 0
    state_hash = state.last_hash if state else GENESIS_HASH

    # Only reconciling the head state is meaningful when the walk saw
    # everything; with a limit the caller already knows it is a sample.
    if limit is None:
        if last_sequence is None:
            if state_sequence:
                problems.append(_problem(
                    'truncated_chain', None,
                    f'chain head records sequence {state_sequence} but no records exist',
                ))
        else:
            if last_sequence != state_sequence:
                problems.append(_problem(
                    'truncated_chain', last_sequence,
                    f'chain head records sequence {state_sequence} but the last record is '
                    f'{last_sequence} (records were deleted from the tail)',
                ))
            elif not hmac.compare_digest(state_hash, last_hash or ''):
                problems.append(_problem(
                    'head_state_mismatch', last_sequence,
                    'chain head hash does not match the last record',
                ))

    return {
        'ok': not problems,
        'checked': checked,
        'problems': problems,
        'truncated': limit is not None,
        'head_sequence': state_sequence,
        'head_hash': state_hash,
        'first_sequence': head_sequence,
        'last_sequence': last_sequence,
    }
