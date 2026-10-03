"""Schema and validation for platform-managed marketing content.

The platform admin can edit customer-facing landing pages. That content is
rendered as `href` attributes and text on public pages, so "the admin typed
JSON" is not a safe storage format: an unknown section type crashes the public
renderer, an over-long string breaks a layout, and a `javascript:` URL in a
button becomes a cross-site scripting hole on every visitor's page.

This module is the single definition of what a marketing page may contain. It
does three things:

  * describe the section types the renderer knows how to draw (`SECTION_TYPES`),
    which doubles as the field list the admin editor builds its form from, so
    adding a field in one place updates validation and the editor together;
  * validate and normalise untrusted content (`validate_content`), returning
    cleaned data plus human-readable errors rather than raising, so the editor
    can show what is wrong with which field;
  * restrict every link to a safe target (`_clean_href`), which is the only
    place in the content path where a URL scheme is trusted.

Deliberately *not* generic: content describes copy and section order, not
layout. Each landing page keeps its bespoke design in JSX and renders whatever
sections it is given. That keeps an admin edit from being able to restyle a
page, which is not a privilege the product needs to grant.
"""

import re

# A page slug becomes part of a public URL and of the admin API path, so it is
# held to the same shape Django's SlugField accepts.
SLUG_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')

# Enough for a real landing page, low enough that a pasted document cannot be
# used to fill the row.
MAX_SECTIONS = 40
MAX_REPEATED = 60

# Schemes a managed link may use. A relative path or a fragment is safe. An
# absolute URL must be https, because a managed http:// link on a public page
# is a downgrade an attacker would use to phish through a trusted domain.
SAFE_HREF_SCHEMES = ('https://',)


def _clean_text(value, limit, label, errors, required=False):
    """Coerce to a trimmed string, truncated at `limit`, or record an error."""
    if value is None:
        value = ''
    if not isinstance(value, str):
        errors.append(f'{label} must be text.')
        return ''
    text = value.strip()
    if required and not text:
        errors.append(f'{label} is required.')
    if len(text) > limit:
        # Truncate rather than reject. An over-long headline is a typo, and
        # losing the edit entirely is a worse outcome than a clipped headline
        # that the admin can see and fix on the next pass.
        text = text[:limit].rstrip()
        errors.append(f'{label} was shortened to {limit} characters.')
    return text


def _clean_href(value, label, errors):
    """Validate a link target, rejecting anything that can execute script.

    This is a security boundary, not a formatting nicety. The value ends up in
    an `href` on a public page, and `javascript:` / `data:` / `vbscript:` URLs
    execute in the page's origin. Allowing only relative paths, fragments and
    https removes that class of injection entirely.
    """
    if value is None:
        return ''
    if not isinstance(value, str):
        errors.append(f'{label} must be text.')
        return ''
    href = value.strip()
    if not href:
        return ''
    if len(href) > 300:
        errors.append(f'{label} must be 300 characters or fewer.')
        return ''
    lowered = href.lower()
    # A control character can be used to smuggle "java\tscript:" past a naive
    # prefix check in the browser while looking inert here.
    if any(ord(c) < 0x20 for c in href):
        errors.append(f'{label} contains an unsupported control character.')
        return ''
    # A protocol-relative URL ("//evil.example.com") also begins with "/", so a
    # plain startswith check lets it through. The browser resolves it against
    # the current scheme, sending the visitor to a different origin while the
    # link still reads as though it points at this site. Reject it, and the
    # backslash form browsers normalise to a slash.
    if href.startswith('//') or href.startswith('/\\'):
        errors.append(f'{label} must not be a protocol-relative address.')
        return ''
    if href.startswith('/') or href.startswith('#'):
        return href
    for scheme in SAFE_HREF_SCHEMES:
        if lowered.startswith(scheme):
            return href
    errors.append(
        f'{label} must be a site path (/pricing), an anchor (#section), or an '
        f'https:// address.'
    )
    return ''


def _clean_bool(value):
    return bool(value) if isinstance(value, (bool, int)) else False


# Field kinds: (kind, max length).
#   text     - a single line, e.g. a heading
#   longtext - a paragraph
#   href     - a link target, scheme-checked by _clean_href
#   bool     - a toggle
SECTION_TYPES = {
    'hero': {
        'label': 'Hero',
        'hint': 'The headline block at the top of the page.',
        'fields': {
            'eyebrow': ('text', 120),
            'title': ('text', 160),
            'title_accent': ('text', 160),
            'subtitle': ('longtext', 600),
            'primary_cta': ('text', 60),
            'primary_href': ('href', 300),
            'secondary_cta': ('text', 60),
            'secondary_href': ('href', 300),
        },
    },
    'feature_rows': {
        'label': 'Feature rows',
        'hint': 'A titled row and its supporting paragraph.',
        'fields': {
            'eyebrow': ('text', 120),
            'title': ('text', 200),
            'subtitle': ('longtext', 400),
        },
        'repeated': {
            'key': 'items',
            'item_label': 'Feature',
            'fields': {
                'title': ('text', 160),
                'body': ('longtext', 600),
            },
        },
    },
    'checklist': {
        'label': 'Checklist',
        'hint': 'A heading and a list of short ticked items.',
        'fields': {
            'eyebrow': ('text', 120),
            'title': ('text', 200),
            'body': ('longtext', 600),
        },
        'repeated': {
            'key': 'items',
            'item_label': 'Item',
            'fields': {
                'label': ('text', 200),
            },
        },
    },
    'prose_blocks': {
        'label': 'Prose blocks',
        'hint': 'Stacked titled paragraphs, used on the About page.',
        'fields': {
            'eyebrow': ('text', 120),
        },
        'repeated': {
            'key': 'blocks',
            'item_label': 'Block',
            'fields': {
                'title': ('text', 200),
                'body': ('longtext', 2000),
            },
        },
    },
    'pricing': {
        'label': 'Pricing plans',
        'hint': 'The plan grid and the notes underneath it.',
        'fields': {
            'eyebrow': ('text', 120),
            'title': ('text', 200),
            'subtitle': ('longtext', 400),
        },
        'repeated': {
            'key': 'plans',
            'item_label': 'Plan',
            'fields': {
                # `plan` binds the card to a real plan. `price` is not an
                # editable field any more: it is derived from PLAN_PRICES when
                # the page is served, so storing one only creates a second copy
                # that can disagree. An editor that still offers it would let an
                # admin type a number that silently never appears.
                'plan': ('text', 20),
                'name': ('text', 60),
                'tagline': ('text', 160),
                'blurb': ('text', 160),
            },
            'item_list': {'key': 'features', 'label': 'text', 'limit': 160},
            'item_extra': {'key': 'highlight', 'kind': 'bool'},
        },
        'notes': {
            'key': 'notes',
            'item_label': 'Note',
            'fields': {
                'title': ('text', 120),
                'body': ('longtext', 400),
            },
        },
    },
    'cta': {
        'label': 'Call to action',
        'hint': 'A closing band with one or two buttons.',
        'fields': {
            'eyebrow': ('text', 120),
            'title': ('text', 200),
        },
        'repeated': {
            'key': 'actions',
            'item_label': 'Button',
            'fields': {
                'label': ('text', 60),
                'href': ('href', 300),
            },
        },
    },
}


def _validate_fields(raw, spec, prefix, errors, allowed_extra=()):
    cleaned = {}
    for name, (kind, limit) in spec.items():
        label = f'{prefix}{name.replace("_", " ")}'
        if kind == 'href':
            cleaned[name] = _clean_href(raw.get(name), label, errors)
        elif kind == 'bool':
            cleaned[name] = _clean_bool(raw.get(name))
        else:
            cleaned[name] = _clean_text(raw.get(name), limit, label, errors)
    # Report keys the schema does not declare instead of dropping them in
    # silence. They are still not stored, so nothing unrenderable reaches the
    # page - but a mistyped field name would otherwise look like it saved.
    # `allowed_extra` covers the structural keys (`type`, and the repeated-list
    # and notes keys) which the caller handles itself rather than as a field.
    unknown = sorted(set(raw) - set(spec) - set(allowed_extra))
    for name in unknown:
        errors.append(
            f'{prefix}{name} is not a field of this section, so it was removed. '
            f'Allowed: {", ".join(sorted(set(spec) | set(allowed_extra)))}.'
        )
    return cleaned


def _validate_section(raw, errors):
    if not isinstance(raw, dict):
        errors.append('Each section must be an object.')
        return None
    kind = raw.get('type')
    if not isinstance(kind, str) or kind not in SECTION_TYPES:
        # Unknown types are dropped rather than stored: the public renderer
        # switches on `type`, so anything else would either crash the page or
        # render as an empty gap nobody can see from the editor.
        errors.append(
            f'Unknown section type {kind!r}. Allowed types: '
            f'{", ".join(sorted(SECTION_TYPES))}.'
        )
        return None
    definition = SECTION_TYPES[kind]
    prefix = f'{kind}.'
    section = {'type': kind}
    repeated = definition.get('repeated')
    notes = definition.get('notes')

    # Keys this section handles outside its plain field spec, so the unknown-key
    # check does not report them as mistakes.
    structural = {'type'}
    if repeated:
        structural.add(repeated['key'])
    if notes:
        structural.add(notes['key'])
    section.update(
        _validate_fields(raw, definition['fields'], prefix, errors, structural)
    )

    if repeated:
        key = repeated['key']
        items = raw.get(key)
        items = items if isinstance(items, list) else []
        if len(items) > MAX_REPEATED:
            errors.append(
                f'{prefix}{key} holds {len(items)} entries; the limit is '
                f'{MAX_REPEATED}.'
            )
            items = items[:MAX_REPEATED]
        item_list = repeated.get('item_list')
        item_extra = repeated.get('item_extra')
        item_allowed = set()
        if item_list:
            item_allowed.add(item_list['key'])
        if item_extra:
            item_allowed.add(item_extra['key'])
        cleaned_items = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f'{prefix}{key}[{index}] must be an object.')
                continue
            entry = _validate_fields(
                item,
                repeated['fields'],
                f'{prefix}{key}[{index}].',
                errors,
                item_allowed,
            )
            if item_list:
                values = item.get(item_list['key'])
                values = values if isinstance(values, list) else []
                entry[item_list['key']] = [
                    _clean_text(
                        value,
                        item_list['limit'],
                        f'{prefix}{key}[{index}].{item_list["key"]}',
                        errors,
                    )
                    for value in values[:MAX_REPEATED]
                ]
            if item_extra:
                entry[item_extra['key']] = _clean_bool(item.get(item_extra['key']))
            cleaned_items.append(entry)
        section[key] = cleaned_items

    if notes:
        raw_notes = raw.get(notes['key'])
        raw_notes = raw_notes if isinstance(raw_notes, list) else []
        section[notes['key']] = [
            _validate_fields(
                note, notes['fields'], f'{prefix}{notes["key"]}[{index}].', errors
            )
            for index, note in enumerate(raw_notes[:MAX_REPEATED])
            if isinstance(note, dict)
        ]
    return section


def validate_content(raw):
    """Validate managed page content.

    Returns `(content, blocking, advisory)`, always a 3-tuple so callers do not
    have to guess:

      * `content` is a usable dict even when there are errors, so the editor can
        render whatever it managed to understand alongside the messages;
      * `blocking` holds problems that mean the content is not safe to store
        (an unknown section type, a rejected link, a malformed list). A save
        must be refused while this is non-empty;
      * `advisory` holds recoverable notes, currently only over-long text that
        was truncated, which must not block an otherwise valid save.
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        return {'sections': []}, ['Content must be a JSON object.'], []

    sections = raw.get('sections')
    if sections is None:
        # An empty object is the state both seeded pages started in. Treat it as
        # "no sections yet" rather than an error, so an untouched page is valid.
        return {'sections': []}, [], []
    if not isinstance(sections, list):
        return {'sections': []}, ['"sections" must be a list.'], []

    errors = []
    if len(sections) > MAX_SECTIONS:
        errors.append(
            f'This page has {len(sections)} sections; the limit is {MAX_SECTIONS}.'
        )
        sections = sections[:MAX_SECTIONS]

    cleaned = []
    for raw_section in sections:
        section = _validate_section(raw_section, errors)
        if section is not None:
            cleaned.append(section)

    # Errors a save must not be blocked by: the admin gets a clear message and
    # the clipped text is still an improvement over losing the whole edit.
    advisory = [e for e in errors if 'was shortened to' in e]
    blocking = [e for e in errors if e not in advisory]
    return {'sections': cleaned}, blocking, advisory


def blank_content():
    """A new page starts with a hero, which every landing page needs."""
    return {'sections': [{'type': 'hero'}]}


def is_valid_slug(slug):
    # The 80-character ceiling mirrors MarketingPage.slug's SlugField. Without it
    # an over-long slug passes here and fails later as a database error, which
    # surfaces to the admin as a 500 instead of a field message.
    return bool(
        isinstance(slug, str)
        and 0 < len(slug) <= 80
        and SLUG_RE.match(slug)
    )


def first_section(content, kind):
    """The first section of `kind`, or {} - lets a page read just its hero."""
    for section in (content or {}).get('sections') or []:
        if section.get('type') == kind:
            return section
    return {}