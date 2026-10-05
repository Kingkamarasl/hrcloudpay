"""The platform console's two tab lists must agree.

`tabs` and `navGroups` are parallel structures that have to stay in step: `tabs`
supplies a label for the breadcrumb and the page heading, `navGroups` supplies
the sidebar buttons that actually set the tab. A tab added to only one of them
is not half-wired - it is unreachable, and the page it renders is dead code that
looks finished.

That is not hypothetical. The Search (SEO) tab was added to `tabs` and given a
`tab==='seo'&&` render branch, and it still did not appear in the console,
because the sidebar renders from `navGroups`. The same check then found `plans`
had been unreachable since it was written: a full create/edit component with a
render branch and no way to reach it.
"""

import ast
import re
import unittest
from pathlib import Path

FRONTEND_SRC = Path(__file__).resolve().parents[2] / 'frontend' / 'src'
PAGE = FRONTEND_SRC / 'pages' / 'PlatformAdmin.jsx'


def _module_source():
    return PAGE.read_text(encoding='utf-8')


class PlatformAdminTabReachabilityTests(unittest.TestCase):
    """Parsed from the source, because reachability is a source-level fact."""

    @classmethod
    def setUpClass(cls):
        cls.source = _module_source()

        cls.tab_keys = set(re.findall(r"\['([a-z_]+)','[^']*'(?:,'[^']*')?\]", cls.source[:4000]))
        cls.nav_keys = set(
            re.findall(r"\['([a-z_]+)','[^']*','[a-z]+'\]", cls.source)
        )
        cls.rendered = set(re.findall(r"tab==='([a-z_]+)'&&", cls.source))

    def test_the_two_lists_were_parsed(self):
        """If either regex stops matching, the assertions below pass vacuously."""
        self.assertGreater(len(self.tab_keys), 15, 'tab list not parsed')
        self.assertGreater(len(self.nav_keys), 15, 'nav list not parsed')
        self.assertIn('seo', self.tab_keys)
        self.assertIn('seo', self.nav_keys)

    def test_every_rendered_tab_has_a_sidebar_button(self):
        """The check that would have caught the SEO tab being invisible.

        Without this, a tab can be fully implemented, registered and rendering,
        and still be impossible to click - which is exactly what shipped.
        """
        unreachable = sorted(self.rendered - self.nav_keys)
        self.assertEqual(
            unreachable, [],
            f'these tabs render but have no sidebar button, so they are '
            f'unreachable: {unreachable}',
        )

    def test_no_sidebar_button_points_at_a_tab_that_does_not_render(self):
        dead = sorted(self.nav_keys - self.rendered)
        self.assertEqual(
            dead, [],
            f'these sidebar buttons set a tab that renders nothing: {dead}',
        )

    def test_every_nav_button_has_a_label_in_the_tab_list(self):
        """Otherwise the breadcrumb falls back to "Overview" on that page."""
        unlabelled = sorted(self.nav_keys - self.tab_keys)
        self.assertEqual(
            unlabelled, [],
            f'these tabs are navigable but have no label: {unlabelled}',
        )


class PlatformAdminJsxParsesTests(unittest.TestCase):
    """The file is JSX, so node is the only parser that will read it."""

    def test_the_platform_console_parses(self):
        import json
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'probe.mjs'
            path.write_text(
                'const t = await import("node:fs");\n'
                'console.log(JSON.stringify({ok: true}));\n',
                encoding='utf-8',
            )
            result = subprocess.run(
                ['node', str(path)], capture_output=True, text=True, timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['ok'])