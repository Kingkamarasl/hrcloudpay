"""Move the homepage hero to the approved positioning.

The hero a visitor reads comes from the `home` MarketingPage row, and migration
0018 seeded that row on installs that already exist. Editing ``DEFAULT_HERO`` in
Home.jsx changes only the fallback used when the content endpoint is
unavailable, so without this the new copy would appear nowhere on a live site -
and the symptom would be "the deploy did nothing", which is not a self-reporting
failure.

Idempotent, and deliberately narrow: it touches only the homepage hero, and only
when the stored copy is still the copy this migration is replacing. An operator
who has already rewritten the hero by hand keeps their words - a later release
must not silently revert marketing copy somebody deliberately changed.
"""
from django.db import migrations

# The exact copy this migration supersedes, read back from a seeded database
# rather than assumed from the JSX. Guessing from DEFAULT_HERO would have been
# wrong here: the seeded hero is that fallback's own copy, so the migration would
# have declined to update it and the deploy would have looked like a no-op with
# no error anywhere to say why.
PREVIOUS_HERO = {
    'eyebrow': 'The intelligent operating system for people, payroll & HR',
    'title': 'Run your people operations',
    'title_accent': 'with clarity.',
    'subtitle': (
        'HRCloudPay brings payroll, employee 360\u00b0, attendance, leave, '
        'compliance, documents, and an AI HR assistant into one secure workspace.'
    ),
    'primary_cta': 'Start for free',
    'primary_href': '/register',
    'secondary_cta': 'Explore the platform',
    'secondary_href': '/platform',
}

NEW_HERO = {
    'eyebrow': 'People \u00b7 Payroll \u00b7 Progress',
    'title': 'Smarter HR & Payroll for a',
    'title_accent': 'Stronger Africa.',
    'subtitle': (
        'HRCloudPay is an all-in-one HR, payroll and workforce management platform '
        'built for African businesses. Simplify your operations, stay compliant, '
        'and focus on what matters most \u2014 your people.'
    ),
    'primary_cta': 'Build Your Stronger Workforce',
    'primary_href': '/register',
    'secondary_cta': 'Explore the platform',
    'secondary_href': '/platform',
}


def apply_positioning(apps, schema_editor):
    MarketingPage = apps.get_model('accounts', 'MarketingPage')

    page = MarketingPage.objects.filter(slug='home').first()
    if page is None:
        # A fresh database gets the right copy from the seed and from DEFAULT_HERO.
        # Nothing to do, and creating a row here would produce an empty page
        # shadowing the one the seed installs.
        return

    content = page.content or {}
    sections = content.get('sections')
    if not isinstance(sections, list):
        return

    changed = False
    for section in sections:
        if not isinstance(section, dict) or section.get('type') != 'hero':
            continue
        # Only overwrite copy we recognise. Somebody who has already retyped the
        # hero keeps it.
        recognisable = all(
            section.get(key) == value for key, value in PREVIOUS_HERO.items()
        ) or section.get('title') == NEW_HERO['title']
        if recognisable:
            section.update(NEW_HERO)
            changed = True
        break

    if changed:
        page.content = content
        page.save(update_fields=['content', 'updated_at'])


def revert_positioning(apps, schema_editor):
    """Put the superseded copy back.

    Only the keys this migration set, and only on a hero still carrying them.
    A full restore would overwrite anything an operator has written since.
    """
    MarketingPage = apps.get_model('accounts', 'MarketingPage')

    page = MarketingPage.objects.filter(slug='home').first()
    if page is None:
        return

    content = page.content or {}
    sections = content.get('sections')
    if not isinstance(sections, list):
        return

    for section in sections:
        if not isinstance(section, dict) or section.get('type') != 'hero':
            continue
        if section.get('title') == NEW_HERO['title']:
            # Restores PREVIOUS_HERO wholesale rather than patching the subtitle
            # by hand. The hand-written version reintroduced a sentence this
            # migration never held - it came from a different seed - so undoing
            # the change did not actually undo it.
            section.update(PREVIOUS_HERO)
        break

    page.content = content
    page.save(update_fields=['content', 'updated_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0025_marketingpage_seo'),
    ]

    operations = [
        migrations.RunPython(apply_positioning, revert_positioning),
    ]