"""Marketing and legal copy may only claim what the code actually does.

The privacy policy shipped claiming "IP allow-listing" and "single sign-on where
configured". Neither is implemented: no allow-list exists anywhere in the
codebase, and `SSOProvider` stores a configuration that no login route reads -
`security/urls.py` has no SSO authenticate or callback endpoint.

The SSO one is worse than a stale sentence. An administrator who configures SSO
and believes they have turned it on has changed nothing, while the password
login path stays open. A document that promises a control is worse than a
document that admits its absence, because the reader stops checking.

Writing legal copy is exactly where an unverified claim is most likely, since
the sentences are long, plausible and written once. So the claims are pinned
here rather than trusted to review.

Each entry below maps a phrase to the evidence that makes it true. Adding a
claim means adding an entry. Removing a feature means the test fails and the
copy gets corrected - which is the direction that should be expensive.
"""

import pathlib
import re

from django.test import SimpleTestCase, TestCase

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend'
FRONTEND = ROOT / 'frontend' / 'src'

# Marketing and legal copy lives in migrations, in the marketing editor's seed
# data, and in the bespoke JSX pages.
COPY_SOURCES = [
    BACKEND / 'accounts' / 'migrations' / '0018_seed_marketing_pages.py',
    BACKEND / 'accounts' / 'migrations' / '0026_homepage_positioning.py',
    BACKEND / 'accounts' / 'migrations' / '0027_legal_pages.py',
    FRONTEND / 'pages' / 'Security.jsx',
    FRONTEND / 'pages' / 'Home.jsx',
    FRONTEND / 'pages' / 'About.jsx',
]

# Phrases that must never appear anywhere in customer-facing copy, because
# nothing in the codebase implements them. Matched with word boundaries, not as
# bare substrings: 'sso' as a substring matches any word containing those
# letters.
#
# Two-factor authentication is deliberately NOT here. It is implemented -
# MFAView, MFAVerifyView, MFADevice, RecoveryCode - and is asserted below so that
# removing it fails in the correct direction.
#
# "end-to-end encryption" is here for a specific reason: it was discussed and
# correctly rejected. Credentials reach a server that must verify them, so there
# is no end-to-end property to claim. It is the most attractive-sounding phrase
# available to someone selling payroll software, which is why it needs a fence.
UNSUPPORTED_PATTERNS = [
    re.compile(r'end[- ]to[- ]end (?:encrypt\w*|security)', re.I),
    re.compile(r'zero[- ]knowledge', re.I),
    re.compile(r'ip allow[- ]?list\w*', re.I),
    re.compile(r'ip white[- ]?list\w*', re.I),
]

# Controls that exist in the model layer but have no working login path, so they
# must never be listed as available - while being perfectly honest to list them
# as planned.
#
# `SSOProvider` stores a configuration; `security/urls.py` has no SSO
# authenticate or callback route, so configuring SSO changes nothing while the
# password path stays open. Retention controls have no implementation at all.
ROADMAP_ONLY = {
    r'\bsso\b': 'SSO',
    r'single sign[- ]on': 'SSO',
    r'retention control': 'retention controls',
}

ROADMAP_PATTERNS = [(re.compile(p, re.I), label) for p, label in ROADMAP_ONLY.items()]

# Security controls that ARE implemented, and what implements them. A claim is
# allowed only if something in this table backs it.
IMPLEMENTED = {
    'two-factor authentication': (
        ['security/views.py'], r'class MFAView|class MFAVerifyView|MFADevice'),
    'api token': (
        ['hrcloudpay/settings.py'], r'rest_framework\.authtoken'),
    'hash-chain': (
        ['accounts/audit.py'], r'hash'),
    'one-way hash': (
        ['hrcloudpay/settings.py'], r'AUTH_PASSWORD_HASHERS|AUTH_USER_MODEL'),
}


def _all_copy():
    for path in COPY_SOURCES:
        if path.exists():
            yield path, path.read_text(encoding='utf-8', errors='ignore')


def _backend_source(fragments):
    matches = []
    for path in BACKEND.rglob('*.py'):
        if 'site-packages' in str(path) or '.venv' in str(path):
            continue
        if not any(path.as_posix().endswith(f) for f in fragments):
            continue
        matches.append(path.read_text(encoding='utf-8', errors='ignore'))
    return '\n'.join(matches)


class UnsupportedClaimTests(SimpleTestCase):
    def test_no_copy_claims_an_unimplemented_control(self):
        offenders = []
        for path, source in _all_copy():
            for n, line in enumerate(source.splitlines(), 1):
                for pattern in UNSUPPORTED_PATTERNS:
                    if pattern.search(line):
                        offenders.append('%s:%d -> %s'
                                          % (path.name, n, pattern.pattern))
        self.assertEqual(offenders, [],
                         'copy claims a control that does not exist: %s' % offenders)

    def test_two_factor_authentication_is_actually_implemented(self):
        """Guards the fix above from becoming its own inaccuracy.

        The privacy policy names two-factor authentication. If that feature is
        removed, the test above will not catch it - it only rejects absent
        claims, and this one is present. This asserts the claim stays true.
        """
        source = _backend_source(['security/views.py'])
        self.assertRegex(source, r'class MFAView')
        self.assertRegex(source, r'class MFAVerifyView')

    def test_api_tokens_are_actually_implemented(self):
        self.assertRegex(
            _backend_source(['hrcloudpay/settings.py']),
            r'rest_framework\.authtoken')

    def test_no_sso_login_route_exists_behind_the_sso_config(self):
        """`SSOProvider` is stored; nothing reads it to log anyone in.

        This is the honest form of the gap above. Until a login route exists,
        configuring SSO changes nothing while the password path stays open - so
        the test asserts the absence, and will fail the day someone wires SSO up
        and the copy becomes true again.
        """
        urls = _backend_source(['security/urls.py'])
        self.assertNotRegex(urls, r'sso/.*(auth|callback|login)',
                            'an SSO login route now exists - the copy can claim it')

    def test_no_ip_allowlist_exists_anywhere(self):
        for path in BACKEND.rglob('*.py'):
            resolved = str(path)
            if 'site-packages' in resolved or '.venv' in resolved:
                continue
            # This file names the pattern in order to forbid it. Scanning itself
            # would mean the guard can never be satisfied.
            if path.name == 'tests_copy_claims.py':
                continue
            text = path.read_text(encoding='utf-8', errors='ignore')
            self.assertNotRegex(
                text, r'allowed_ip|ip_allowlist|ip_whitelist',
                'an IP allow-list now exists in %s - update the policy' % path.name)


class RoadmapHonestyTests(SimpleTestCase):
    """A planned control may be named as planned. It may not be named as shipped.

    The Security page ships two lists - "Available today" and "Next on the
    roadmap" - and listed single sign-on under the first while no login route
    existed. Being honest about a roadmap is good practice; being wrong about
    which list a control is in is the problem, so the split is what gets checked.
    """

    def _roadmap_lists(self):
        source = (FRONTEND / 'pages' / 'Security.jsx').read_text(encoding='utf-8')
        # The two lists sit inside one section: "Available today", then
        # "Next on the roadmap". Take everything between the first label and the
        # end of the section, which is the next opening tag.
        block = re.search(r'Available today(.*?)<section', source, re.S)
        self.assertIsNotNone(block, 'the Security page roadmap lists are gone')
        block = block.group(1)
        marker = 'Next on the roadmap'
        self.assertIn(marker, block, 'the roadmap no longer has a "next" list')
        today, later = block.split(marker, 1)
        return today, later

    def test_no_planned_control_is_listed_as_available_today(self):
        today, _later = self._roadmap_lists()
        for pattern, label in ROADMAP_PATTERNS:
            self.assertNotRegex(
                today, pattern,
                '%s is listed under "Available today" but has no working '
                'implementation' % label)

    def test_single_sign_on_is_disclosed_as_planned(self):
        """Not just absent from today - it should be visible on the roadmap.

        Silently dropping it would be the other kind of dishonest: a buyer
        evaluating against an enterprise checklist can see it is planned rather
        than assuming the product has never heard of it.
        """
        _today, later = self._roadmap_lists()
        self.assertRegex(
            later.lower(), r'single sign[- ]on|\bsso\b',
            'SSO is no longer disclosed anywhere on the roadmap')

    def test_the_prose_agrees_with_the_badges(self):
        """The sentence above the badges claimed SSO and retention "today" while
        the badges immediately below put retention on the roadmap. A page that
        contradicts itself within one screen is worse than either being wrong."""
        source = (FRONTEND / 'pages' / 'Security.jsx').read_text(encoding='utf-8')
        sentence = re.search(r'HRCloudPay covers.{0,220}', source)
        self.assertIsNotNone(sentence, 'the enterprise-path sentence is gone')
        text = sentence.group(0)
        self.assertIn('today', text)
        for pattern, label in ROADMAP_PATTERNS:
            near = text.split('today')[0]
            self.assertNotRegex(
                near, pattern,
                'the sentence claims %s works today, but the badge list below '
                'says otherwise' % label)


class SecurityPageClaimTests(TestCase):
    """The Security page is the one a buyer reads before paying."""

    def setUp(self):
        from accounts.platform_models import MarketingPage

        self.rows = {p.slug: p.content for p in MarketingPage.objects.all()}

    def _claims(self):
        blob = ' '.join(
            ' '.join(
                str(block.get('title', '')) + ' ' + str(block.get('body', ''))
                for section in (content or {}).get('sections', [])
                for block in section.get('blocks', [])
            ) for content in self.rows.values()
        )
        return blob.lower()

    def test_marketing_copy_makes_no_unsupported_claim(self):
        blob = self._claims()
        for pattern in UNSUPPORTED_PATTERNS:
            self.assertNotRegex(blob, pattern,
                                'a published marketing page claims %s' % pattern.pattern)

    def test_the_immutable_audit_claim_is_backed_by_the_hash_chain(self):
        """"Immutable audit trail" is the Security page's lead claim.

        It is true, but only because entries are hash-chained - not because the
        table happens to follow an append-only convention nobody enforces. The
        chain lives in audit_chain.py, not audit.py, which is why the prose in
        audit.py ("Create an immutable audit record") is not evidence of it.
        """
        blob = self._claims()
        if 'immutable' in blob or 'append-only' in blob:
            source = _backend_source(['accounts/audit_chain.py'])
            self.assertIn('hashlib', source)
            self.assertRegex(source, r'def .*verify|verify_chain')
        verifier = BACKEND / 'accounts' / 'management' / 'commands' / 'verify_audit_chain.py'
        self.assertTrue(verifier.exists(),
                        'verify_audit_chain.py is missing, so the chain is unverified')