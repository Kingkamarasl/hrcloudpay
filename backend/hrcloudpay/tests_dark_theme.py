"""Regression tests for the dark theme.

Dark mode was not a partial styling job that needed finishing. It was broken in
a way that made parts of the app unreadable, and the cause was structural.

The app shell (the "Milestone 9 redesign" block) wrote its entire palette as
~120 hardcoded hex literals: ``label { color: #52615c }``,
``.panel-head > a { color: #087f5b }``, ``.btn-primary { background: #087f5b }``
and so on. ``[data-theme="dark"]`` could not reach any of them, because there
were no variables to override. What it *did* reach was the text colours, and it
flipped those to near-white. So the two halves diverged: near-white text on
surfaces that were still pure white.

Measured across the 28 real routes before the fix:

* 129 text/background pairs below the WCAG AA threshold of 4.5:1
* 20 surfaces still painted with a light fill on a dark page

The worst were not subtly low-contrast, they were invisible. The platform-admin
``h1`` sat at 1.06:1 and the AI page's suggestion buttons at 1.11:1 - light text
on a white card, roughly the same brightness on both sides.

Seven further defects fell out of the same work:

* ``var(--surface-2)``, ``var(--surface-muted)``, ``var(--accent)``,
  ``var(--lg-gold-dark)`` and ``var(--card)`` were referenced but never defined.
  An undefined custom property with no fallback makes the *whole declaration*
  invalid at computed-value time, so the property silently reverted to its
  inherited or initial value - the styling was not wrong, it was absent.
* ``.segmented button`` set no colour, so it inherited the browser's default
  button text (black) and vanished on the dark knowledge toolbar at 1.23:1.
* ``--surface`` was ``#fff`` with no dark value of its own, so drawers and modal
  cards stayed white.
* A second, later ``label { color: #667085 }`` rule shadowed the app-shell one at
  equal specificity, so fixing the first was not enough.
* ``--lg-verdant`` is a light-theme token, but the ledger page paints itself
  ``#0b1220`` in dark mode, putting 3.01:1 verdant-green on near-black.
* A batch of status badges, notice levels and the AI draft panel were light
  pastels with mid-tone text that no dark rule reached. The 28-route audit could
  not see them at all - a badge only exists once a record carries the state that
  produces it - so a static sweep over the stylesheet found them instead.
* The tokenisation pass read and wrote this file through the platform's default
  encoding instead of UTF-8, and five characters became U+FFFD. One was not a
  comment: ``.dashboard-connection .connection-status em::before`` sets a live
  ``content:`` glyph, so the connection card's status bullet rendered a black
  diamond with a question mark instead of a middle dot.

Why these tests are invariants rather than a snapshot: a snapshot of the
stylesheet would have accepted every one of those defects. These assert the
properties that make each defect class unrepresentable - a property that is read
must be defined, a themed surface must have a dark value, a themed token must
have both, light mode must render the exact colours it always did, and the pairs
that were measured must still clear AA.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

# --------------------------------------------------------------------------
# Locating the sources
# --------------------------------------------------------------------------

REPO_ROOT = Path(settings.BASE_DIR).parent
SRC_DIR = REPO_ROOT / 'frontend' / 'src'
CSS_PATH = SRC_DIR / 'index.css'
DIST_DIR = Path(settings.BASE_DIR) / 'frontend_dist'

# The app-shell block is delimited by these two banner comments. Anchoring on
# the text inside them means a test stays attached to the code it protects even
# as lines are added above it.
APP_SHELL_START = 'HRCloudPay application redesign'
APP_SHELL_END = 'Operations / payroll redesign'

# Sections that carry their own dark palette further up the stylesheet and are
# deliberately not covered by the app tokens. They are excluded from the
# "needs a dark counterpart" sweep, not from the contrast maths.
OWN_PALETTE_PREFIXES = (
    'marketing', 'hero', 'feature', 'product-window', 'preview', 'hc-',
    'ledger', 'lg-', 'btn-light', 'module-card',
)

# Selectors with light fills, no dark counterpart, and - this is the part that
# matters - no component that renders them. They belong to a landing-page design
# that `/` no longer uses: Home.jsx renders `hc-*` classes and MarketingLayout
# renders `ledger-*`, and these four appear nowhere in the 60 jsx/js files
# (428,610 characters scanned, 0 hits each).
#
# Writing dark rules for them would be dark-mode theatre - no user would ever
# see the result. Excluding them is the honest call, but an exclusion that
# outlives its reason is how a real gap gets waved through later, so
# `test_dead_selector_exclusions_are_still_dead` fails the moment any component
# starts using one of them.
DEAD_SELECTOR_PREFIXES = ('window-bar', 'cta-section', 'mini-dashboard',
                          'module-grid')

# The light palette, recorded from the stylesheet as it stood *before* the
# tokenisation, paired with the token each literal became. Every entry is a
# literal that existed in the file; the value beside it is that literal.
#
# The `-altN` twins exist because the first pass merged several distinct
# literals onto one token and kept whichever was listed first, which shifted
# light mode on 27 declarations - 24 of them perceptible, worst being the
# `.setup-icon` disc (#f6d875 -> #d9aa25, dRGB 80) and the `.dot-leave` status
# dot (#9bd6bf -> #c7e5d9, dRGB 44). Each twin restores one literal exactly and
# inherits its parent's dark value, so dark rendering is unchanged.
APP_LIGHT_PALETTE = {
    '--app-danger-bg': '#feeaea',
    '--app-danger-dot': '#d64545',
    '--app-danger-text': '#b42318',
    '--app-heading': '#13241f',
    '--app-heading-alt1': '#172822',
    '--app-ink': '#23342e',
    '--app-ink-alt1': '#10221d',
    '--app-ink-alt2': '#33443e',
    '--app-ink-alt3': '#263631',
    '--app-ink-soft': '#52615c',
    '--app-ink-soft-alt1': '#66746f',
    '--app-line-soft': '#f0f3f2',
    '--app-line-soft-alt1': '#eef2f0',
    '--app-line-soft-alt2': '#d9e1de',
    '--app-muted': '#7d8a86',
    '--app-muted-2': '#9aa7a3',
    '--app-muted-2-alt1': '#94a39e',
    '--app-muted-2-alt2': '#9aa6a2',
    '--app-muted-2-alt3': '#94a3a0',
    '--app-muted-alt1': '#8b9995',
    '--app-muted-alt2': '#72807c',
    '--app-muted-alt3': '#8c9995',
    '--app-muted-alt4': '#8a9793',
    '--app-note-bg': '#f4f8f6',
    '--app-note-line': '#d5e5de',
    '--app-note-text': '#2f5d4e',
    '--app-on-accent': '#ffffff',
    '--app-on-dark': '#ffffff',
    '--app-primary-alt': '#f3f7f5',
    '--app-primary-glow': '#e9f7f1',
    '--app-primary-line': '#9bd6bf',
    '--app-primary-pale': '#eaf7f2',
    '--app-primary-ring': '#83c8ad',
    '--app-primary-soft': '#e8f6f0',
    '--app-primary-soft-alt1': '#f0f7f4',
    '--app-primary-soft-alt2': '#edf5f2',
    '--app-primary-tint': '#dff2eb',
    '--app-primary-tint-alt1': '#ccecdf',
    '--app-primary-tint-alt2': '#e5f6ee',
    '--app-surface': '#ffffff',
    '--app-surface-alt': '#fafcfc',
    '--app-surface-alt-alt1': '#f1f5f9',
    '--app-surface-sunken': '#fbfcfc',
    '--app-upgrade-bg': '#102d26',
    '--app-upgrade-ink': '#7ee0ba',
    '--app-upgrade-muted': '#b9ccc6',
    '--app-warn-bg': '#fff5d8',
    '--app-warn-bg-alt1': '#fff9e9',
    '--app-warn-dot': '#d9aa25',
    '--app-warn-dot-alt1': '#f6d875',
    '--app-warn-line': '#f1e3b9',
    '--app-warn-text': '#9b7400',
    '--app-warn-text-alt1': '#725500',
    '--app-warn-text-alt2': '#877753',
    '--app-warn-text-alt3': '#775d00',
}

# Properties that are read but were never defined, so each declaration naming
# one was discarded silently.
PREVIOUSLY_UNDEFINED = ('--surface-2', '--surface-muted', '--accent',
                        '--lg-gold-dark', '--card')


def _read(path):
    return path.read_text(encoding='utf-8')


def _strip_comments(text):
    return re.sub(r'/\*.*?\*/', '', text, flags=re.S)


def _strip_js_comments(text):
    """Drop JSX `{/* ... */}` and `// ...` comments before looking for a name.

    Without this, writing "this used to be a .window-bar" in a comment would
    read as the selector being back in use, and the deadness exemption would
    fail for a note about the past rather than for code.
    """
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    text = re.sub(r'^\s*//.*$', '', text, flags=re.M)
    return text


def app_shell_rules(css):
    """The app-shell *rules*, with the token-definition :root left out.

    The block slice starts and ends inside its banner comments, and the
    :root that defines the shared tokens is the first rule in it. That :root is
    allowed to contain literals - it is where they are defined.
    """
    start = css.index(APP_SHELL_START)
    end = css.index(APP_SHELL_END, start)
    body = _strip_comments(css[start:end])
    out = {}
    for selector, block in re.findall(r'([^{}]+)\{([^{}]*)\}', body):
        selector = re.sub(r'\s+', ' ', selector).strip()
        if ':root' in selector:
            continue
        props = {}
        for decl in block.split(';'):
            if ':' in decl:
                name, value = decl.split(':', 1)
                props[name.strip().lower()] = value.strip()
        if props:
            out.setdefault(selector, {}).update(props)
    return out


def defined_properties(text):
    """Every custom property given a value, comments excluded."""
    return set(re.findall(r'(--[A-Za-z0-9_-]+)\s*:', _strip_comments(text)))


def used_properties(text):
    """Every custom property read via var(), comments excluded."""
    return set(re.findall(r'var\(\s*(--[A-Za-z0-9_-]+)', _strip_comments(text)))


def all_rules(css):
    return re.findall(r'([^{}]+)\{([^{}]*)\}', _strip_comments(css))


def token_block(css, selector_pattern):
    """Merge the declarations of every block whose selector matches."""
    merged = {}
    for selector, body in all_rules(css):
        if re.search(selector_pattern, selector):
            for name, value in re.findall(
                    r'(--[A-Za-z0-9_-]+)\s*:\s*([^;]+)', body):
                merged[name] = value.strip()
    return merged


# The minifier drops the attribute-value quotes, so accept both spellings.
ROOT = r':root(?![-\w])'
DARK_THEME = r'\[data-theme=["\']?dark["\']?\]'


def marketing_dark_token_block(css):
    """The `--lg-*` overrides for the marketing pages, payslip excluded.

    `token_block` merges every `[data-theme="dark"]` block in document order,
    which is right for the app tokens - each is declared exactly once - but
    wrong for the marketing tokens. The page-level block switches the palette
    for the whole ledger page:
    ``[data-theme="dark"] .ledger-page { --lg-ink: #edf4fb; ... }`` and then,
    later in the file, the payslip - a preview of a printed document that
    deliberately stays light in both themes - re-declares the same tokens to
    their light values on its own subtree:
    ``[data-theme="dark"] .ledger-payslip, [data-theme="dark"] .ledger-payslip *``.
    A document-order merge therefore ends with the light values winning, which
    is exactly the wrong picture of what dark mode does.

    The payslip subtree is a deliberate exception, so it is excluded here and
    asserted separately by the test that owns it.
    """
    merged = {}
    for selector, body in all_rules(css):
        s = re.sub(r'\s+', ' ', selector).strip()
        if not re.search(DARK_THEME, s):
            continue
        if '.ledger-payslip' in s:
            continue
        for name, value in re.findall(
                r'(--lg-[A-Za-z0-9_-]+)\s*:\s*([^;]+)', body):
            merged[name] = value.strip()
    return merged


# --------------------------------------------------------------------------
# Colour maths - WCAG 2.x relative luminance, same formula as the audit
# --------------------------------------------------------------------------

NAMED_COLOURS = {
    'white': (255, 255, 255),
    'black': (0, 0, 0),
    'red': (255, 0, 0),
    'green': (0, 128, 0),
    'blue': (0, 0, 255),
    'gray': (128, 128, 128),
    'grey': (128, 128, 128),
    'silver': (192, 192, 192),
    'navy': (0, 0, 128),
    'teal': (0, 128, 128),
    'orange': (255, 165, 0),
    'yellow': (255, 255, 0),
    'purple': (128, 0, 128),
    'transparent': (0, 0, 0, 0.0),
}


def _channels(value):
    if isinstance(value, tuple):
        return value
    value = value.strip()
    if value.startswith('#'):
        digits = value[1:]
        if len(digits) == 3:
            digits = ''.join(c * 2 for c in digits)
        return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))
    # Keywords are spelled out because `white` is the single most common fill
    # in the stylesheet, and a sweep that cannot read it cannot see the plain
    # case. Anything not listed raises, which is the right outcome: a fill it
    # cannot resolve must not be silently counted as safe.
    if value.lower() in NAMED_COLOURS:
        return NAMED_COLOURS[value.lower()]
    match = re.match(r'rgba?\(([^)]+)\)', value)
    if match:
        parts = [p.strip() for p in re.split(r'[,\s/]+', match.group(1)) if p.strip()]
        rgb = tuple(int(round(float(p))) for p in parts[:3])
        alpha = float(parts[3]) if len(parts) > 3 else 1.0
        return rgb + (alpha,)
    raise ValueError('cannot parse colour %r' % value)


def _flatten(value, backdrop):
    """Resolve a possibly translucent colour against an opaque backdrop."""
    parsed = _channels(value)
    if len(parsed) == 4 and parsed[3] < 1:
        alpha = parsed[3]
        # The backdrop may itself be given as a colour string, so resolve it to
        # channels before using it as the thing being blended into.
        base = _channels(backdrop)
        if len(base) == 4:
            base = base[:3]
        return tuple(round(parsed[i] * alpha + base[i] * (1 - alpha))
                     for i in range(3))
    return parsed[:3]


def _luminance(rgb):
    def channel(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(foreground, background, backdrop=(255, 255, 255)):
    """WCAG contrast ratio.

    ``backdrop`` matters: a status fill is a translucent wash over whatever
    card it sits on, so it has to be resolved against that card rather than
    against white or against the text.
    """
    bg = _flatten(background, backdrop)
    fg = _flatten(foreground, bg)
    l1, l2 = _luminance(fg), _luminance(bg)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def relative_luminance(value, backdrop=(255, 255, 255)):
    return _luminance(_flatten(value, backdrop))


# --------------------------------------------------------------------------


class StylesheetPresentTests(SimpleTestCase):
    def setUp(self):
        if not CSS_PATH.exists():
            self.skipTest('no frontend source present at %s' % CSS_PATH)
        self.css = _read(CSS_PATH)


class UndefinedCustomPropertyTests(StylesheetPresentTests):
    """`var(--x)` with no definition and no fallback drops its whole declaration.

    This is what made the knowledge toolbar's filter buttons black on a dark
    page, and it does so silently - nothing errors, the property just reverts.
    Catching it structurally is the only reliable way, because "did this one
    selector look right" does not scale to a 3,000-line stylesheet.
    """

    def test_no_undefined_custom_properties_in_stylesheet(self):
        missing = used_properties(self.css) - defined_properties(self.css)
        self.assertEqual(
            missing, set(),
            'these custom properties are read with var() but never defined, so '
            'every declaration naming one is silently discarded: %s'
            % sorted(missing))

    def test_no_undefined_custom_properties_in_components(self):
        """Components may read tokens too, so their definitions count as well."""
        used, defined = set(), set()
        for path in sorted(SRC_DIR.rglob('*.jsx')) + sorted(SRC_DIR.rglob('*.js')):
            text = _read(path)
            used |= used_properties(text)
            defined |= defined_properties(text)
        missing = used - defined - defined_properties(self.css)
        self.assertEqual(
            missing, set(),
            'components read custom properties that nothing ever defines: %s'
            % sorted(missing))

    def test_variables_used_in_light_mode_are_defined_for_light_mode(self):
        """A token declared only inside the dark block is a light-mode bug.

        `test_no_undefined_custom_properties_in_stylesheet` cannot see this. It
        counts any declaration as a definition, so a property present in
        `[data-theme="dark"]` and missing from `:root` looks fine to it - even
        though in light mode the declaration reading it is discarded and the
        property silently reverts to its inherited or initial value.

        `--surface-2` was in exactly that state while the five genuinely
        undefined variables were being chased, which is how the class nearly
        went unnoticed: dark mode looked correct, because dark mode was the one
        place those variables had been defined.
        """
        light_defined = set(token_block(self.css, ROOT))
        missing = set()
        for selector, body in all_rules(self.css):
            if re.search(DARK_THEME, selector):
                continue
            missing |= used_properties(body) - light_defined
        self.assertEqual(
            missing, set(),
            'these custom properties are read by rules that apply in both themes '
            'but are not declared in any :root, so light mode silently discards '
            'every declaration that names one: %s' % sorted(missing))


class AppShellUsesTokensTests(StylesheetPresentTests):
    """The app shell must be themeable, which means no literal palette.

    The original defect was 120 hex literals in this block. Reintroducing even
    one puts that element outside the reach of `[data-theme="dark"]` again, and
    the symptom is not a slightly-wrong colour - it is light text on a white
    surface, at roughly 1:1.
    """

    def setUp(self):
        super().setUp()
        self.rules = app_shell_rules(self.css)

    def test_app_shell_has_rules(self):
        self.assertGreater(len(self.rules), 100)

    def test_app_shell_contains_no_colour_literals(self):
        literals = []
        for selector, props in self.rules.items():
            for prop, value in props.items():
                if prop not in ('color', 'background', 'background-color',
                                'border-color', 'border', 'border-bottom',
                                'border-top', 'border-right', 'border-left',
                                'outline-color', 'fill', 'stroke'):
                    continue
                for found in re.findall(r'#[0-9a-fA-F]{3,8}\b', value):
                    literals.append((selector, prop, found))
        self.assertEqual(
            literals, [],
            'the app shell must read its palette from custom properties so the '
            'dark theme can reach it; found literals: %s' % literals)

    def test_no_label_colour_is_a_literal_without_a_dark_counterpart(self):
        """A label colour written as a literal is unreachable from the dark theme.

        Two of them were. The app shell's own `label { color: #52615c }` and
        `.audit-filters label { color: #667085 }` were both literals, so
        `[data-theme="dark"]` had nothing to override and every form label in
        the app kept its light-mode grey on a dark surface.

        `.auth-field label { color: #324b60 }` is also a literal and is fine,
        because the auth section carries its own `[data-theme="dark"]` rule
        beside it. So the invariant is not "no literals" - it is "no literal
        without a dark counterpart", which is the actual failure condition and
        the one that keeps working as sections are added.
        """
        dark_labelled = set()
        for selector, _ in all_rules(self.css):
            if re.search(DARK_THEME, selector) and re.search(
                    r'(^|[\s,>])label(\b|\[|:)', selector):
                dark_labelled.update(re.findall(
                    r'\.([A-Za-z][\w-]*)', selector))

        checked, offenders = 0, []
        for selector, body in all_rules(self.css):
            if re.search(DARK_THEME, selector):
                continue
            if not re.search(r'(^|[\s,>])label(\b|\[|:)', selector):
                continue
            colours = [c.strip() for c in
                       re.findall(r'(?<![\w-])color:\s*([^;]+)', body)]
            if not colours:
                continue
            checked += 1
            owners = re.findall(r'\.([A-Za-z][\w-]*)', selector)
            themed = any(owner in dark_labelled for owner in owners)
            for colour in colours:
                if not colour.startswith('#') or themed:
                    continue
                offenders.append((selector.strip(), colour))
        self.assertEqual(
            offenders, [],
            'these label colours are literals and no dark rule overrides them, '
            'so they keep their light-mode value in dark mode: %s' % offenders)
        self.assertGreater(
            checked, 1,
            'expected to find several rules setting a label colour; finding one '
            'means this sweep can no longer detect a regression here')


class LightPaletteIsFaithfulTests(StylesheetPresentTests):
    """Theming must not change what light mode looks like.

    This is the assertion that was missing and the claim that was wrong. The
    first tokenisation pass merged distinct literals onto shared tokens, which
    is fine for dark mode and wrong for light: 27 declarations rendered a
    different colour, 24 of them by a visible margin. Splitting the tokens
    brought the light-mode audit back to its exact baseline of 460 failures
    with an identical set of failure signatures.

    The expected values below were read out of the pre-change stylesheet, so
    this is a record of what light mode always rendered rather than a guess.
    """

    def setUp(self):
        super().setUp()
        self.light = token_block(self.css, ROOT)

    def test_every_recorded_token_still_exists(self):
        missing = sorted(set(APP_LIGHT_PALETTE) - set(self.light))
        self.assertEqual(
            missing, [],
            'these app tokens are gone; a selector reading one is now falling '
            'back to an inherited colour: %s' % missing)

    def test_light_values_are_the_original_literals(self):
        wrong = {
            name: (self.light[name], expected)
            for name, expected in APP_LIGHT_PALETTE.items()
            if name in self.light and self.light[name].strip().lower() != expected
        }
        self.assertEqual(
            wrong, {},
            'these tokens no longer render the colour light mode always used: %s'
            % {k: 'now %s, was %s' % v for k, v in wrong.items()})

    def test_a_token_stands_for_exactly_one_literal(self):
        """The defect this file exists to prevent, stated as an invariant.

        A token that two rules read with two different original colours can
        only have one light value, so one of those rules is wrong. This is the
        check that would have caught the merge before it shipped rather than
        after.
        """
        rules = app_shell_rules(self.css)
        one_value = {name: expected for name, expected in APP_LIGHT_PALETTE.items()}
        offenders = []
        for selector, props in rules.items():
            for prop, value in props.items():
                for name in used_properties(value):
                    if name in one_value:
                        continue
                    # A token outside the recorded palette: it must be one of the
                    # five that were previously undefined, or a shared token.
                    if name.startswith('--app-'):
                        offenders.append((selector, prop, name))
        self.assertEqual(
            offenders, [],
            'these rules read an --app-* token that is not in the recorded '
            'palette, so its light value is unverified: %s' % offenders)

    def test_shared_tokens_were_not_redefined_for_light(self):
        """`--ink`, `--line`, `--surface`, `--muted` are shared with marketing.

        They already had their own dark blocks. Adding another light value in
        the app token block would leak one section's palette into another.
        """
        light = self.light
        for name, expected in (('--ink', '#12221e'), ('--line', '#e6ece9'),
                               ('--surface', '#fff'), ('--muted', '#70807b')):
            with self.subTest(token=name):
                self.assertEqual(
                    light.get(name, '').strip().lower(), expected,
                    '%s is shared with the marketing/ledger stylesheets and must '
                    'keep its original light value' % name)


class AppTokensAreFullyThemedTests(StylesheetPresentTests):
    """Every `--app-*` token needs a value in *both* themes.

    A token defined only for light is not a partial theme, it is the original
    bug wearing a token's name: the element keeps its light value and the dark
    page is wrong exactly where it was before.
    """

    def setUp(self):
        super().setUp()
        self.light = token_block(self.css, ROOT)
        self.dark = token_block(self.css, DARK_THEME)

    def test_every_app_token_has_a_dark_value(self):
        missing = sorted(
            name for name in self.light
            if name.startswith('--app-') and name not in self.dark)
        self.assertEqual(
            missing, [],
            'these --app-* tokens have no dark value, so they keep their light '
            'colour in dark mode: %s' % missing)

    def test_dark_values_actually_differ_from_light(self):
        """A dark value identical to the light one is a token that does nothing.

        The exceptions are the upgrade card's three tokens, and they are the
        exception by design rather than by omission: that card is dark in both
        themes, so its surface moves and its text deliberately does not. They
        are asserted separately below so that "unchanged on purpose" cannot
        quietly become "unchanged by accident".
        """
        unchanged_by_design = {'--app-on-dark', '--app-upgrade-ink',
                               '--app-upgrade-muted'}
        same = sorted(
            name for name in APP_LIGHT_PALETTE
            if name not in unchanged_by_design
            and name in self.dark
            and self.dark[name].strip().lower()
            == self.light.get(name, '').strip().lower())
        self.assertEqual(
            same, [],
            'these tokens have the same value in both themes, so dark mode is '
            'unchanged for whatever uses them: %s' % same)

    def test_the_upgrade_card_stays_dark_in_both_themes(self):
        """The card that keeps its dark surface in light mode.

        Its background does move with the theme (#102d26 -> #14312b, a slight
        lift so it separates from the page), but the two text colours are
        deliberately fixed, because the surface is dark either way and moving
        them would be a change with nothing to compensate for it.
        """
        for name in ('--app-upgrade-ink', '--app-upgrade-muted'):
            with self.subTest(token=name):
                self.assertEqual(
                    self.dark[name].strip().lower(),
                    self.light[name].strip().lower(),
                    'the upgrade card is dark in both themes, so its text %s '
                    'must not change with the theme' % name)
        self.assertNotEqual(
            self.dark['--app-upgrade-bg'].strip().lower(),
            self.light['--app-upgrade-bg'].strip().lower(),
            'the upgrade card background should still lift slightly in dark '
            'mode so it separates from the page behind it')

    def test_app_surface_is_dark_not_white(self):
        """`--surface` was `#fff`, so drawers and modal cards stayed white."""
        self.assertLess(
            relative_luminance(self.dark['--app-surface']), 0.05,
            '--app-surface is %s in dark mode; white on a dark page is the '
            'failure this file exists to prevent' % self.dark['--app-surface'])

    def test_previously_undefined_variables_are_now_defined(self):
        for name in PREVIOUSLY_UNDEFINED:
            with self.subTest(token=name):
                self.assertIn(name, self.light, '%s still has no definition' % name)
                self.assertIn(name, self.dark, '%s has no dark-mode value' % name)


class LightSurfaceHasDarkCounterpartTests(StylesheetPresentTests):
    """The sweep that found the unthemed badges, kept as a standing check.

    A sweep rather than a fixed list, so a card added in a light colour without
    a dark counterpart is caught without anyone having to remember. Sections
    with their own dark palette are excluded by prefix.
    """

    # A fill is classified as light by its luminance, not by membership in a
    # list of pale hex values. The list version of this check enumerated 18
    # colours and was blind to 38 others, among them `#e0f2fe` on
    # `.notice-level.info` - so a regression test built on it could have been
    # sabotaged past without noticing. A threshold covers every fill in the
    # file, including ones written after this was written.
    #
    # 0.75 is the point above which a fill reads as a light-theme surface: at
    # that point light-mode text on it would clear 4.5:1 and a dark page's text
    # would not. Every fill below the threshold is either a dark colour used
    # deliberately, or one already reachable only through a themed token.
    LIGHT_FILL_LUMINANCE = 0.75

    FILL = re.compile(
        r'(?:^|[;{\s])(?:background|background-color)\s*:\s*'
        r'(#[0-9a-fA-F]{3,8}|[a-zA-Z]+)\s*(?=[;!]|\Z)')

    # `background: none` and `transparent` both mean "no fill of my own" - the
    # card behind shows through, and that card is already themed. `transparent`
    # in particular resolves to white here and would be reported as the
    # lightest surface in the file while actually being the absence of one.
    NOT_A_FILL = frozenset(('none', 'transparent', 'inherit', 'initial',
                            'unset', 'revert'))

    def _compounds(self, selector, strip_dark_prefix=False):
        """Split a selector into its individual compound selectors.

        Compared as whole compounds rather than as a bag of class names. An
        earlier version collected every `.class` in the selector and asked
        whether *any* of them appeared in a dark rule, which meant deleting the
        `[data-theme="dark"] .notice-level.info` rule entirely was invisible:
        `.notice-level` was still there courtesy of the .danger, .success and
        .warning variants, so the sweep reported the family as covered while
        one level was rendering light-on-light. Removing a single variant is
        the most likely way this check is ever needed, so it is the one case it
        must not miss.
        """
        if strip_dark_prefix:
            selector = re.sub(r'\[data-theme=["\']?dark["\']?\]', ' ', selector)
        return [self._normalise(part) for part in selector.split(',')
                if self._normalise(part)]

    @staticmethod
    def _normalise(compound):
        """Spacing-insensitive form, so `.a > .b` and `.a>.b` compare equal.

        They are the same selector but not the same string, and a mismatch here
        would be reported as a missing dark rule that does exist.
        """
        compound = re.sub(r'\s*([>+~])\s*', r'\1', compound)
        return re.sub(r'\s+', ' ', compound).strip()

    @staticmethod
    def _base(compound):
        """The element a compound selects, with simple pseudo-classes stripped.

        `.ai-widget-draft-review button:last-child` and
        `.ai-widget-draft-review button` select the same element, so a dark
        rule written for the second one does theme the first. Comparing the
        compounds as text would call that an unpaired light fill, which is a
        false report - and a false report is how a real one gets ignored.

        A pseudo-*function* such as `:not(.x)` is left alone: stripping it
        would widen the base selector and make this check accept matches it
        should reject, which is the dangerous direction to be wrong in.
        """
        if re.search(r':[\w-]+\(', compound):
            return compound
        return re.sub(r':(?!:)[\w-]+', ' ', compound).strip()

    @staticmethod
    def _specificity(compound):
        """(ids, classes-and-attributes, types) - the cascade's own ordering.

        Element names are counted on a copy with classes, ids, attributes and
        pseudo-classes removed first. Counting them in place was the first
        version's bug: it read the `ai` in `.ai-widget-draft-review` as an
        element name, so a rule with one class and one element scored the same
        as a rule with two classes, and every specificity comparison in this
        file silently came out wrong.
        """
        ids = len(re.findall(r'(?<![\w-])#[\w-]+', compound))
        classes = (len(re.findall(r'\[[^\]]*\]', compound))
                   + len(re.findall(r'\.[\w-]+', compound))
                   + len(re.findall(r':(?!:)[\w-]+', compound)))
        stripped = re.sub(r'\[[^\]]*\]', ' ', compound)
        stripped = re.sub(r'(?<![\w-])#[\w-]+', ' ', stripped)
        stripped = re.sub(r'\.[\w-]+', ' ', stripped)
        stripped = re.sub(r':(?!:)[\w-]+', ' ', stripped)
        types = len(re.findall(r'(?<![\w-])[a-zA-Z][\w-]*', stripped))
        return (ids, classes, types)

    def _dark_covers(self, light_compound, dark_fills):
        """Does any dark rule set a background on the element `light_compound` hits?

        Three ways that can be true, and all three are checked because a
        partial version of this produced both a false report and a missed one:

        * the same compound - `[data-theme="dark"] .notice-level.info`;
        * the same element reached through an ancestor -
          `[data-theme="dark"] .marketing .window-bar` themes `.window-bar`,
          so a dark compound that *ends with* the light one counts;
        * the same element written with fewer pseudo-classes, at equal or
          greater specificity, in a later block - every dark block in this
          stylesheet is written after the light rule it overrides, so a tie
          goes to the dark rule.

        `dark_fills` holds `(stripped compound, specificity)` pairs. The
        specificity is deliberately computed on the *unstripped* compound: the
        `[data-theme="dark"]` attribute is a class-level selector, so dropping
        it before the comparison understated every dark rule in the file by
        one, which made `[data-theme="dark"] .ai-widget-draft-review button`
        (really 0,2,1) look weaker than `.ai-widget-draft-review
        button:last-child` (0,2,1) and reported a fill that a later dark rule
        already overrides.
        """
        want = self._base(light_compound)
        want_spec = self._specificity(light_compound)
        for dark_compound, dark_spec in dark_fills:
            if dark_compound == light_compound:
                return True
            if dark_compound.endswith(' ' + light_compound):
                return True
            if self._base(dark_compound) != want:
                continue
            if dark_spec >= want_spec:
                return True
        return False

    def test_the_sweep_recognises_what_actually_themes_an_element(self):
        """The coverage test, tested.

        `_dark_covers` is now real logic - equal compounds, ancestor scoping,
        pseudo-class stripping, and a specificity comparison that has to keep
        the `[data-theme="dark"]` attribute to be worth anything. A bug in it
        that returned True too eagerly would make the sweep report nothing
        wrong with the whole stylesheet, and nothing about a passing run would
        distinguish that from a clean one. These cases are the ones that
        actually occur in this file.

        Each `True` row is a real fill the sweep must consider themed; each
        `False` row is one it must still report, so a rule that themes
        everything is caught by the second group.
        """
        dark_fills = [
            # The attribute is kept, because its specificity is what lets this
            # beat `.ai-widget-draft-review button:last-child` on a tie. Each
            # rule also appears again stripped, which is how the caller records
            # it: the same rule has to be findable by an ancestor-scoped
            # selector as well as by the compound it actually wrote.
            ('[data-theme="dark"] .ai-widget-draft-review button', (0, 2, 1)),
            ('.ai-widget-draft-review button', (0, 2, 1)),
            ('[data-theme="dark"] .ai-widget-toolbar', (0, 2, 0)),
            ('.ai-widget-toolbar', (0, 2, 0)),
            ('[data-theme="dark"] .ai-widget-toolbar button', (0, 2, 1)),
            ('.ai-widget-toolbar button', (0, 2, 1)),
            ('.notice-level.info', (0, 2, 0)),
            # An ancestor-scoped rule, which themes a whole branch.
            ('.marketing .window-bar', (0, 2, 0)),
        ]
        themed = [
            # Pseudo-class stripped, then beaten on a specificity tie by being
            # later in the file - this is the one that used to be reported.
            '.ai-widget-draft-review button:last-child',
            '.ai-widget-draft-review button',
            '.ai-widget-toolbar',
            '.ai-widget-toolbar button',
            '.notice-level.info',
            # Found only through the ancestor rule above.
            '.window-bar',
        ]
        unthemed = [
            # No dark rule mentions these at all.
            '.window-bar-gone',
            '.notice-level.info-gone',
            # Same element, but the light rule outranks every dark rule for it,
            # so its fill really does survive into dark mode. Specificity has
            # to be enforced, not just compared, or this passes.
            '.ai-widget-toolbar button.active:hover',
        ]
        for light in themed:
            with self.subTest(light=light, expected=True):
                self.assertTrue(
                    self._dark_covers(light, dark_fills),
                    '%s is themed by a rule in this list, but the sweep would '
                    'report its light fill as unpaired' % light)
        for light in unthemed:
            with self.subTest(light=light, expected=False):
                self.assertFalse(
                    self._dark_covers(light, dark_fills),
                    '%s is NOT themed by any rule in this list, so reporting it '
                    'is the correct answer' % light)

    def test_the_sweep_actually_finds_light_fills_to_examine(self):
        """A parser that reads nothing reports nothing wrong, and looks clean.

        The light-mode audit in this project already had that bug once: a colour
        parser that returned `null` for every value produced a perfect score.
        Two counts, because they fail for different reasons:

        * `fills_seen` guards the pattern. It is 155 today, and a pattern
          narrowed to a single hex drops it to 1 - which is the blind spot the
          hand-written list of 18 hexes had all along, hiding 38 fills.
        * `light_found` guards the threshold. It is 123 today at 0.75; raising
          the threshold to 0.99 drops it to 42 while `fills_seen` stays at
          155, so a count that only looked at the pattern could not see it.
        """
        fills_seen = light_found = 0
        for selector, body in all_rules(self.css):
            if re.search(DARK_THEME, selector):
                continue
            if any(prefix in selector
                   for prefix in OWN_PALETTE_PREFIXES + DEAD_SELECTOR_PREFIXES):
                continue
            for match in self.FILL.finditer(body):
                fill = match.group(1)
                if fill.lower() in self.NOT_A_FILL:
                    continue
                fills_seen += 1
                try:
                    if relative_luminance(fill) >= self.LIGHT_FILL_LUMINANCE:
                        light_found += 1
                except ValueError:
                    pass
        self.assertGreater(
            fills_seen, 120,
            'the sweep found only %d background literals in scope. A fill '
            'pattern that has stopped matching is indistinguishable from a '
            'stylesheet with no problems' % fills_seen)
        self.assertGreater(
            light_found, 90,
            'only %d of the %d fills in scope are classified as light. The '
            'threshold is %.2f, which today finds 123; raising it to 0.99 '
            'finds 42 and quietly stops checking most of the file'
            % (light_found, fills_seen, self.LIGHT_FILL_LUMINANCE))

    def test_no_dark_rule_sets_a_light_background(self):
        """A dark rule that fills with a light colour is a light box on a dark page.

        The sweep above only looks at rules that are *not* under
        `[data-theme="dark"]`, because it is asking "does this light fill get
        overridden". That leaves the mirror-image bug unexamined: a dark rule
        that itself sets a pale background. It is the same failure - and the
        AI draft-studio toolbar had exactly it, at
        `[data-theme="dark"] .ai-widget-toolbar button { background: #fff }`
        carrying `#edf4fb` text at a measured 1.11:1.

        This check needs no cascade reasoning at all: under
        `[data-theme="dark"]`, a background light enough to be a light-theme
        surface is simply wrong.
        """
        offenders = []
        for selector, body in all_rules(self.css):
            if not re.search(DARK_THEME, selector):
                continue
            for match in self.FILL.finditer(body):
                fill = match.group(1)
                if fill.lower() in self.NOT_A_FILL:
                    continue
                try:
                    if relative_luminance(fill) < self.LIGHT_FILL_LUMINANCE:
                        continue
                except ValueError:
                    offenders.append((selector.strip(), fill, 'unreadable'))
                    continue
                offenders.append((selector.strip(), fill,
                                  'relative luminance %.3f'
                                  % relative_luminance(fill)))
        self.assertEqual(
            offenders, [],
            'these [data-theme="dark"] rules set a background light enough to '
            'read as a light-theme surface, which on a dark page is the '
            'failure this file exists to prevent: %s'
            % sorted(set(offenders)))

    def test_dead_selector_exclusions_are_still_dead(self):
        """The one condition under which the sweep may ignore a light fill.

        `DEAD_SELECTOR_PREFIXES` is a promise that nothing renders those
        selectors, which is the only reason they are allowed to keep a light
        fill in dark mode. This checks the promise, so reviving one of them
        turns into a failure telling you to theme it rather than into a silent
        hole in the dark theme.
        """
        sources = (sorted(SRC_DIR.rglob('*.jsx')) + sorted(SRC_DIR.rglob('*.js')))
        self.assertTrue(sources, 'no component sources found under %s' % SRC_DIR)
        blob = '\n'.join(_strip_js_comments(_read(path)) for path in sources)
        revived = [prefix for prefix in DEAD_SELECTOR_PREFIXES if prefix in blob]
        self.assertEqual(
            revived, [],
            'these selectors are now referenced by a component, so they render '
            'and need a [data-theme="dark"] rule like any other light fill. '
            'Remove them from DEAD_SELECTOR_PREFIXES and theme them: %s'
            % revived)

    def test_light_fills_outside_self_themed_sections_have_a_dark_rule(self):
        # Only dark rules that actually set a fill can theme anything. A dark
        # rule that sets `color` alone - as `[data-theme="dark"]
        # .ai-widget-toolbar button` originally did - leaves the background
        # exactly as light as it was, which is the failure this file exists for.
        dark_fills = []
        for selector, body in all_rules(self.css):
            if not re.search(DARK_THEME, selector):
                continue
            if not re.search(r'(?:^|[;{\s])background(?:-color)?\s*:', body):
                continue
            for compound in self._compounds(selector):
                specificity = self._specificity(compound)
                dark_fills.append((compound, specificity))
                # The same rule again with the attribute removed, because a
                # dark rule scoped through an ancestor - `[data-theme="dark"]
                # .marketing .window-bar` - themes a whole branch, and the
                # suffix test has to be able to see that. Same specificity:
                # dropping the attribute here is a presentation change to the
                # selector text, not a change to what the rule outranks.
                dark_fills.append((
                    self._normalise(re.sub(DARK_THEME, ' ', compound)),
                    specificity))

        unpaired, unresolvable = [], []
        for selector, body in all_rules(self.css):
            if re.search(DARK_THEME, selector):
                continue
            if any(prefix in selector
                   for prefix in OWN_PALETTE_PREFIXES + DEAD_SELECTOR_PREFIXES):
                continue
            for match in self.FILL.finditer(body):
                fill = match.group(1)
                if fill.lower() in self.NOT_A_FILL:
                    continue
                try:
                    if relative_luminance(fill) < self.LIGHT_FILL_LUMINANCE:
                        continue
                except ValueError:
                    # An unparseable fill is not evidence of anything either
                    # way, so it is reported separately rather than treated as
                    # light - but it is still surfaced, because a colour this
                    # check cannot read is a colour this check cannot vouch for.
                    unresolvable.append((selector.strip(), fill))
                    continue
                for compound in sorted(self._compounds(selector)):
                    if not self._dark_covers(compound, dark_fills):
                        unpaired.append((selector.strip(), compound, fill))
        self.assertEqual(
            unresolvable, [],
            'these fills are not colours the contrast helpers can read, so the '
            'light-surface sweep cannot judge them: %s' % sorted(set(unresolvable)))
        self.assertEqual(
            unpaired, [],
            'these selectors keep a light fill (relative luminance >= %.2f) in '
            'dark mode. Add a [data-theme="dark"] rule for them, or add the '
            'section to OWN_PALETTE_PREFIXES if it themes itself: %s'
            % (self.LIGHT_FILL_LUMINANCE, sorted(set(unpaired))))


class DarkContrastTests(StylesheetPresentTests):
    """Lock in the measured ratios so a later tweak cannot quietly undo them.

    Each pair below was a real failure at 1.03:1 - 3.47:1 before the fix. They
    are asserted as numbers rather than as "looks dark enough" because that is
    the only form of the check that actually fails when a colour is wrong.
    """

    def setUp(self):
        super().setUp()
        self.light = token_block(self.css, ROOT)
        self.dark = token_block(self.css, DARK_THEME)

    def test_body_text_clears_aa_on_the_dark_card(self):
        for token in ('--app-heading', '--app-ink', '--app-ink-soft', '--app-muted'):
            with self.subTest(token=token):
                self.assertGreaterEqual(
                    contrast(self.dark[token], self.dark['--app-surface']), 4.5,
                    '%s is below 4.5:1 on --app-surface in dark mode' % token)

    def test_body_text_clears_aa_on_the_dark_page(self):
        page = self.dark.get('--bg', '#0b1220')
        for token in ('--app-heading', '--app-ink', '--app-ink-soft', '--app-muted'):
            with self.subTest(token=token):
                self.assertGreaterEqual(
                    contrast(self.dark[token], page), 4.5,
                    '%s is below 4.5:1 on the page background in dark mode' % token)

    def test_accent_text_clears_aa_in_both_themes(self):
        """`--primary` inverts from deep green to bright teal, so text on it must too.

        White is correct in light (5.00:1 on #087f5b) and unreadable in dark
        (1.86:1 on #2dd4bf). That is why `--app-on-accent` exists as its own
        token instead of a hardcoded white.
        """
        for theme, tokens in (('light', self.light), ('dark', self.dark)):
            with self.subTest(theme=theme):
                self.assertGreaterEqual(
                    contrast(tokens['--app-on-accent'], tokens['--primary']), 4.5,
                    'text on --primary is below 4.5:1 in %s mode' % theme)

    def test_text_on_the_upgrade_card_clears_aa_in_both_themes(self):
        """The opposite case: a surface that stays dark, so its text stays light."""
        for theme, tokens in (('light', self.light), ('dark', self.dark)):
            for text in ('--app-on-dark', '--app-upgrade-ink', '--app-upgrade-muted'):
                with self.subTest(theme=theme, token=text):
                    self.assertGreaterEqual(
                        contrast(tokens[text], tokens['--app-upgrade-bg']), 4.5,
                        'upgrade card text %s is below 4.5:1 in %s mode' % (text, theme))

    def test_tinted_status_fills_clear_aa_against_the_card_they_sit_on(self):
        """A wash is translucent, so the ratio depends on what is underneath.

        Resolving the alpha against white instead of against the card is how
        these end up looking fine in a spreadsheet and unreadable on screen.
        """
        card = self.dark['--app-surface']
        for fill, text in (
            ('--app-primary-tint', '--primary'),
            ('--app-primary-soft', '--primary'),
            ('--app-primary-pale', '--primary'),
            ('--app-danger-bg', '--app-danger-text'),
            ('--app-warn-bg', '--app-warn-text'),
        ):
            with self.subTest(fill=fill):
                self.assertGreaterEqual(
                    contrast(self.dark[text], self.dark[fill], backdrop=card), 4.5,
                    '%s on %s is below 4.5:1 over --app-surface in dark mode'
                    % (text, fill))

    def test_ledger_eyebrow_is_corrected_without_breaking_the_payslip(self):
        """`--lg-verdant` may only go dark where the payslip does not read it.

        - the page-level block may switch it to #5eead4: the ledger sections
          that actually go dark need it, and the plain eyebrow on the ledger's
          own #0b1220 surface measured 3.01:1,
        - the payslip subtree must re-declare the light values so its verdant
          accents stay light-on-light in both themes (it is a preview of a
          printed document, not UI),
        - and no other dark block may declare the token at all - a dark
          declaration anywhere else is either a light value leaking in or an
          override the payslip was not reset for.

        If the override ever moves somewhere the payslip inherits without a
        reset beneath it, this fails - which is the exact failure `--lg-verdant`
        is capable of, and the one this test exists to prevent.
        """
        page = marketing_dark_token_block(self.css)
        self.assertEqual(
            page.get('--lg-verdant'), '#5eead4',
            'the page-level dark block no longer overrides --lg-verdant; the '
            'ledger sections that go dark are back to 3.01:1')
        resets = []
        for selector, body in all_rules(self.css):
            s = re.sub(r'\s+', ' ', selector).strip()
            if re.search(DARK_THEME, s) and '.ledger-payslip *' in s:
                resets.append((s, body))
        self.assertEqual(
            len(resets), 1,
            'exactly one dark rule may reset the payslip subtree to the light '
            'tokens; found %r' % [s for s, _ in resets])
        reset = {}
        for name, value in re.findall(
                r'(--lg-[A-Za-z0-9_-]+)\s*:\s*([^;]+)', resets[0][1]):
            reset[name] = value.strip()
        for token, light_value in (('--lg-verdant', '#2f6b5c'),
                                   ('--lg-ink', '#17140f'),
                                   ('--lg-ink-soft', '#4a463e')):
            self.assertEqual(
                reset.get(token), light_value,
                'the payslip reset must return %s to its light value %s'
                % (token, light_value))
        # The payslip stays legible: light verdant on its own light surfaces.
        self.assertGreaterEqual(
            contrast('#2f6b5c', '#fffdf8'), 4.5,
            'payslip verdant on the light page is not readable (was 6.11:1)')
        self.assertGreaterEqual(
            contrast('#2f6b5c', '#f3eee1'), 4.5,
            'payslip verdant on the parchment band is not readable (was '
            '5.37:1)')
        dark_selectors = ' '.join(
            selector for selector, _ in all_rules(self.css)
            if re.search(DARK_THEME, selector))
        self.assertIn(
            'ledger-eyebrow', dark_selectors,
            'the ledger section eyebrow needs its own dark rule: --lg-verdant '
            'on the ledger\'s own #0b1220 surface measures 3.01:1')


class StylesheetEncodingTests(StylesheetPresentTests):
    """A read/write through the wrong encoding is silent, and it reaches the UI.

    Rewriting this file with the platform's default encoding replaced five
    characters with U+FFFD. Four were in comments, which is untidy. The fifth
    was ``.dashboard-connection .connection-status em::before { content: '·' }``
    - a live glyph, so the connection card's status bullet rendered a black
    diamond with a question mark.
    """

    def test_no_replacement_characters(self):
        offenders = [
            (i, line.strip()[:90])
            for i, line in enumerate(self.css.splitlines(), 1)
            if '\ufffd' in line
        ]
        self.assertEqual(
            offenders, [],
            'U+FFFD means a character was destroyed by an encoding mismatch: %s'
            % offenders)

    def test_no_cp1252_mojibake(self):
        """`â€”` is an em-dash whose UTF-8 bytes were read as cp1252.

        The file already shipped with eight of these in its banner comments.
        They are harmless in a comment but fatal in a `content:` value, and
        they hide the fact that a byte-level round trip is happening at all.
        """
        mojibake = re.compile(
            '[\u00c2-\u00f4][\u20ac\u0153\u201c\u201d\u0192\u2122]')
        offenders = [
            (i, line.strip()[:90])
            for i, line in enumerate(self.css.splitlines(), 1)
            if mojibake.search(line)
        ]
        self.assertEqual(
            offenders, [],
            'these lines hold cp1252 mojibake rather than the character that '
            'was meant: %s' % offenders)

    def test_generated_glyphs_are_real_characters(self):
        """Any `content:` value that is not ASCII must be a real glyph."""
        offenders = []
        for i, line in enumerate(self.css.splitlines(), 1):
            for value in re.findall(r'content:\s*["\']([^"\']*)["\']', line):
                if any(ord(ch) > 127 for ch in value):
                    if mojibake_re.search(value) or '\ufffd' in value:
                        offenders.append((i, value))
        self.assertEqual(offenders, [], offenders)


mojibake_re = re.compile('[\u00c2-\u00f4][\u20ac\u0153\u201c\u201d\u0192\u2122]')


class BuiltBundleCarriesTheThemeTests(SimpleTestCase):
    """The build in `frontend_dist/` must contain the fixed stylesheet.

    A source fix that is never built leaves the running app exactly as broken as
    before while every source-level test passes, so the shipped artefact is
    checked too.
    """

    def setUp(self):
        if not DIST_DIR.exists():
            self.skipTest('no frontend build present; run `npm run build` in frontend/')
        sheets = sorted(DIST_DIR.glob('assets/index-*.css'))
        if not sheets:
            self.skipTest('no built stylesheet in frontend_dist/assets/')
        self.path = sheets[-1]
        self.css = _read(self.path)

    def test_only_one_built_stylesheet_is_present(self):
        """Two hashed copies means the bundle is ambiguous about which is live."""
        sheets = sorted(DIST_DIR.glob('assets/index-*.css'))
        self.assertEqual(
            len(sheets), 1,
            'frontend_dist holds %d built stylesheets (%s); the entry point '
            'names one and the other is dead weight that will be served after '
            'the next rebuild' % (len(sheets), [p.name for p in sheets]))

    def test_built_stylesheet_defines_the_app_tokens(self):
        dark = token_block(self.css, DARK_THEME)
        for token in ('--app-surface', '--app-ink-soft', '--app-on-accent'):
            self.assertIn(
                token, dark,
                'the built stylesheet %s is missing %s - the source was probably '
                'edited without running `npm run build`' % (self.path.name, token))

    def test_built_stylesheet_has_no_undefined_custom_properties(self):
        missing = used_properties(self.css) - defined_properties(self.css)
        self.assertEqual(
            missing, set(),
            'the built stylesheet reads undefined custom properties: %s'
            % sorted(missing))

    def test_built_stylesheet_has_no_replacement_characters(self):
        self.assertNotIn(
            '\ufffd', self.css,
            'the built stylesheet contains U+FFFD; the source was written '
            'through the wrong encoding')


# --------------------------------------------------------------------------
# The marketing pages (the 7 `/` routes)
#
# The marketing design was broken differently from the app shell. It was
# half-tokenised: the text inverted under `[data-theme="dark"]` while the
# surfaces stayed at their light literals, so dark mode rendered near-white
# text on pure-white cards (1.11:1 on the hero) and, in the sections that did
# go dark, #17140f text on a #0b1220 page (1.02:1). The fix is tokenisation
# rather than a second set of overrides: every surface became a `--lg-*` token
# whose *light* value is the original literal (so light mode only changes by
# identity), and the dark values live in one
# `[data-theme="dark"] .ledger-page` block.
# --------------------------------------------------------------------------

# The literals the components were authored with. `background: #ffffff` on
# `.hc-card` became `background: var(--lg-card)` with `--lg-card: #ffffff` in
# :root, so light mode renders exactly as before. Locking these values is how a
# later "fix" that moves light mode is caught.
LG_LIGHT_PALETTE = {
    '--lg-ink': '#17140f',          # text
    '--lg-ink-soft': '#4a463e',     # secondary text
    '--lg-verdant': '#2f6b5c',      # accents; light-theme only, see the payslip test
    '--lg-surface': '#fffdf8',      # page
    '--lg-parchment': '#f3eee1',    # hero artefact / net band
    '--lg-parchment-line': '#ddd2b8',
    '--lg-card': '#ffffff',
    '--lg-wash': '#f7f9f7',
    '--lg-workspace': '#f8faf9',
    '--lg-avatar': '#dcece7',
    '--lg-chip-gold': '#f1e2bd',
    '--lg-chip-ai': '#e9f3ef',
    '--lg-chat-user': '#eef2f5',
    '--lg-chat-bot': '#edf6f3',
    '--lg-pillar-top': '#edf5f2',
    '--lg-doc-line': '#e8ecea',
    '--lg-doc-highlight': '#eef7f4',
    '--lg-status-pill': '#dff7e9',
    '--lg-proof-card': '#fbfcfb',
    '--lg-hairline': '#e1e7e4',
    '--lg-hairline-doc': '#dce3df',
    '--lg-hairline-hl': '#d9e9e3',
}

# The measured dark values the same 22 tokens take under
# `[data-theme="dark"]`, one palette per value so a drifted colour fails by
# name. `--lg-gold-dark` is deliberately not here: it is hardcoded by the app
# shell's dark block (#fbbf24) for the upgrade card, and the marketing pages
# read it for their gold eyebrow accents in both themes.
LG_DARK_PALETTE = {
    '--lg-ink': '#edf4fb',
    '--lg-ink-soft': '#bdc8d8',
    '--lg-verdant': '#5eead4',
    '--lg-surface': '#0f1a2b',
    '--lg-parchment': '#18243c',
    '--lg-parchment-line': '#2b3b52',
    '--lg-card': '#16202f',
    '--lg-wash': '#101a2b',
    '--lg-workspace': '#16202f',
    '--lg-avatar': '#1d3a44',
    '--lg-chip-gold': '#403c33',
    '--lg-chip-ai': '#1f4241',
    '--lg-chat-user': '#1d2a3d',
    '--lg-chat-bot': '#16202f',
    '--lg-pillar-top': '#1f4241',
    '--lg-doc-line': '#253349',
    '--lg-doc-highlight': '#1c2a3d',
    '--lg-status-pill': '#1f4241',
    '--lg-proof-card': '#16202f',
    '--lg-hairline': '#2b3b52',
    '--lg-hairline-doc': '#2b3b52',
    '--lg-hairline-hl': '#2b3b52',
}

# Brand colours that are the brand *in both themes* and so must never gain a
# marketing dark value: the gold CTA bands, the navy buttons and the navy
# headings all sit on these in dark mode exactly as they do in light.
LG_BRAND_TOKENS = ('--lg-gold', '--lg-gold-soft', '--lg-indigo',
                   '--lg-indigo-deep', '--lg-white')


class MarketingDarkThemeTests(StylesheetPresentTests):
    """Regression tests for the marketing-page dark theme.

    The audit measured 118 dark-mode pairs below AA across the 7 marketing
    routes; after the tokenisation there were 0. These tests lock the *shape*
    of the fix so it cannot quietly come apart:

    * the light values are still the literals the components were authored
      with (light mode unchanged, by identity),
    * the dark values are exactly the measured palette, into which no brand
      token may drift,
    * the dark inks clear AA on their own dark surfaces (locked as ratios),
    * the round-2 work is structural: tokenised surfaces instead of override
      stacks, and the gold CTA bands stay gold with dark ink in dark mode,
    * the three both-theme base fixes are present,
    * the generated blocks are still there (a deleted block is the fastest
      way for the whole fix to silently vanish).
    """

    def setUp(self):
        super().setUp()
        self.light = token_block(self.css, ROOT)
        self.dark = marketing_dark_token_block(self.css)

    @staticmethod
    def _props(body):
        props = {}
        for decl in body.split(';'):
            if ':' in decl:
                name, value = decl.split(':', 1)
                props[name.strip().lower()] = value.strip()
        return props

    def _first(self, selector):
        """Props of the first non-dark rule whose selector matches exactly."""
        for sel, body in all_rules(self.css):
            if re.search(DARK_THEME, sel):
                continue
            if ' '.join(sel.split()) == selector:
                return self._props(body)
        return {}

    def test_the_light_values_are_the_literals_the_components_used(self):
        """Light mode is unchanged because the tokens ARE the old literals.

        If a later edit brightens `--lg-card` because dark mode "felt wrong",
        every marketing card brightens in light too - this is the check that
        names it.
        """
        changed = []
        for name, expected in LG_LIGHT_PALETTE.items():
            actual = self.light.get(name)
            if actual is None or actual.strip().lower() != expected:
                changed.append((name, actual))
        self.assertEqual(
            changed, [],
            'these marketing tokens no longer carry the literals the '
            'components were authored with, so light mode has moved: %s'
            % changed)

    def test_the_dark_values_are_exactly_the_measured_palette(self):
        """The marketing dark palette, minus the app shell's one hardcoded token.

        `--lg-gold-dark` is declared by the app-shell dark block (not the
        marketing block), so it is popped and pinned to its own value before
        the 22 measured tokens are compared one for one.
        """
        page = dict(self.dark)
        gold_dark = page.pop('--lg-gold-dark', None)
        self.assertEqual(
            gold_dark, '#fbbf24',
            'the app shell hardcodes --lg-gold-dark in its own dark block '
            '(the marketing pages read it for gold eyebrows); that value is '
            'outside the marketing palette and must stay untouched')
        self.assertEqual(
            page, LG_DARK_PALETTE,
            'dark mode must override the marketing tokens with exactly the '
            'measured palette: %s' % sorted(set(LG_DARK_PALETTE) ^ set(page)))

    def test_every_light_marketing_token_has_a_dark_value(self):
        missing = sorted(set(LG_LIGHT_PALETTE) - set(self.dark))
        self.assertEqual(
            missing, [],
            'these marketing tokens have no dark override, so they keep their '
            'light colour in dark mode: %s' % missing)

    def test_the_brand_tokens_are_not_overridden_in_dark(self):
        for name in LG_BRAND_TOKENS:
            with self.subTest(token=name):
                self.assertNotIn(
                    name, self.dark,
                    '%s is a brand colour in both themes; a dark value for it '
                    'would move the gold CTAs or the navy buttons/headings'
                    % name)

    def test_only_the_page_block_and_the_payslip_reset_declare_marketing_tokens(self):
        """No third dark block may declare a `--lg-*` token.

        Everything dark must be either the page-level override, the payslip
        reset, or the app shell's `--lg-gold-dark`. A declaration anywhere
        else is a light value leaking into dark mode or an override the
        payslip has not been reset for.
        """
        offenders = []
        for selector, body in all_rules(self.css):
            if not re.search(DARK_THEME, selector):
                continue
            s = re.sub(r'\s+', ' ', selector).strip()
            for name in re.findall(r'(--lg-[A-Za-z0-9_-]+)\s*:', body):
                allowed = (
                    '.ledger-payslip' in s
                    or s == '[data-theme="dark"] .ledger-page'
                    or (name == '--lg-gold-dark' and s == '[data-theme="dark"]'))
                if not allowed:
                    offenders.append((s, name))
        self.assertEqual(
            offenders, [],
            'dark blocks declaring --lg-* tokens outside the page block, the '
            'payslip reset and the app shell\'s --lg-gold-dark: %s'
            % sorted(set(offenders)))

    def test_the_dark_ink_tokens_clear_aa_on_their_own_dark_surfaces(self):
        """The token pairs that were the invisible text, locked as ratios."""
        pairs = (
            ('--lg-ink', '--lg-surface', 15.74),
            ('--lg-ink-soft', '--lg-card', 9.69),
            ('--lg-ink-soft', '--lg-parchment', 9.15),
            ('--lg-verdant', '--lg-card', 11.08),
            ('--lg-verdant', '--lg-doc-highlight', 9.80),
            ('--lg-ink', '--lg-doc-highlight', 13.08),
        )
        for text, fill, measured in pairs:
            with self.subTest(text=text, fill=fill):
                self.assertGreaterEqual(
                    contrast(self.dark[text], self.dark[fill]), 4.5,
                    '%s on %s fell below 4.5:1 (was %.2f:1)'
                    % (text, fill, measured))

    def test_dark_ink_on_the_brand_surfaces_clears_aa(self):
        """Navy headings/buttons and the gold bands, both measured pairs."""
        self.assertGreaterEqual(
            contrast(self.light['--lg-white'], self.light['--lg-indigo']), 4.5,
            '--lg-white on --lg-indigo is below 4.5:1 (was 15.34:1)')
        self.assertGreaterEqual(
            contrast(self.light['--lg-indigo-deep'], self.light['--lg-gold']),
            4.5,
            '--lg-indigo-deep on --lg-gold is below 4.5:1 (was 6.44:1)')

    def test_the_gold_cta_bands_stay_gold_in_dark(self):
        """The two CTA bands keep their gold fill and take dark ink in dark mode.

        The old `[data-theme="dark"] .ledger-cta` flattening rule painted them
        the page navy, so the now-dark text sat on navy at ~3:1 - and the
        gradients they sat on in light mode are exactly the kind of thing dark
        mode cannot reproduce. The fix keeps the band gold and inks it with
        --lg-indigo-deep.
        """
        dark_gold, fills = [], []
        for selector, body in all_rules(self.css):
            if not re.search(DARK_THEME, selector):
                continue
            s = re.sub(r'\s+', ' ', selector)
            if 'ledger-cta-upgraded' in s or 'ledger-security-cta' in s:
                props = self._props(body)
                if props.get('background') == 'var(--lg-gold)':
                    dark_gold.append(s.strip())
                if 'color' in props:
                    fills.append((s.strip(), props['color']))
        self.assertTrue(
            dark_gold,
            'no dark rule keeps a gold CTA band on var(--lg-gold); the bands '
            'fall back to the navy page fill')
        for s, colour in fills:
            with self.subTest(selector=s):
                self.assertEqual(
                    colour, 'var(--lg-indigo-deep)',
                    '%s must ink the gold band with --lg-indigo-deep so the '
                    'text stays dark-on-gold, not %s' % (s, colour))

    def test_the_gold_button_text_is_white_in_both_themes(self):
        """The navy-on-gold CTA buttons carry white text, measured at 15.60:1.

        Before the fix `.ledger-page a.ledger-btn-gold` (0,2,1) overrode the
        button's own `color: #fff` with the gold-adjacent ink, putting gold
        text on the navy button fill at 1.13:1 in *both* themes - a light-mode
        bug too.
        """
        selector = ('.ledger-page .ledger-cta-upgraded a.ledger-btn-gold, '
                    '.ledger-page .ledger-security-cta a.ledger-btn-gold')
        self.assertEqual(
            self._first(selector).get('color'), '#fff',
            'the gold-band CTA buttons must carry color:#fff in both themes')

    def test_the_round2_surfaces_were_tokenised_not_overridden(self):
        """The round-2 fix switched literal fills for tokens in the base rules.

        An override-only fix would leave the base rule on #ffffff and paint a
        dark rule over it - workable, but two sources of truth and a light
        page that a deleted dark rule silently breaks. The actual fix reads
        the token, so its light value *is* the surface.
        """
        tokenised = (
            ('.hc-trust-list > div', 'background', 'var(--lg-card)'),
            ('.hc-problem-grid article span', 'color', 'var(--lg-verdant)'),
            ('.hc-doc-highlight small', 'color', 'var(--lg-verdant)'),
            ('.hc-pillar-top em', 'color', 'var(--lg-verdant)'),
            ('.hc-doc-top b', 'color', 'var(--lg-verdant)'),
            ('.hc-doc-footer span:first-child', 'color', 'var(--lg-verdant)'),
            ('.hc-avatar', 'color', 'var(--lg-verdant)'),
            ('.hc-card-foot em', 'color', 'var(--lg-verdant)'),
            ('.hc-ai-head em', 'color', 'var(--lg-verdant)'),
        )
        for selector, prop, expected in tokenised:
            with self.subTest(selector=selector, prop=prop):
                self.assertEqual(
                    self._first(selector).get(prop), expected,
                    '%s should read %s, not a literal, so dark mode can reach '
                    'it through the token' % (selector, expected))
        for selector in ('.hc-positioning-strip', '.hc-problem-grid',
                         '.hc-trust-list'):
            with self.subTest(hairline=selector):
                body = ' '.join(self._first(selector).values())
                self.assertIn(
                    'var(--lg-parchment-line)', body,
                    '%s must use --lg-parchment-line for its grid hairlines so '
                    'dark mode can reach them' % selector)

    def test_no_light_marketing_literal_sneaks_back_into_hc_base_rules(self):
        """A `#2f6b5c` literal back in an `.hc-*` base rule is dark-mode-proof.

        The token keeps its light value; a pasted literal does not move with
        the theme, so it puts the light-only green back into dark mode where
        the audit measured 3.01:1.
        """
        offenders = []
        for selector, body in all_rules(self.css):
            if re.search(DARK_THEME, selector):
                continue
            s = ' '.join(selector.split())
            if '.hc-' not in s:
                continue
            for name, value in self._props(body).items():
                for found in re.findall(r'#([0-9a-fA-F]{3,8})\b', value):
                    if found.lower() == '2f6b5c':
                        offenders.append((s, name, value))
        self.assertEqual(
            offenders, [],
            'a #2f6b5c literal is back in an .hc-* base rule, outside the '
            'theme\'s reach: %s' % offenders)

    def test_the_round2_dark_component_inks_are_in_place(self):
        """The component inks round 2 had to add, collected last-wins.

        Two rounds both wrote `.hc-doc-highlight span`; the later rule wins
        (that is the cascade), so colours are collected with last-wins to
        match what the browser actually renders.
        """
        colours = {}
        for selector, body in all_rules(self.css):
            if not re.search(DARK_THEME, selector):
                continue
            s = re.sub(r'\s+', ' ', selector).strip()
            colour = self._props(body).get('color')
            if colour:
                colours[s] = colour
        expected = {
            '[data-theme="dark"] .ledger-page .hc-doc-highlight strong':
                '#edf4fb',
            '[data-theme="dark"] .ledger-page .hc-doc-highlight span':
                '#9aa8bd',
            '[data-theme="dark"] .ledger-page .hc-positioning-strip b':
                '#edf4fb',
            '[data-theme="dark"] .ledger-page .hc-trust-list span':
                '#bdc8d8',
            '[data-theme="dark"] .ledger-page .hc-card-foot span':
                '#9aa8bd',
            '[data-theme="dark"] .ledger-page .hc-doc-top, '
            '[data-theme="dark"] .ledger-page .hc-doc-footer':
                '#9aa8bd',
        }
        for selector, value in expected.items():
            with self.subTest(selector=selector):
                self.assertEqual(
                    colours.get(selector), value,
                    '%s must carry color:%s in dark mode' % (selector, value))

    def test_the_both_theme_base_fixes_are_in_place(self):
        """The three real light-mode AA failures, each fixed for both themes.

        They are asserted as values *and* as ratios so the lock survives a
        rename to a token.
        """
        self.assertEqual(
            self._first('.ledger-footer-bottom').get('color'), '#94a3b8',
            '.ledger-footer-bottom should read #94a3b8 (was #647092, 3.59:1)')
        self.assertGreaterEqual(contrast('#94a3b8', '#0e1830'), 4.5,
                                'footer-bottom is not legible, was 6.87:1')
        self.assertEqual(
            self._first('.ledger-cta-upgraded p').get('color'),
            'var(--lg-indigo-deep)',
            '.ledger-cta-upgraded p should ink the gold band with '
            '--lg-indigo-deep (was #5a461b, 3.30:1)')
        self.assertGreaterEqual(contrast('#0e1830', '#c6942f'), 4.5,
                                'CTA paragraph is not legible, was 6.44:1')
        self.assertEqual(
            self._first('.hc-card-foot').get('color'), '#697386',
            '.hc-card-foot should read #697386 (was #768091, 3.99:1)')
        self.assertGreaterEqual(contrast('#697386', '#ffffff'), 4.5,
                                'hc-card-foot is not legible, was 4.78:1')

    def test_the_feature_note_is_readable_in_both_themes(self):
        """.feature-note replaced a bare `.alert-error` on both gated pages.

        It used `.alert-error` (#feeaea on #dc2626 text) to say a module was
        switched off. Nothing had errored, and nothing was wrong with the
        reader's account - so the colour was wrong twice over, and the copy
        behind it claimed an administrator had disabled the module even when a
        staged rollout simply had not reached this workspace yet.

        The replacement is neutral in light mode and on-brand green when the
        reason is a rollout in progress. The numbers below are measured, not
        asserted by eye.
        """
        light_bg = APP_LIGHT_PALETTE['--app-note-bg']
        dark_bg = token_block(self.css, DARK_THEME)['--app-note-bg']
        body_light = APP_LIGHT_PALETTE['--app-ink-soft']
        body_dark = token_block(self.css, DARK_THEME)['--app-ink-soft']
        head_light = APP_LIGHT_PALETTE['--app-heading']
        head_dark = token_block(self.css, DARK_THEME)['--app-heading']
        icon_light = APP_LIGHT_PALETTE['--app-note-text']
        icon_dark = token_block(self.css, DARK_THEME)['--app-note-text']

        for label, fg, bg in (
            ('body, light', body_light, light_bg),
            ('heading, light', head_light, light_bg),
            ('icon, light', icon_light, light_bg),
            ('body, dark', body_dark, dark_bg),
            ('heading, dark', head_dark, dark_bg),
            ('icon, dark', icon_dark, dark_bg),
        ):
            with self.subTest(pair=label):
                self.assertGreaterEqual(
                    contrast(fg, bg), 4.5,
                    '.feature-note %s is under AA, was %.2f:1'
                    % (label, contrast(fg, bg)))

        # The icon is a 1.8px stroke, so it is a graphical object and needs the
        # 3:1 non-text floor, not the 4.5:1 text one. It sits on --app-surface.
        for label, fg, surface in (
            ('light', icon_light, APP_LIGHT_PALETTE['--app-surface']),
            ('dark', icon_dark, token_block(self.css, DARK_THEME)['--app-surface']),
        ):
            with self.subTest(icon=label):
                self.assertGreaterEqual(
                    contrast(fg, surface), 3.0,
                    '.feature-note__icon glyph is under the 3:1 graphical '
                    'floor, was %.2f:1' % contrast(fg, surface))

    def test_the_feature_note_is_never_painted_as_an_error(self):
        """The severity regression, pinned.

        A module being off is a state, not a failure. Painting it with the
        danger family is the specific thing this change fixed, and it is easy
        to reintroduce by reaching for `.alert-error` as the nearest existing
        style.
        """
        note_rules = [(s, b) for s, b in all_rules(self.css)
                      if '.feature-note' in s]
        self.assertTrue(note_rules, '.feature-note rules are missing entirely')
        for selector, body in note_rules:
            for name, value in re.findall(r'(color|background|background-color)'
                                          r'\s*:\s*([^;]+)', body):
                for danger in ('--app-danger', '--danger', 'feeaea', 'dc2626',
                               'b42318', 'd64545'):
                    self.assertNotIn(
                        danger, value,
                        '.feature-note sets %s to a danger colour (%s); a module '
                        'that is switched off is not an error'
                        % (name, value))

    def test_the_generated_dark_blocks_are_still_present(self):
        """A deleted generation block is the fastest way to lose the whole fix.

        Round 2's addendum once vanished *inside* a sentinel comment - the
        comment survived while the rule it introduced was inert. Each marker
        below guards a real generation.
        """
        for sentinel in ('MARKETING DARK THEME (generated)',
                         'MARKETING DARK THEME ROUND 2 (generated)',
                         'MARKETING DARK ROUND 2 ADDENDUM'):
            with self.subTest(sentinel=sentinel):
                self.assertIn(
                    sentinel, self.css,
                    'the %r banner is missing; its whole block may have been '
                    'deleted' % sentinel)
