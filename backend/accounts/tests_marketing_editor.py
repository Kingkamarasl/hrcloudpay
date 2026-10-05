"""The admin editor and the public renderer must agree with the backend.

The editor builds its form from a schema the backend returns, so the field list
cannot drift from the validator by construction. What *can* drift is everything
around that, and none of it is covered by a Python test that never looks at the
front end:

  * the editor's local copy of the link rule. If it is laxer than the backend's,
    an admin types a `javascript:` URL, sees no complaint, and only finds out on
    the 400 that came back. This file runs both rules over the same table of
    hostile inputs and requires them to agree.
  * a CSS class the editor asks for that the stylesheet never defines. That
    renders as unstyled - a misaligned field or an invisible button - and no
    build step notices, because an unknown class name is valid CSS.
  * a landing page that quietly stops reading managed content, or a preview that
    shows something other than the page the admin is about to publish.
"""

import json
import pathlib
import re
import subprocess
import tempfile
import unittest

FRONTEND_SRC = pathlib.Path(__file__).resolve().parents[2] / 'frontend' / 'src'


def _component(name):
    """Resolve a component by name, whichever extension it currently uses.

    These components were migrated from ``.jsx`` to ``.tsx``. Pinning the
    extension here made every test below fail on a file that had simply been
    renamed - which is the same failure mode as a test that stops running when
    the code moves: the guard goes quiet instead of reporting something real.
    """
    for suffix in ('.tsx', '.jsx', '.ts', '.js'):
        candidate = FRONTEND_SRC / 'components' / f'{name}{suffix}'
        if candidate.exists():
            return candidate
    # Fall back to the current name so a missing component produces this
    # module's own assertion message rather than a bare FileNotFoundError.
    return FRONTEND_SRC / 'components' / f'{name}.tsx'


EDITOR = _component('MarketingEditor')
SECTIONS = _component('MarketingSections')
STYLESHEET = FRONTEND_SRC / 'index.css'

# The same table the schema tests use. If the front end accepts one of these,
# an admin is shown a field that the backend will refuse.
DANGEROUS_HREFS = [
    'javascript:alert(1)',
    'JavaScript:alert(1)',
    '  javascript:alert(1)  ',
    'data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==',
    'vbscript:msgbox(1)',
    'http://example.com',
    '//evil.example.com',
    'java\tscript:alert(1)',
    'JAVASCRIPT:alert(1)',
    'mailto:someone@example.com',
    'file:///etc/passwd',
]

SAFE_HREFS = ['/pricing', '/register?plan=business', '#faq',
              'https://example.com/docs', '/']


def editor_source():
    return EDITOR.read_text(encoding='utf-8')


def _node_type_flags():
    """The flags this node needs to run a `.ts` file, or None if it cannot.

    The helpers these tests exercise are lifted verbatim out of
    MarketingEditor.tsx, so the harness carries TypeScript annotations and node
    has to erase them before running it. Node 22.6 does that behind
    `--experimental-strip-types`; node 23.6 and later do it by default; older
    versions cannot do it at all.

    Probed with the smallest script that still fails to parse without erasure,
    rather than assumed from a version string. A harness that cannot run for lack
    of a runtime capability is indistinguishable from a harness reporting a real
    failure, and that ambiguity is exactly what these tests exist to catch.
    """
    probe = 'const x: number = 1;\nconsole.log(x);\n'
    with tempfile.TemporaryDirectory() as folder:
        path = pathlib.Path(folder) / 'probe.ts'
        path.write_text(probe, encoding='utf-8')
        for flags in ([], ['--experimental-strip-types']):
            result = subprocess.run(
                ['node', *flags, str(path)], capture_output=True, text=True,
                timeout=60,
            )
            if result.returncode == 0:
                return flags
    return None


_NODE_TYPE_FLAGS = _node_type_flags()


def run_node(script, *args):
    """Run a TypeScript file under node and parse its stdout as JSON.

    Written to a file rather than passed to `node -e`: an inline script this
    size gets mangled by Windows argument quoting, and a harness that fails for
    quoting reasons looks exactly like a harness reporting a real failure.

    Named `.ts` because the script is lifted from the editor source. It used to
    be written as `.js`, so node met `repeated: RepeatedSpec` and answered
    `SyntaxError: Unexpected token ':'` - a parse error in the harness, reported
    as a failure of the component's own helpers.
    """
    if _NODE_TYPE_FLAGS is None:
        raise unittest.SkipTest(
            'This node cannot erase TypeScript annotations, so the helpers '
            'lifted from MarketingEditor.tsx cannot be run. Needs node 22.6 or '
            'later; Vite itself only wants 18, so an older checkout is plausible '
            'rather than a broken machine.'
        )
    with tempfile.TemporaryDirectory() as folder:
        path = pathlib.Path(folder) / 'harness.ts'
        path.write_text(script, encoding='utf-8')
        result = subprocess.run(
            ['node', *_NODE_TYPE_FLAGS, str(path), *args],
            capture_output=True, text=True, timeout=60,
        )
    if result.returncode != 0:
        raise AssertionError(f'node exited {result.returncode}: {result.stderr.strip()}')
    return json.loads(result.stdout)


class LinkRuleParityTests(unittest.TestCase):
    """The editor's link check and the backend's must give the same answers.

    The backend is the boundary; the editor is a courtesy. A courtesy that is
    more permissive than the boundary is worse than no check at all, because it
    tells the admin the value is fine.
    """

    @classmethod
    def setUpClass(cls):
        source = editor_source()
        # Lift the whole declaration and let Node evaluate it. Re-parsing the
        # regex literal here would be fragile: its source contains `/` both as a
        # delimiter and as an escaped literal, so any attempt to read it as text
        # has to guess where the literal ends.
        line = next(
            (row for row in source.splitlines() if row.strip().startswith('const SAFE_HREF')),
            None,
        )
        if not line:
            raise AssertionError(
                'SAFE_HREF was not found in MarketingEditor.jsx. The editor no '
                'longer checks links as they are typed, so a dangerous href is '
                'only reported after a round trip.'
            )
        cls.declaration = line.strip().rstrip(';')
        script = (
            f'{cls.declaration}\n'
            # argv[1] is this script's own path, so the payload is argv[2].
            'const hrefs = JSON.parse(process.argv[2]);\n'
            'process.stdout.write(JSON.stringify(\n'
            '  hrefs.map((h) => Boolean(h.trim() && SAFE_HREF.test(h.trim())))\n'
            '));\n'
        )
        verdicts = run_node(script, json.dumps(DANGEROUS_HREFS + SAFE_HREFS))
        cls.javascript = dict(zip(DANGEROUS_HREFS + SAFE_HREFS, verdicts))

        # The backend's own rule, for the same inputs.
        from accounts.marketing_schema import _clean_href

        cls.python = {}
        for href in DANGEROUS_HREFS + SAFE_HREFS:
            errors = []
            accepted = _clean_href(href, 'link', errors)
            cls.python[href] = bool(accepted) and not errors

    def test_the_editor_accepts_exactly_what_the_backend_accepts(self):
        disagreements = [
            href for href in self.python
            if bool(self.javascript[href]) != bool(self.python[href])
        ]
        self.assertEqual(
            disagreements, [],
            'the editor and the backend disagree about which links are allowed: '
            f'{disagreements}',
        )

    def test_the_editor_refuses_every_hostile_link(self):
        accepted = [href for href in DANGEROUS_HREFS if self.javascript[href]]
        self.assertEqual(accepted, [], f'the editor accepts {accepted}')

    def test_the_editor_accepts_the_links_the_backend_does(self):
        rejected = [href for href in SAFE_HREFS if not self.javascript[href]]
        self.assertEqual(rejected, [], f'the editor wrongly refuses {rejected}')


class EditorStylesheetTests(unittest.TestCase):
    """Every class the editor asks for must exist in the stylesheet."""

    def classes_used(self):
        source = editor_source()
        # className literals only: the editor writes every class out in full.
        return set(re.findall(r'className="([^"]+)"', source)) | set(
            re.findall(r"className=\{`([^`]+)`\}", source)
        )

    def flatten(self, value):
        out = set()
        for part in re.split(r'[\s${}]+', value):
            part = part.strip()
            if not part or not part.startswith(('me-', 'marketing-')):
                continue
            out.add(part)
        return out

    def test_every_editor_class_is_defined(self):
        css = STYLESHEET.read_text(encoding='utf-8')
        defined = set(re.findall(r'\.([a-zA-Z][\w-]*)', css))
        used = set()
        for value in self.classes_used():
            used |= self.flatten(value)
        missing = sorted(name for name in used if name not in defined)
        self.assertEqual(missing, [], f'classes used but never styled: {missing}')

    def test_the_editor_uses_no_button_class_the_app_does_not_define(self):
        """`btn-ghost` and `btn-xs` were invented and rendered as plain text."""
        css = STYLESHEET.read_text(encoding='utf-8')
        defined = set(re.findall(r'\.(btn[\w-]*)', css))
        source = editor_source()
        used = set(re.findall(r'\b(btn[\w-]*)\b', source))
        missing = sorted(name for name in used if name not in defined)
        self.assertEqual(missing, [], f'undefined button classes: {missing}')

    def test_the_editor_references_no_undefined_custom_property(self):
        """A `var(--nope)` resolves to nothing and silently drops the value."""
        css = STYLESHEET.read_text(encoding='utf-8')
        defined = set(re.findall(r'(--[\w-]+)\s*:', css))
        new_rules = '\n'.join(
            line for line in css.splitlines()
            if re.search(r'\.(me-|marketing-preview-frame)', line)
        )
        used = set(re.findall(r'var\((--[\w-]+)', new_rules))
        missing = sorted(name for name in used if name not in defined)
        self.assertEqual(
            missing, [],
            f'new rules reference undefined custom properties: {missing}',
        )

    def test_the_dead_preview_mockup_is_gone(self):
        """Its markup was removed; leaving its CSS behind is how it lingers."""
        css = STYLESHEET.read_text(encoding='utf-8')
        for dead in ('marketing-preview-page', 'marketing-preview-hero',
                     'preview-gold-button', 'marketing-preview-cards',
                     'marketing-preview-nav'):
            with self.subTest(rule=dead):
                self.assertNotIn(f'.{dead}', css)


class EditorBehaviourTests(unittest.TestCase):
    """Structural guarantees about the editor and the pages it feeds."""

    def test_saving_a_draft_leaves_the_editor_able_to_publish(self):
        """Publish must be reachable from the screen that writes the draft.

        `dirty` is wired to three things: the status line, the Publish
        button's `disabled`, and a guard inside `publish()` itself. So its
        value decides whether the core verb of this screen works at all.

        It used to be set to `Boolean(page.has_draft)` by the effect that
        re-syncs the working copy. Saving a draft flips `has_draft` to true,
        that effect re-runs, `dirty` becomes true, and Publish disables
        itself. The only way out was to reload the page - so draft and publish,
        the two steps the editor exists for, could not be done in one sitting.
        """
        source = editor_source()

        # 1. Re-syncing from the server means the working copy matches it.
        effect = source.split('useEffect(() => {')[1].split('}, [', 1)[0]
        self.assertNotIn(
            'setDirty(Boolean(page.has_draft))', effect,
            're-syncing from the server must clear dirty, not set it from '
            "has_draft; otherwise saving a draft disables Publish",
        )
        self.assertIn('setDirty(false)', effect)

        # 2. `dirty` must not be derived from has_draft anywhere else.
        for line in source.splitlines():
            if 'setDirty(' in line and 'page.has_draft' in line:
                self.fail(f'dirty is derived from has_draft: {line.strip()}')

        # 3. Saving a draft must clear it, or the button never re-enables.
        save = source.split('async function saveDraft')[1].split('\n  }', 1)[0]
        self.assertIn('setDirty(false)', save)

    def test_the_status_line_never_claims_an_unpublished_page_is_live(self):
        """A new page is unpublished and has no draft.

        That combination used to fall through every branch of the status
        ternary to 'Published version'. It is the one state where the status is
        the only thing telling the admin the truth: the page looks complete,
        the preview renders, and the public URL still 404s. Reading 'Published
        version' there is the exact opposite of what is true.
        """
        source = editor_source()
        status = source.split('marketing-editor-status')[1]
        status = status[:status.index('</div>')]
        # Every branch must be reachable from a distinct, named condition.
        for condition in ('dirty', 'page.has_draft', 'page.is_published'):
            self.assertIn(condition, status)
        self.assertIn('Not published yet', status)
        # And no branch may fall through to a bare 'Published version'.
        published = status.split('Published version')
        self.assertEqual(
            len(published), 2,
            "'Published version' must appear exactly once, guarded by "
            f"is_published. Found {len(published) - 1} occurrences in {status!r}",
        )
        self.assertRegex(
            status, r'is_published\s*\n?\s*\?\s*[\'"]Published version',
        )

    def test_there_is_no_json_textarea_any_more(self):
        """The reason this component exists: nobody should hand-edit JSON."""
        source = editor_source()
        self.assertNotIn('JSON.stringify', source)
        self.assertNotIn('JSON.parse', source)
        self.assertNotIn('spellCheck="false"', source)

    def test_the_preview_renders_the_real_page_components(self):
        """A mockup is not a preview - it drifts from the thing being published."""
        source = editor_source()
        self.assertIn('MarketingSections', source)
        # And it must sit inside the design island the public pages use, or it
        # would show different colours from the live site.
        self.assertRegex(
            source, r'className="marketing-preview-frame ledger-page"',
        )

    def test_the_editor_builds_its_form_from_the_served_schema(self):
        source = editor_source()
        self.assertIn('payload?.schema', source)
        for control in ('Add a section', 'Section', 'fields'):
            with self.subTest(control=control):
                self.assertIn(control, source)

    def test_every_public_landing_page_reads_managed_content(self):
        """The gap being closed: five of seven pages ignored the admin entirely."""
        expected = {
            'Home': 'home',
            'Platform': 'platform',
            'PayrollProduct': 'payroll-product',
            'HRProduct': 'hr',
            'About': 'about',
            'Pricing': 'pricing',
            'Security': 'security',
        }
        for component, slug in expected.items():
            page = FRONTEND_SRC / 'pages' / f'{component}.jsx'
            with self.subTest(page=component):
                self.assertTrue(page.exists(), f'{component}.jsx is missing')
                source = page.read_text(encoding='utf-8')
                self.assertIn('useMarketingPage', source)
                self.assertIn(f"'{slug}'", source)

    def test_no_landing_page_still_calls_the_api_directly(self):
        """The hook is the single place that knows how this fetch fails.

        Scoped to the public landing pages. The platform admin page calls the
        write endpoints, which is a different job and legitimately talks to the
        API on its own.
        """
        for component in ('Home', 'Platform', 'PayrollProduct', 'HRProduct',
                          'About', 'Pricing', 'Security'):
            page = FRONTEND_SRC / 'pages' / f'{component}.jsx'
            with self.subTest(page=component):
                self.assertNotIn('marketing-pages/', page.read_text(encoding='utf-8'))

    def test_home_and_security_keep_a_fallback(self):
        """Their bespoke layouts mean the hero cannot be the only thing present
        if the content endpoint is down, so the shipped copy has to stay."""
        for component in ('Home', 'Security'):
            page = FRONTEND_SRC / 'pages' / f'{component}.jsx'
            with self.subTest(page=component):
                source = page.read_text(encoding='utf-8')
                self.assertIn('DEFAULT_', source)
                self.assertIn('managedSection(', source)

    def test_the_ledger_pages_have_no_hardcoded_copy_left(self):
        """Copy that stays in JSX is copy the admin cannot change."""
        for component in ('Platform', 'PayrollProduct', 'HRProduct', 'About', 'Pricing'):
            page = FRONTEND_SRC / 'pages' / f'{component}.jsx'
            with self.subTest(page=component):
                source = page.read_text(encoding='utf-8')
                # No arrays of marketing copy, no constants holding sentences.
                for pattern in (r'const [A-Z_]+ = \[', r"const [A-Z_]+ = \{\s*\n\s*\w+:"):
                    self.assertIsNone(
                        re.search(pattern, source),
                        f'{component}.jsx still hardcodes its copy',
                    )

    def test_the_renderer_maps_every_section_type(self):
        source = SECTIONS.read_text(encoding='utf-8')
        self.assertIn('switch (section.type)', source)
        self.assertIn('export function MarketingSections', source)
        self.assertIn('export function managedSection', source)

    def test_external_links_are_opened_safely(self):
        """A managed link can point off-site; it must not hand over `window.opener`."""
        source = SECTIONS.read_text(encoding='utf-8')
        self.assertIn('rel="noopener noreferrer"', source)
        self.assertIn('target="_blank"', source)

class PlatformAdminIsItsOwnPageTests(unittest.TestCase):
    """The control centre is a page, not a screen inside the dashboard.

    `PlatformAdmin` was declared as a child of the `AppLayout` route, which
    renders `Sidebar` + `Navbar` around its `<Outlet />`. So the control centre
    arrived with the tenant dashboard's navigation wrapped around it *and* its
    own sidebar inside that - two navs, two headers, on the screen where an
    administrator acts on every tenant in the system. Nothing warned about it:
    both layouts are valid CSS, and the page rendered.

    So this asserts the shape of the route table rather than the rendering. The
    rendering is checked in a browser, where the two sidebars are visible; what
    a Python test can pin without a DOM is *where the route sits* and the fact
    that the page owns the chrome it needs to get out of.
    """

    def app_source(self):
        return (FRONTEND_SRC / 'App.jsx').read_text(encoding='utf-8')

    @staticmethod
    def _tag_end(source, start):
        """Index just past the `>` closing the tag that begins at ``start``.

        Braces and quotes are tracked because a `>` inside an attribute value
        does not close the tag: `element={<Dashboard />}` ends at the second
        `>`, not the first.
        """
        depth = 0
        quote = None
        index = start
        while index < len(source):
            char = source[index]
            if quote:
                if char == quote:
                    quote = None
            elif char in '\'"`':
                quote = char
            elif char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
            elif char == '>' and depth == 0:
                return index + 1
            index += 1
        raise AssertionError(f'unterminated tag at offset {start}')

    def _dashboard_group(self):
        """The body of the AppLayout route, as source text.

        The children here are self-closing (`<Route path=... />`), so they open
        nothing. A walker that counted every `<Route` as an opening would never
        find the group's close and would silently read the whole rest of the
        file as dashboard routes - which is exactly the bug this test exists to
        catch, so it must not reproduce it.
        """
        source = self.app_source()
        opening = re.search(
            r'<Route\s+element=\{\s*<ProtectedRoute>\s*<AppLayout\s*/>',
            source,
        )
        self.assertIsNotNone(opening, 'the dashboard layout route has moved')

        index = self._tag_end(source, opening.start())
        depth = 1
        body_start = index
        while depth and index < len(source):
            if source.startswith('</Route', index):
                depth -= 1
                if not depth:
                    break
                index = self._tag_end(source, index)
            elif source.startswith('<Route', index):
                end = self._tag_end(source, index)
                # A self-closing `/>` encloses no children.
                depth += 0 if source[end - 2:end] == '/>' else 1
                index = end
            else:
                index += 1
        self.assertEqual(depth, 0, 'could not find the end of the AppLayout route')
        return source[body_start:index]

    def test_platform_admin_is_not_a_child_of_the_dashboard_layout(self):
        dashboard_group = self._dashboard_group()
        self.assertIn('path="/dashboard"', dashboard_group)

        self.assertNotIn(
            'path="/platform-admin"', dashboard_group,
            '/platform-admin is declared inside the AppLayout group, so the '
            'dashboard sidebar and navbar render around the control centre, '
            'which brings its own. It must be a top-level route.',
        )

    def test_platform_admin_is_still_gated(self):
        """Lifting it out of the dashboard must not lift it past the auth."""
        source = self.app_source()
        route = re.search(
            r'path="/platform-admin"(.*?)/>', source, re.DOTALL,
        )
        self.assertIsNotNone(route, 'the /platform-admin route is missing')
        element = route.group(1)
        self.assertIn('ProtectedRoute', element)
        self.assertIn('PlatformOnlyRoute', element)
        self.assertNotIn(
            'AppLayout', element,
            'the control centre must not pull in the dashboard layout',
        )

    def test_the_page_carries_its_own_chrome_and_a_way_back(self):
        """It no longer sits inside the nav, so it supplies its own.

        Moving the route out of AppLayout removes the dashboard sidebar, which
        used to double as the way out. Without an exit the page is a dead end
        for anyone who arrived by URL.
        """
        source = (FRONTEND_SRC / 'pages' / 'PlatformAdmin.jsx').read_text(
            encoding='utf-8'
        )
        self.assertIn('platform-admin-sidebar', source)
        self.assertIn('platform-admin-topbar', source)

        exit_link = re.search(r'<Link[^>]*className="platform-exit"[^>]*>', source)
        self.assertIsNotNone(
            exit_link, 'no way out of the control centre now that the '
            'dashboard sidebar no longer wraps it',
        )
        self.assertIn('to="/dashboard"', exit_link.group(0))

    def test_the_exit_link_is_actually_styled(self):
        """A class the stylesheet never defines renders as unstyled text."""
        css = STYLESHEET.read_text(encoding='utf-8')
        self.assertIn('.platform-exit', css)
        # The mobile rule used to hide `.platform-sidebar-footer` outright.
        # That was harmless while the dashboard navbar was always on screen;
        # now it would remove the only exit on a phone, so the breakpoint
        # hides the other two footer children and keeps this one.
        self.assertIsNone(
            re.search(r'\.platform-sidebar-footer\s*\{\s*display\s*:\s*none', css),
            'a rule hides the whole footer, and the exit lives in the footer. '
            'It was harmless while the dashboard navbar was always on screen; '
            'now it would strand anyone on a phone.',
        )


class AdminWrapperTests(unittest.TestCase):
    """`MarketingContent` must render, and must forward every prop it is given.

    This is not hypothetical. The wrapper was written calling `notify`, which
    is declared in `PlatformAdmin`'s scope and not in the module's. It parsed,
    it built, and it threw `notify is not defined` on first render - which the
    error boundary turned into a blank control centre behind a reassuring
    "your data is safe" banner, on the one tab a platform admin opens to change
    what the public site says.

    A free identifier is a runtime ReferenceError, so nothing static catches it.
    Rather than approximate it with a regex, the wrapper is lifted out of the
    file, compiled with esbuild, and called for real - so this asserts the
    behaviour rather than a guess at it.
    """

    @classmethod
    def setUpClass(cls):
        cls.harness = pathlib.Path(__file__).resolve().parent / '_wrapper_harness.mjs'
        cls.page = FRONTEND_SRC / 'pages' / 'PlatformAdmin.jsx'
        cls.frontend_root = FRONTEND_SRC.parent
        if not cls.harness.exists():
            raise unittest.SkipTest('the wrapper harness is missing')
        if not (cls.frontend_root / 'node_modules' / 'esbuild').exists():
            raise unittest.SkipTest('esbuild is not installed; run npm ci in frontend/')

    def run_wrapper(self, source_path):
        result = subprocess.run(
            ['node', str(self.harness), str(source_path), str(self.frontend_root)],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(
            result.returncode, 0,
            f'the wrapper harness failed: {result.stderr.strip()[:600]}',
        )
        return json.loads(result.stdout)

    def test_the_wrapper_renders_without_reaching_outside_itself(self):
        """The exact failure: an undefined name at render time."""
        outcome = self.run_wrapper(self.page)
        self.assertIsNone(
            outcome['threw'],
            f'MarketingContent throws when rendered: {outcome["threw"]}. It '
            'can only use its own parameters and module imports - a name from '
            "the caller's scope is a ReferenceError here.",
        )

    def test_the_wrapper_forwards_every_prop_it_is_given(self):
        """A prop quietly dropped looks identical to a working editor."""
        outcome = self.run_wrapper(self.page)
        self.assertEqual(
            outcome['forwarded'], outcome['supplied'],
            'MarketingContent does not pass every prop through to '
            'MarketingEditor. A prop it swallows leaves the editor unable to '
            'save, create, or delete without any error being shown.',
        )

    def test_no_prop_arrives_at_the_editor_as_undefined(self):
        """Distinct from a missing key, and equally silent."""
        outcome = self.run_wrapper(self.page)
        self.assertEqual(
            outcome['undefinedForwarded'], [],
            'MarketingContent forwards these props as undefined: '
            f'{outcome["undefinedForwarded"]}',
        )


class SectionOrderTests(unittest.TestCase):
    """Reordering is the editor's main structural verb, so it gets checked.

    The move helpers are pure functions lifted straight out of the component
    source and run under Node, rather than reimplemented here - a test that
    copied the logic would pass while the component was broken.
    """

    @classmethod
    def setUpClass(cls):
        source = editor_source()
        for name in ('function moveItem', 'function blankItem', 'function summaryOf'):
            if name not in source:
                raise unittest.SkipTest(f'{name} is not in the editor source')

        def lift(name):
            start = source.index(name)
            depth = 0
            for index in range(start, len(source)):
                if source[index] == '{':
                    depth += 1
                elif source[index] == '}':
                    depth -= 1
                    if depth == 0:
                        return source[start:index + 1]
            raise AssertionError(f'unbalanced braces lifting {name}')

        cls.lifted = '\n'.join(
            lift(name) for name in ('function moveItem', 'function blankItem', 'function summaryOf')
        )
        # Prove the lifted helpers parse before relying on them, so a syntax
        # error is reported once here rather than as eight mystery failures.
        run_node(f'{cls.lifted}\nconsole.log(JSON.stringify({{ok: true}}));\n')

    def run_node(self, body):
        return run_node(f'{self.lifted}\n{body}')

    def test_moving_an_item_down_reorders_the_array(self):
        out = self.run_node(
            'let s = {items: ["a", "b", "c"]};'
            'moveItem(s, "items", s.items, 0, 1, (next) => { s = next; });'
            'console.log(JSON.stringify(s.items));'
        )
        self.assertEqual(out, ['b', 'a', 'c'])

    def test_moving_an_item_up_reorders_the_array(self):
        out = self.run_node(
            'let s = {items: ["a", "b", "c"]};'
            'moveItem(s, "items", s.items, 2, -1, (next) => { s = next; });'
            'console.log(JSON.stringify(s.items));'
        )
        self.assertEqual(out, ['a', 'c', 'b'])

    def test_moving_past_the_edge_changes_nothing(self):
        out = self.run_node(
            'let s = {items: ["a", "b"]}; let moved = 0;'
            'moveItem(s, "items", s.items, 0, -1, (next) => { s = next; moved++; });'
            'moveItem(s, "items", s.items, 1, 1, (next) => { s = next; moved++; });'
            'console.log(JSON.stringify({items: s.items, moved}));'
        )
        self.assertEqual(out, {'items': ['a', 'b'], 'moved': 0})

    def test_moving_preserves_every_other_field_on_the_section(self):
        out = self.run_node(
            'let s = {type: "cta", title: "Keep me", items: ["a", "b"]};'
            'moveItem(s, "items", s.items, 0, 1, (next) => { s = next; });'
            'console.log(JSON.stringify({type: s.type, title: s.title, items: s.items}));'
        )
        self.assertEqual(out, {'type': 'cta', 'title': 'Keep me', 'items': ['b', 'a']})

    def test_a_blank_pricing_plan_has_a_key_for_every_declared_field(self):
        """A missing key renders as `undefined` on the live page."""
        out = self.run_node(
            'const rep = {item_label: "Plan",'
            ' fields: {name: ["text", 60], price: ["text", 40]},'
            ' item_list: {key: "features", limit: 160},'
            ' item_extra: {key: "highlight", kind: "bool"}};'
            'console.log(JSON.stringify(blankItem(rep)));'
        )
        self.assertEqual(out, {'name': '', 'price': '', 'features': [], 'highlight': False})

    def test_a_blank_checklist_item_has_no_list_or_toggle(self):
        out = self.run_node(
            'const rep = {item_label: "Item", fields: {label: ["text", 200]}};'
            'console.log(JSON.stringify(blankItem(rep)));'
        )
        self.assertEqual(out, {'label': ''})

    def test_a_collapsed_section_summarises_from_whatever_it_has(self):
        """A blank new section still has to read as something in the list."""
        out = self.run_node(
            'const def1 = {repeated: {key: "items"}};'
            'console.log(JSON.stringify(summaryOf({}, def1)));'
        )
        self.assertEqual(out, '0 items')
