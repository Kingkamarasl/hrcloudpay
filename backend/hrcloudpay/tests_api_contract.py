"""Regression tests for the frontend/backend API contract.

The SPA is a separate build from the API, and the only thing joining a call in
``frontend/src`` to a route in ``backend/*/urls.py`` is a hand-written string.
Nothing checks that the two agree, so a path can drift and the only symptom is a
runtime 404 on a page that looks finished in the source.

That is not hypothetical. ``pages/AuditLogs.jsx`` requested ``/audit-logs/``,
which resolves against the client's base URL to ``/api/audit-logs/``. The route
is registered at ``/api/auth/audit-logs/`` (``accounts/urls.py``, name
``company-audit-logs``). Django returned 404 for the former and 403 for the
latter, so the Audit trail page rendered nothing at all - while every test
passed, because no test covered the join.

A snapshot of the URLconf would not help either: the routes were correct and
correctly named, and the snapshot would have gone on accepting the typo. So
these tests assert the join itself. They enumerate the real resolved URLconf -
router-generated routes included, because a ``DefaultRouter`` route is a
``RegexPattern`` and reconstructing it from ``str(pattern)`` silently misses it -
and require that every API call in the frontend source reaches one.

Matching is done on resolved regexes rather than reconstructed path strings for
the same reason: Django anchors each urlconf level separately, so concatenating
the anchors produces a pattern that matches nothing and would report every
endpoint in the project as missing.
"""
import os
import re
from pathlib import Path

from django.test import SimpleTestCase
from django.urls import (
    URLPattern, URLResolver, Resolver404, get_resolver, resolve,
)
from rest_framework.routers import APIRootView

# Verbs the API client exposes. ``upload``/``downloadFile`` take the same
# ``(path, ...)`` shape as the rest.
API_CALL_RE = re.compile(
    r"""api\.(get|post|put|patch|del|delete|upload|downloadFile|stream)\("""
    r"""\s*(['"`])([^'"`]*)\2"""
)
# Template interpolation, e.g. ``/employees/employees/${id}/photo/``.
INTERP_RE = re.compile(r"\$\{[^}]*\}")
# Each urlconf level carries its own anchors; strip them before joining.
LEADING_ANCHORS_RE = re.compile(r"^\^+")
TRAILING_ANCHORS_RE = re.compile(r"(\$|\\Z)+$")
# The SPA fallback serves index.html for anything that is not /api or /admin.
# Left in the set it would answer for every unmatched path and hide every real
# gap, so it is excluded from the contract.
SPA_FALLBACK_RE = re.compile(r"\(\?!api")


def frontend_root():
    """``frontend/src`` for the checkout that contains this backend."""
    return Path(__file__).resolve().parent.parent.parent / "frontend" / "src"


def collect_router_roots(resolver, prefix=""):
    """Paths served by a DRF ``DefaultRouter``'s browsable API root.

    These are the one place in this project where a *registered* route is still
    the wrong thing to call. ``api/employees/`` resolves and returns 200 with a
    dict of child URLs, not a list of employees, so any caller expecting a list
    silently gets a dict - and the contract test above cannot flag it, because
    the path genuinely does resolve. The bug it caused is covered here instead.
    """
    out = []
    for entry in resolver.url_patterns:
        segment = LEADING_ANCHORS_RE.sub("", str(entry.pattern.regex.pattern))
        segment = TRAILING_ANCHORS_RE.sub("", segment)
        full = prefix + segment
        if isinstance(entry, URLResolver):
            out.extend(collect_router_roots(entry, full))
        elif isinstance(entry, URLPattern):
            if getattr(entry.callback, "cls", None) is APIRootView:
                # Drop the optional ``(?P<format>...)`` sibling the router adds.
                if "(?P<format>" not in full:
                    out.append(full)
    return out


def collect_api_routes(resolver, prefix=""):
    """Every leaf API route as ``(regex, name)``.

    ``str(pattern.regex.pattern)`` is used rather than ``str(pattern)`` because a
    DRF router route is a ``RoutePattern`` (a ``RegexPattern`` subclass); taking
    the string form yields the raw regex and the route then fails to match.
    """
    out = []
    for entry in resolver.url_patterns:
        segment = str(entry.pattern.regex.pattern)
        segment = LEADING_ANCHORS_RE.sub("", segment)
        segment = TRAILING_ANCHORS_RE.sub("", segment)
        full = prefix + segment
        if isinstance(entry, URLResolver):
            out.extend(collect_api_routes(entry, full))
        elif isinstance(entry, URLPattern):
            out.append((full, entry.name))
    return [
        (rx, name)
        for rx, name in out
        if not SPA_FALLBACK_RE.search(rx) and rx.lstrip("/").startswith("api/")
    ]


def _segments(path):
    """Split a URL or route regex into comparable segments.

    Route regexes are not paths - ``api/employees/^employees/$`` still carries
    the anchors and escapes Django's ``path()`` left behind - so each piece is
    stripped back to what it actually matches.

    The split has to ignore ``/`` inside a character class. DRF's default
    primary-key converter is ``[^/.]+``: a plain ``path.split('/')`` cuts that
    in half and yields a converter that no longer looks like one.
    """
    pieces, current, in_class = [], [], False
    for char in path:
        if char == "[" and not in_class:
            in_class = True
        elif char == "]" and in_class:
            in_class = False
        elif char == "/" and not in_class:
            pieces.append("".join(current))
            current = []
            continue
        current.append(char)
    pieces.append("".join(current))

    out = []
    for piece in pieces:
        piece = piece.lstrip("^").rstrip("$").replace("\\", "")
        if piece:
            out.append(piece)
    return out


# A segment with no regex metacharacter is a literal the route insists on.
# Anything with a bracket, group, or quantifier is a converter, and accepts
# whatever the caller sends.
_LITERAL_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._~-]+$")


def _matches(call_segments, route_segments):
    """Whether ``call_segments`` could land on ``route_segments``.

    A ``${...}`` on the frontend side is a wildcard, and so is a converter on
    the backend side. Two wildcards meet happily, which is what lets
    ``/leave/requests/${id}/${action}/`` match the literal route segment
    ``approve``: the test cannot know what the caller will pass, only that some
    value of it works. Every literal must be equal and the counts must match,
    so a missing or extra segment is still a failure.
    """
    if len(call_segments) != len(route_segments):
        return False
    for call, route in zip(call_segments, route_segments):
        call_is_literal = _LITERAL_SEGMENT_RE.match(call) is not None
        route_is_literal = _LITERAL_SEGMENT_RE.match(route) is not None
        if call_is_literal and route_is_literal and call != route:
            return False
    return True


def resolves_to_route(call_path, route_regex):
    """Whether a frontend call's *shape* is served by a backend route.

    Comparing shapes rather than strings is deliberate. The obvious alternative -
    substitute something for each ``${...}`` and regex-match the result - is
    wrong in both directions. Substituting a regex like ``[^/]+`` only appears
    to work because ``re.match`` stops at the ``/`` inside the probe and never
    examines the rest of it, and it cannot match a Django path converter at
    all: ``slug`` is ``[-a-zA-Z0-9_]+``, and no amount of prefix matching lets
    that consume a literal ``[^/]+``.

    That mistake produced a false failure here: ``/auth/marketing-pages/${slug}/``
    was reported as having no backend route, when
    ``resolve('/api/auth/marketing-pages/platform/')`` returns
    ``public-marketing-page`` and works. Being wrong in the other direction is
    worse - being wrong in this direction meant a call to a path that 404s was
    reported as fine, because the bare list route is a prefix of the detail one.
    """
    # The client's base URL is '/api' in a production build, so a bare
    # '/employees/' is really '/api/employees/'. A query string is not part of
    # the route.
    call = call_path.split("?")[0]
    if not call.startswith("/"):
        return False
    if not call.startswith("/api/"):
        call = "/api" + call
    return _matches(_segments(call), _segments(route_regex))


class FrontendBackendApiContractTests(SimpleTestCase):
    """Every API call the frontend can make must reach a real backend route."""

    def test_frontend_source_is_present(self):
        """Guard the contract itself: a moved frontend must fail loudly."""
        self.assertTrue(
            frontend_root().is_dir(),
            f"frontend source not found at {frontend_root()}",
        )

    def test_every_frontend_api_call_resolves_to_a_backend_route(self):
        routes = collect_api_routes(get_resolver())
        self.assertGreater(len(routes), 100, "URLconf enumeration looks broken")

        unresolved = []
        checked = 0
        for path in sorted(frontend_root().rglob("*")):
            if path.suffix not in (".js", ".jsx") or not path.is_file():
                continue
            source = path.read_text(encoding="utf-8")
            for match in API_CALL_RE.finditer(source):
                call_path = match.group(3)
                if not call_path.startswith("/"):
                    continue  # a local asset or an absolute external URL
                checked += 1
                if not any(resolves_to_route(call_path, regex)
                           for regex, _ in routes):
                    line = source[: match.start()].count("\n") + 1
                    unresolved.append(
                        f"{match.group(1).upper()} {call_path}  -> "
                        f"{path.relative_to(frontend_root())}:{line}"
                    )

        self.assertGreater(checked, 100, "no API calls were scanned")
        self.assertEqual(
            unresolved,
            [],
            "frontend calls with no matching backend route:\n  "
            + "\n  ".join(unresolved),
        )

    def test_the_route_matcher_agrees_with_django_on_real_routes(self):
        """The matcher must not be the weakest link in the contract.

        A contract test is only worth having if it fails when it should. Every
        route below was taken from this project's own urlconf. The cases are the
        ones that previously went wrong: a ``slug`` converter, DRF's ``[^/.]+``
        primary key, a route literal hiding behind an interpolated argument,
        and a list route that is a prefix of the detail route a call wants.

        Each case names the route the regex belongs to, so ``resolve()`` can
        adjudicate the same question the matcher answers: is *this* route the
        one that serves the call? Where ``resolve()`` cannot answer - because an
        interpolated segment has to become a particular literal, and no generic
        token resolves to that - the case is marked and the matcher stands alone.
        """
        routes = collect_api_routes(get_resolver())
        cases = [
            # (call, route name, expected, adjudicable, why)
            ("/auth/marketing-pages/${slug}/",
             "public-marketing-page", True, True,
             "a slug converter the old regex probe could not match"),
            ("/auth/platform/marketing-pages/${slug}/",
             "platform-marketing-page-detail", True, True,
             "the platform-admin detail route"),
            ("/employees/employees/${id}/photo/",
             "employee-photo", True, True,
             "DRF's [^/.]+ pk converter, whose / must not split it"),
            ("/leave/requests/${id}/${action}/",
             "leave-request-approve", True, False,
             "${action} meeting a literal route segment"),
            ("/employees/employees/${id}/360/",
             "employee-list", False, True,
             "the list route is not a stand-in for a detail route"),
            ("/ai/knowledge/${id}/",
             "ai-knowledge", False, True,
             "an id is not a knowledge-base slug"),
        ]
        by_name = {}
        for route_regex, name in routes:
            by_name.setdefault(name, []).append(route_regex)

        for call, name, expected, adjudicable, why in cases:
            with self.subTest(call=call, route=name):
                # Look the route up rather than pasting its regex. A regex
                # transcribed here would drift from the urlconf silently and
                # keep asserting whatever it said when it was written.
                self.assertIn(
                    name, by_name,
                    f"{why}: no route named {name!r} in the urlconf, so this "
                    "case is testing a route that does not exist",
                )
                candidates = by_name[name]
                # "Any variant serves the call" is the contract's own
                # semantics, and DRF registers each route twice: once bare and
                # once with a ``.json``-style format suffix. A call with no
                # suffix should match the bare one and not the suffixed one, so
                # the variants are expected to differ here.
                self.assertEqual(
                    any(resolves_to_route(call, rx) for rx in candidates),
                    expected,
                    f"{why}: the matcher disagrees with the expectation for "
                    f"{call} against {name!r}. Variants: " + "; ".join(
                        f"/{rx} -> {resolves_to_route(call, rx)}"
                        for rx in candidates),
                )
                if not adjudicable:
                    continue
                # The expectation should be Django's, not this test's. Assert
                # the real resolver lands on the same route, so a wrong
                # expectation is caught here instead of quietly enshrined.
                probe = "/api" + INTERP_RE.sub("x", call.split("?")[0])
                try:
                    resolved = resolve(probe).url_name
                except Resolver404:
                    resolved = None
                self.assertEqual(
                    resolved == name, expected,
                    f"{why}: resolve({probe!r}) returned {resolved!r}, so the "
                    "expectation above is wrong, not the matcher",
                )


class RouterRootMisuseTests(SimpleTestCase):
    """No frontend call may target a DefaultRouter's browsable API root.

    ``api/employees/`` is a real, registered route, so the route contract
    passes it. It is also useless as a data source: DRF answers it with
    ``{"employees": "...", "departments": "...", ...}``. Two pages fetched it
    that way, kept the result in state, and rendered an empty list forever
    because the defensive ``Array.isArray(d) ? d : d.results || []`` turned the
    dict into ``[]``. The symptom was an empty table with no error anywhere.
    """

    def test_no_frontend_call_targets_a_router_api_root(self):
        roots = collect_router_roots(get_resolver())
        self.assertTrue(
            roots,
            "no DRF router roots found - enumeration is broken, so this "
            "test would pass vacuously",
        )
        # Routes are "/api/employees/". The client prepends "/api" itself, so
        # the frontend spells the same call "/employees/"; both forms are banned.
        banned = set()
        for route in roots:
            full = "/" + route.lstrip("/")
            banned.add(full)
            banned.add(full[len("/api"):])

        offenders = []
        for path in sorted(frontend_root().rglob("*")):
            if path.suffix not in (".js", ".jsx") or not path.is_file():
                continue
            source = path.read_text(encoding="utf-8")
            for match in API_CALL_RE.finditer(source):
                call_path = match.group(3).split("?")[0]
                if call_path in banned:
                    line = source[: match.start()].count("\n") + 1
                    offenders.append(
                        f"{match.group(1).upper()} {call_path}  -> "
                        f"{path.relative_to(frontend_root())}:{line}"
                    )

        self.assertEqual(
            offenders,
            [],
            "frontend calls a DefaultRouter API root, which returns a dict of "
            "child URLs rather than a list of records; use the list route "
            "instead:\n  " + "\n  ".join(offenders),
        )
