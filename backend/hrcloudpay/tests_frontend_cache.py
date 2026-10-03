"""Regression tests for the frontend entry point's cache headers.

The bug: ``hrcloudpay.views.serve_frontend`` returned no cache headers at all -
no ``Cache-Control``, no ``ETag``, no ``Last-Modified``. A browser faced with
that falls back to *heuristic* caching and is free to reuse the stored copy of
``index.html`` on an ordinary reload without asking the server.

That file is the only thing that names the current content-hashed bundles, so a
reused copy keeps pointing at the *previous* build. The result is that every
deploy leaves users on the old app until someone hard-refreshes - and the card
on the dashboard silently keeps rendering its old wording while the server is
already serving the new one.

These tests pin both halves of the fix: the entry point must always revalidate
(and answer 304 cheaply when unchanged), and the hashed assets it points at
must be safe to cache indefinitely, which is what makes that revalidation free.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import Client, SimpleTestCase


class IndexHtmlMustRevalidateTests(SimpleTestCase):
    """The entry point can never be served from a stale copy."""

    def setUp(self):
        self.client = Client()
        self.index_path = Path(settings.BASE_DIR) / 'frontend_dist' / 'index.html'
        if not self.index_path.exists():
            self.skipTest('no frontend build present; run `npm run build` in frontend/')

    def test_index_html_is_marked_no_cache(self):
        """Without this, an ordinary reload may reuse the stored copy entirely."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Cache-Control', response)
        self.assertIn('no-cache', response['Cache-Control'])
        self.assertIn('must-revalidate', response['Cache-Control'])

    def test_index_html_advertises_an_etag(self):
        """so revalidation can be answered with a 304 instead of the whole file."""
        response = self.client.get('/')
        self.assertTrue(response.get('ETag'), 'index.html must carry an ETag')

    def test_matching_etag_returns_304_with_no_body(self):
        first = self.client.get('/')
        second = self.client.get('/', HTTP_IF_NONE_MATCH=first['ETag'])
        self.assertEqual(second.status_code, 304)
        self.assertEqual(second.content, b'')

    def test_a_stale_etag_still_returns_the_current_page(self):
        """The tag is derived from the file, so a rebuild invalidates it.

        This is the property that actually ends the bug: after `npm run build`
        writes a new index.html, the old tag no longer matches and the browser
        is given the page that references the new bundle.
        """
        stale = '"deadbeef-0"'
        response = self.client.get('/', HTTP_IF_NONE_MATCH=stale)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<div id="root">', response.content)

    def test_last_modified_is_sent(self):
        response = self.client.get('/')
        self.assertTrue(response.get('Last-Modified'))

    def test_every_spa_route_serves_the_entry_point(self):
        """React Router owns these paths, so they must revalidate identically.

        Landing straight on a deep link is how a stale copy bites hardest: the
        user is already on /payroll and a soft reload must not pin them to the
        previous build.
        """
        for path in ('/dashboard', '/employees', '/payroll', '/settings'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn('no-cache', response['Cache-Control'])


class HashedAssetsMayBeCachedForeverTests(SimpleTestCase):
    """Companion half: the assets must be safe to cache for a year.

    ``no-cache`` on the entry point would be a poor trade if every reload also
    re-downloaded ~950 kB of JavaScript. It doesn't, because Vite content-hashes
    every filename, so a URL that has been fetched once can never change meaning
    and caching it indefinitely is safe.
    """

    def test_only_content_hashed_assets_are_treated_as_immutable(self):
        """The year-long cache must be gated on a content hash being present.

        ``WHITENOISE_IMMUTABLE_FILE_TEST`` is a regex, and a looser one would pin
        unhashed files for a decade - reintroducing the stale-bundle bug in a
        worse form, since a hard refresh would no longer help either.
        """
        test = settings.WHITENOISE_IMMUTABLE_FILE_TEST
        self.assertTrue(test)
        compiled = re.compile(test)
        self.assertTrue(compiled.search('/static/assets/index-CnSaHDfT.js'))
        self.assertTrue(compiled.search('/static/assets/index-DyKjpPXq.css'))
        # A name with no hash must not match.
        self.assertFalse(compiled.search('/static/assets/index.js'))
        self.assertFalse(compiled.search('/static/assets/app.css'))
        self.assertFalse(compiled.search('/static/admin/css/base.css'))
        # Nor must a hash-looking string somewhere other than the filename.
        self.assertFalse(compiled.search('/static/assets/../../etc/passwd'))

    def test_unhashed_static_files_are_not_pinned(self):
        """max-age=0, so a replaced file is picked up on the next load."""
        self.assertEqual(settings.WHITENOISE_MAX_AGE, 0)

    def test_built_asset_filenames_actually_carry_a_content_hash(self):
        """The assumption above has to hold for this project, so assert it.

        If someone turns off hashing, the year-long cache becomes a way to ship
        a stale bundle forever - which is the bug this file is about, in a new
        disguise.
        """
        assets = Path(settings.BASE_DIR) / 'frontend_dist' / 'assets'
        if not assets.is_dir():
            self.skipTest('no frontend build present')
        hashed = re.compile(r'^index-[A-Za-z0-9_-]{8,}\.(js|css)$')
        built = [p.name for p in assets.iterdir() if p.suffix in ('.js', '.css')]
        if not built:
            self.skipTest('no built assets to check')
        unhashed = [n for n in built if not hashed.match(n)]
        self.assertEqual(unhashed, [], f'assets without a content hash: {unhashed}')


class HashedAssetServingTests(SimpleTestCase):
    def setUp(self):
        self.client = Client()
        self.assets = Path(settings.BASE_DIR) / 'frontend_dist' / 'assets'
        if not self.assets.is_dir():
            self.skipTest('no frontend build present')
        built = sorted(p.name for p in self.assets.iterdir() if p.suffix == '.js')
        if not built:
            self.skipTest('no built JS asset to request')
        self.asset_name = built[0]

    def test_a_hashed_asset_is_served(self):
        response = self.client.get(f'/static/assets/{self.asset_name}')
        self.assertEqual(response.status_code, 200)

    def test_a_hashed_asset_gets_a_long_lived_cache_header(self):
        response = self.client.get(f'/static/assets/{self.asset_name}')
        cache_control = response.get('Cache-Control', '')
        self.assertIn('immutable', cache_control,
                      f'expected an immutable cache, got {cache_control!r}')
        # WhiteNoise uses its own FOREVER (10 years) for files that match the
        # immutable test, so assert "effectively forever" rather than a number
        # this project does not control.
        years = int(re.search(r'max-age=(\d+)', cache_control).group(1)) / 31536000
        self.assertGreater(years, 1, cache_control)

    def test_javascript_is_served_with_a_javascript_content_type(self):
        """A wrong type here makes the browser refuse the module outright."""
        response = self.client.get(f'/static/assets/{self.asset_name}')
        content_type = response.get('Content-Type', '')
        self.assertTrue(
            'javascript' in content_type,
            f'expected a JavaScript content type, got {content_type!r}',
        )


class DevelopmentDoesNotCacheTests(SimpleTestCase):
    """The dev server deliberately behaves differently, and that is correct.

    WhiteNoise's ``WHITENOISE_AUTOREFRESH`` defaults to ``settings.DEBUG``, so with
    ``DEBUG=True`` it looks files up per request and attaches no long-lived cache
    header. That is what you want locally - you can rebuild and reload without a
    restart. The tests above therefore only describe production (the Django test
    runner forces ``DEBUG=False``), and this class records the split so nobody
    reads a green test as a claim about the dev server.
    """

    def test_whitenoise_autorefresh_is_left_at_its_debug_derived_default(self):
        """Pinning it would be the bug: a fixed file map 404s every new build.

        WhiteNoise in non-autorefresh mode indexes static files once at startup,
        so a `npm run build` that produces new hashed filenames would serve 404
        for the new bundle until the process was restarted. The dev loop depends
        on the default, so it is deliberately not overridden.
        """
        import whitenoise.middleware as wn_middleware
        import inspect

        source = inspect.getsource(wn_middleware.WhiteNoiseMiddleware.__init__)
        self.assertIn('settings.DEBUG', source,
                      'WhiteNoise should still derive autorefresh from DEBUG')
        self.assertFalse(hasattr(settings, 'WHITENOISE_AUTOREFRESH'),
                         'do not pin autorefresh: it would break the local build loop')

    def test_the_entry_point_is_no_cache_in_debug_too(self):
        """The fix for the stale-bundle bug must not depend on DEBUG.

        This is the one that matters: if `no-cache` were only applied in
        production, every developer would still be looking at stale builds.
        """
        from django.test import override_settings
        with override_settings(DEBUG=True):
            response = Client().get('/')
        self.assertIn('no-cache', response['Cache-Control'])
