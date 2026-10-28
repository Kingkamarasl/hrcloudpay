"""Remove the two security controls the privacy policy does not implement.

0027 was edited in place to drop "IP allow-listing" and single sign-on from the
privacy policy, and editing an applied migration does nothing on an instance
that already ran it. Production therefore kept the false sentence while the
source looked correct. This migration repairs the stored copy.

It rewrites only the exact old sentence, so an administrator who has already
edited the surrounding block keeps their wording everywhere else.

The security marketing page had the same kind of claim, but that page is
frontend source rather than a database row, so it needed no repair here.
"""

from django.db import migrations

OLD = (
    'Optional controls include two-factor authentication, IP allow-listing, '
    'API tokens and single sign-on where configured.'
)
NEW = (
    'Two-factor authentication can be enrolled per account, and API tokens can '
    'be issued for integrations and revoked centrally.'
)


def _rewrite(MarketingPage, old, new):
    for page in MarketingPage.objects.filter(slug='privacy'):
        content = page.content or {}
        changed = False
        for section in content.get('sections', []):
            for block in section.get('blocks', []):
                body = block.get('body') or ''
                if old in body:
                    block['body'] = body.replace(old, new)
                    changed = True
        if changed:
            page.content = content
            page.save(update_fields=['content'])


def repair(apps, schema_editor):
    _rewrite(apps.get_model('accounts', 'MarketingPage'), OLD, NEW)


def unrepair(apps, schema_editor):
    _rewrite(apps.get_model('accounts', 'MarketingPage'), NEW, OLD)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0029_idempotencyrecord_started_at'),
    ]

    operations = [
        migrations.RunPython(repair, unrepair),
    ]
