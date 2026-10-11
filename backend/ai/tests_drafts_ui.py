"""The AI drafts review surface.

`AIDraftView` generated drafts, `AIDraftDetailView` approved and rejected them,
`CanManageAIDrafts` gated every method, and `DRAFT_MANAGER_ROLES` was already
declared in the frontend constants - and none of it was reachable. No route
pointed at it, no nav entry linked to it. Approval gates that no page links to
are not gates; they are a POST endpoint with good intentions.

These guard the wiring only. The approval logic keeps its own tests.
"""

import pathlib
import re

from django.test import SimpleTestCase

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / 'frontend' / 'src'
PAGE = FRONTEND / 'pages' / 'AIDrafts.jsx'
APP = FRONTEND / 'App.jsx'
SIDEBAR = FRONTEND / 'components' / 'Sidebar.tsx'
CSS = list((FRONTEND).rglob('*.css'))[0]


class AlertClassTests(SimpleTestCase):
    """An alert class that does not exist fails silently.

    The element still renders - only the colour is missing - so the page looks
    fine in review and a failed save reads as a neutral note. `error-alert` was
    wrong on Compliance, StatutoryCompliance and Workflows; the stylesheet has
    always defined `.alert-error`.
    """

    def test_no_page_uses_an_alert_class_that_does_not_exist(self):
        css = CSS.read_text(encoding='utf-8')
        offenders = []
        for page in FRONTEND.rglob('*'):
            if page.suffix not in ('.jsx', '.tsx'):
                continue
            source = page.read_text(encoding='utf-8', errors='ignore')
            for match in re.finditer(r'className="alert ([a-z-]+)"', source):
                cls = match.group(1)
                if ('.%s' % cls) not in css:
                    offenders.append('%s: %s' % (page.name, cls))
        self.assertEqual(offenders, [],
                         'alert classes with no CSS rule: %s' % offenders)


class DraftsPageTests(SimpleTestCase):
    def test_page_exists(self):
        self.assertTrue(PAGE.exists(), 'frontend/src/pages/AIDrafts.jsx is missing')

    def test_route_is_registered(self):
        self.assertRegex(APP.read_text(encoding='utf-8'), r'path="/ai-drafts"')

    def test_route_is_role_gated(self):
        """An ungated route would render the shell and 403 on every call.

        `CanManageAIDrafts` returns the full `content` and `context`, so a
        department_manager reaching this URL would be shown a page that fails
        on load - and, before the gate was added, would have read warning
        letters about colleagues.
        """
        route = re.search(r'path="/ai-drafts"[^>]*', APP.read_text(encoding='utf-8'))
        self.assertIn('DRAFT_MANAGER_ROLES', route.group(0))

    def test_sidebar_link_exists(self):
        """The failure this guards: built, routed, but invisible.

        The SEO tab was invisible for exactly this reason - the endpoint and the
        tab existed and `navGroups` was never updated. The platform-admin nav
        test covers that page; this covers the app sidebar.
        """
        self.assertRegex(SIDEBAR.read_text(encoding='utf-8'), r"to: '/ai-drafts'")

    def test_page_uses_the_existing_draft_manager_roles(self):
        """Not a hardcoded list that could drift from the backend."""
        self.assertIn('DRAFT_MANAGER_ROLES', APP.read_text(encoding='utf-8'))

    def test_approval_copy_does_not_claim_it_sends(self):
        """The endpoint records a decision; it never sends the letter.

        A control reading "Approve & send" would be a promise the API does not
        keep. The person who believed it would send a warning letter from their
        own inbox and reasonably assume the system had logged it.
        """
        source = PAGE.read_text(encoding='utf-8')
        self.assertIn('Approve for use', source)
        # Strip line comments first: the file's own header explains why "Approve
        # & send" is wrong, and that explanation must not trip its own check.
        rendered = '\n'.join(l for l in source.splitlines()
                             if not l.strip().startswith('//'))
        for claim in ['Approve &amp; send', 'Approve and send', 'Approve & send',
                      'Send letter', 'Send to employee']:
            self.assertNotIn(claim, rendered, f'the button promises it sends: {claim!r}')

    def test_every_css_class_the_page_uses_exists(self):
        """`error-alert` shipped on three pages that rendered errors unstyled.

        A class name that does not exist fails silently: the element still
        renders, just with the wrong colour, so nobody notices in review. This
        checks the page's own class usage against index.css.
        """
        css = CSS.read_text(encoding='utf-8')
        source = PAGE.read_text(encoding='utf-8')
        used = set()
        for match in re.finditer(r'className="([^"]+)"', source):
            used.update(c for c in match.group(1).split() if not c.startswith('$'))
        for match in re.finditer(r'`badge-\$\{[^}]+\}`', source):
            used.add('badge-pending')
            used.add('badge-approved')
            used.add('badge-rejected')
        unknown = sorted(c for c in used if c not in css)
        self.assertEqual(unknown, [], f'classes with no CSS rule: {unknown}')

    def test_every_icon_the_page_uses_exists(self):
        source = PAGE.read_text(encoding='utf-8')
        icons = (FRONTEND / 'components' / 'Icon.tsx').read_text(encoding='utf-8')
        names = set(re.findall(r'name="(\w+)"', source))
        for name in names:
            self.assertRegex(icons, r'(?m)^\s*%s:' % re.escape(name),
                             'Icon "%s" does not exist' % name)