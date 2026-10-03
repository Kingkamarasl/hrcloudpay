"""Give the managed pricing page the current plan grid.

`0018_seed_marketing_pages` fills a marketing row only while it is still empty,
which is the right rule for prose and the wrong one for structure. The plan grid
is not prose: adding the Scale tier, raising Starter's capacity and moving AI
onto Professional all have to reach the stored `pricing` row, or the public page
keeps advertising four plans and none of them carry AI.

Only the `plans` list of the `pricing` section is replaced. The notes, the hero,
and every other page are left alone, so an admin's copy survives a schema change
to the product. Inside the grid, the cards carry only what an admin owns - which
plan, the name, a tagline, the feature list, which card is highlighted. `price`
and the capacity sentence are deliberately absent: `hrcloudpay.pricing_sync`
derives both from `PLAN_PRICES` and the limit tables when the page is served, so
there is no second copy to drift.

Reversing puts the previous card list back.
"""

from django.db import migrations

# Transcribed from PRICING in 0018_seed_marketing_pages, before Scale existed and
# before AI was placed on a tier. Kept verbatim so a reverse migration restores
# exactly what the database held.
OLD_PLANS = [
    {
        'name': 'Starter',
        'price': '$15',
        'blurb': 'Up to 10 employees, 3 team accounts',
        'features': ['Employee management', 'Basic payroll',
                     'Payslip PDFs'],
        'highlight': False,
    },
    {
        'name': 'Business',
        'price': '$49',
        'blurb': 'Up to 50 employees, 15 team accounts',
        'features': ['Everything in Starter', 'Attendance tracking',
                     'Leave & break requests', 'HR reports'],
        'highlight': False,
    },
    {
        'name': 'Professional',
        'price': '$99',
        'blurb': 'Up to 150 employees, 50 team accounts',
        'features': ['Everything in Business', 'Departments & warning letters',
                     'Compliance document rules',
                     'Automated HR notifications'],
        'highlight': True,
    },
    {
        'name': 'Enterprise',
        'price': 'Custom',
        'blurb': '150+ employees, unlimited team accounts',
        'features': ['Everything in Professional', 'Custom integrations',
                     'Dedicated support'],
        'highlight': False,
    },
]


def replace_plans(plans):
    """Swap in ``plans``, leaving every other key of the page untouched."""
    page = MarketingPage.objects.filter(slug='pricing').first()
    if page is None:
        return
    content = page.content or {}
    sections = content.get('sections')
    if not isinstance(sections, list):
        return
    changed = False
    new_sections = []
    for section in sections:
        if isinstance(section, dict) and section.get('type') == 'pricing':
            section = dict(section)
            section['plans'] = [dict(p) for p in plans]
            changed = True
        new_sections.append(section)
    if not changed:
        return
    content = dict(content)
    content['sections'] = new_sections
    page.content = content
    page.save(update_fields=['content', 'updated_at'])


PLANS = [
    {
        'plan': 'starter',
        'name': 'Starter',
        'tagline': 'Core HR and payroll for a small team',
        'features': ['Employee management', 'Basic payroll', 'Payslip PDFs'],
        'highlight': False,
    },
    {
        'plan': 'business',
        'name': 'Business',
        'tagline': 'Time off and attendance on top of core HR',
        'features': ['Everything in Starter', 'Attendance tracking',
                     'Leave & break requests', 'HR reports'],
        'highlight': False,
    },
    {
        'plan': 'professional',
        'name': 'Professional',
        'tagline': 'Adds the AI assistant and compliance automation',
        'features': ['Everything in Business', 'AI HR assistant & drafts',
                     'Departments & warning letters', 'Compliance document rules',
                     'Automated HR notifications'],
        'highlight': True,
    },
    {
        'plan': 'scale',
        'name': 'Scale',
        'tagline': 'For larger teams running several departments',
        'features': ['Everything in Professional', 'AI company knowledge base',
                     'Custom integrations', 'Priority support'],
        'highlight': False,
    },
    {
        'plan': 'enterprise',
        'name': 'Enterprise',
        'tagline': 'By agreement, for unlimited headcount',
        'features': ['Everything in Scale', 'Dedicated account management',
                     'Custom integrations', 'Dedicated support'],
        'highlight': False,
    },
]


def forward(apps, schema_editor):
    global MarketingPage
    MarketingPage = apps.get_model('accounts', 'MarketingPage')
    replace_plans(PLANS)


def backward(apps, schema_editor):
    global MarketingPage
    MarketingPage = apps.get_model('accounts', 'MarketingPage')
    replace_plans(OLD_PLANS)


class Migration(migrations.Migration):

    dependencies = [('accounts', '0020_alter_company_plan')]

    operations = [
        migrations.RunPython(forward, backward),
    ]
