from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny

from .site_icons import serve_apple_touch_icon, serve_favicon
from .views import robots_view, serve_frontend, serve_media, sitemap_view

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('accounts.urls')),
    path('api/auth/security/', include('security.urls')),
    path('api/employees/', include('employees.urls')),
    path('api/payroll/', include('payroll.urls')),
    path('api/attendance/', include('attendance.urls')),
    path('api/leave/', include('leave.urls')),
    path('api/integrations/', include('integrations.urls')),
    path('api/workflows/', include('workflows.urls')),
    path('api/regional/', include('regional.urls')),
    path('api/ai/', include('ai.urls')),
    # API documentation (public access)
    path('api/schema/', SpectacularAPIView.as_view(permission_classes=[AllowAny], authentication_classes=[]), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema', permission_classes=[AllowAny], authentication_classes=[]), name='swagger-ui'),
]

# Uploaded files are served in every environment, not just under DEBUG.
#
# `static()` used to do this job, but it was registered only when DEBUG was
# true, which left two problems: in production no uploaded file was reachable
# at all (company logos and employee photos 404 because the SPA is handed
# absolute /media/ URLs), and the "fix" of registering it unconditionally would
# have served every tenant's identity documents to anyone with the URL, since
# static() performs no identity check. serve_media keeps the route but applies
# the per-kind role rules in media_access.py.
#
# `(?P<path>.*)` is intentionally greedy and the view rejects traversal, rather
# than the safer-looking `[\w\-.]+` pattern, because the real storage names
# contain nested date directories (`employee_photos/2026/01/name.png`) that a
# single-segment pattern would not match.
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve_media, name='media'),
    # The site's own favicon and iOS icon, at fixed paths. `frontend/index.html`
    # links to these unconditionally, so an administrator can replace the icon
    # from the platform console with no frontend rebuild. Both are public by
    # necessity - a browser asks for a favicon before the visitor has any
    # session - and both are safe to expose because they are the platform's
    # brand mark rather than any tenant's data. See hrcloudpay/site_icons.py.
    re_path(r'^site-icon/favicon\.png$', serve_favicon, name='site-favicon'),
    re_path(r'^site-icon/apple-touch-icon\.png$', serve_apple_touch_icon, name='site-apple-touch-icon'),

    # Crawler-facing files. Registered before the SPA catch-all below, or
    # serve_frontend answers both with index.html and a crawler is handed an
    # empty page where it expects a sitemap.
    path('robots.txt', robots_view, name='robots'),
    path('sitemap.xml', sitemap_view, name='sitemap'),
]

# SPA catch-all: anything that isn't admin/api/static/media serves the
# built React app, so React Router handles the route client-side. This
# MUST stay last - Django tries urlpatterns in order, and this matches
# everything.
urlpatterns += [
    re_path(r'^(?!api(?:/|$)|admin(?:/|$)).*$', serve_frontend),
]
