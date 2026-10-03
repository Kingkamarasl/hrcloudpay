"""Seed every public landing page with its own managed content.

The content system shipped wired but empty: a data migration created two rows
(`home`, `security`) with `content={}`, and the other five public pages were
hardcoded in JSX with no row behind them at all. So "manage pages" in the
platform admin could edit two pages that had no copy in them, and five pages
that could not be reached.

This migration puts all seven under management. The copy is transcribed from
the JSX that already shipped, not newly written, so the live site reads
identically once the front end starts consuming it.

`home` and `security` deliberately get a hero section only. Those two pages
carry bespoke layouts - an animated workspace mockup, pillar grids, security
control grids - and rewriting them as generic sections would throw away real
design work to gain a section builder that only helps the five ledger pages.
Their remaining content stays in JSX; the hero is the part admins actually
revisit.

Rows that already hold content are left alone, so a re-run - or a deployment
where an admin has already written copy - never overwrites live edits. Rows
that hold nothing, which is the state migration 0012 left `home` and `security`
in, are filled in from the shipped JSX.
"""

from django.db import migrations

# Transcribed from frontend/src/pages/Platform.jsx
PLATFORM = {
    'sections': [
        {
            'type': 'hero',
            'eyebrow': 'Platform',
            'title': 'One system for people ops and payday.',
            'title_accent': '',
            'subtitle': 'HRCloudPay connects employee records, time off, compliance, '
                        'and payroll in a single multi-tenant workspace built for '
                        'African businesses that set their own tax rules.',
            'primary_cta': 'Get started free',
            'primary_href': '/register',
            'secondary_cta': 'View pricing',
            'secondary_href': '/pricing',
        },
        {
            'type': 'feature_rows',
            'eyebrow': 'How it fits together',
            'title': 'From first hire to payslip, without switching tools.',
            'subtitle': 'Each module shares the same company, roles, and audit context.',
            'items': [
                {
                    'title': 'One workspace',
                    'body': 'Employees, payroll, attendance, leave, and compliance share '
                            'the same company account — not five tools bolted together.',
                },
                {
                    'title': 'Your tax rules',
                    'body': 'Configure currency, brackets, and statutory contributions '
                            'once. Every run applies them automatically.',
                },
                {
                    'title': 'Role-aware access',
                    'body': 'HR, finance, and department managers each see what their job '
                            'requires — and nothing they should not.',
                },
                {
                    'title': 'Audit-ready trail',
                    'body': 'Approvals, payroll status changes, and sensitive actions stay '
                            'visible for the people who need them.',
                },
            ],
        },
        {
            'type': 'cta',
            'eyebrow': 'Next step',
            'title': 'See payroll and HR in more detail.',
            'actions': [
                {'label': 'Payroll product', 'href': '/payroll-product'},
                {'label': 'HR product', 'href': '/hr'},
            ],
        },
    ],
}

# Transcribed from frontend/src/pages/PayrollProduct.jsx
PAYROLL_PRODUCT = {
    'sections': [
        {
            'type': 'hero',
            'eyebrow': 'Payroll',
            'title': 'Payroll that is clear from draft to payday.',
            'title_accent': '',
            'subtitle': 'Configure your company rules once, run a period, approve it, '
                        'and generate payslips — with status visible to finance and '
                        'locked down for everyone else.',
            'primary_cta': 'Start payroll setup →',
            'primary_href': '/register',
            'secondary_cta': 'View plans',
            'secondary_href': '/pricing',
        },
        {
            'type': 'checklist',
            'eyebrow': 'Pay cycle control',
            'title': 'Know exactly where payroll stands.',
            'body': 'Move from draft to processed, approved, and paid with a workflow '
                    'designed so finance always knows what is still open — and employees '
                    'can download their own payslip copies.',
            'items': [
                {'label': 'Progressive tax calculation from your brackets'},
                {'label': 'Employee and employer statutory contributions'},
                {'label': 'Draft → processed → approved → paid workflow'},
                {'label': 'Employee and company payslip PDF copies'},
                {'label': 'Protected payroll periods and export'},
            ],
        },
        {
            'type': 'cta',
            'eyebrow': 'Predictable payday',
            'title': 'Payroll should feel controlled.',
            'actions': [
                {'label': 'Get started', 'href': '/register'},
                {'label': 'See the platform', 'href': '/platform'},
            ],
        },
    ],
}

# Transcribed from frontend/src/pages/HRProduct.jsx
HR_PRODUCT = {
    'sections': [
        {
            'type': 'hero',
            'eyebrow': 'HR management',
            'title': 'People records that stay useful after onboarding.',
            'title_accent': '',
            'subtitle': 'Keep identity, contracts, attendance, and leave in one place — '
                        'with the right managers able to act, and everyone else kept out '
                        'of data they do not need.',
            'primary_cta': 'Get started →',
            'primary_href': '/register',
            'secondary_cta': 'Platform overview',
            'secondary_href': '/platform',
        },
        {
            'type': 'checklist',
            'eyebrow': 'What HR gets',
            'title': 'Structured records, not spreadsheet rows.',
            'body': 'HR managers work company-wide on employees and time off. Department '
                    'managers stay scoped to their teams. Finance never has to live inside '
                    'the same screens unless you grant it.',
            'items': [
                {'label': 'Employee 360 profiles with contracts and documents'},
                {'label': 'Departments and department-manager scoping'},
                {'label': 'Attendance, leave, and break requests with PDF forms'},
                {'label': 'Compliance rules and expiry warnings'},
                {'label': 'Automated HR tasks and notifications'},
            ],
        },
        {
            'type': 'cta',
            'eyebrow': 'Ready when you are',
            'title': 'Give HR one source of truth.',
            'actions': [
                {'label': 'Get started', 'href': '/register'},
                {'label': 'Compare plans', 'href': '/pricing'},
            ],
        },
    ],
}

# Transcribed from frontend/src/pages/About.jsx
ABOUT = {
    'sections': [
        {
            'type': 'hero',
            'eyebrow': 'About HRCloudPay',
            'title': "Payroll software shouldn't assume where you do business.",
            'title_accent': '',
            'subtitle': 'HRCloudPay is HR and payroll software built for African '
                        'businesses first — not adapted from a product designed for '
                        'somewhere else.',
            'primary_cta': '',
            'primary_href': '',
            'secondary_cta': '',
            'secondary_href': '',
        },
        {
            'type': 'prose_blocks',
            'eyebrow': '',
            'blocks': [
                {
                    'title': 'Why we built this',
                    'body': 'Most HR and payroll software is built for one country at a '
                            'time, or priced for businesses far larger than the small and '
                            'mid-sized companies that make up most of the African market. '
                            'Business owners are often left managing payroll in spreadsheets '
                            '— which works, until a tax rule changes or a new employee '
                            'joins and the calculations get harder to trust. HRCloudPay '
                            'exists to close that gap: affordable per-employee pricing, and '
                            'a payroll engine that adapts to whatever country you operate '
                            'in, instead of assuming one set of tax rules for everyone.',
                },
                {
                    'title': 'How the payroll engine works',
                    'body': 'After your company activates its account, you complete a '
                            'short setup form declaring your own tax brackets, statutory '
                            'contributions, and currency. From then on, every payroll run '
                            'uses exactly the rules you configured — nothing is hardcoded '
                            'to one country, so the same platform works whether you operate '
                            'in Guinea, Nigeria, Kenya, Ghana, or anywhere else on the '
                            'continent.',
                },
                {
                    'title': "Built for how your team is actually structured",
                    'body': "Owners and admins aren't the only people who touch HR and "
                            'payroll. HRCloudPay has separate HR Manager, Finance Manager, '
                            'and Department Manager roles, so payroll figures stay with '
                            'finance, employee records stay with HR, and a department '
                            "manager can approve their own team's leave without seeing "
                            "anyone else's.",
                },
                {
                    'title': "Who it's for",
                    'body': 'Small and mid-sized businesses that are ready to move payroll '
                            'off spreadsheets, without paying for enterprise software built '
                            "for a different market. Whether you're a 5-person team or "
                            'scaling past 150 employees, HRCloudPay has a plan that fits.',
                },
            ],
        },
        {
            'type': 'cta',
            'eyebrow': '',
            'title': '',
            'actions': [{'label': 'See our plans', 'href': '/pricing'}],
        },
    ],
}

# Transcribed from frontend/src/pages/Pricing.jsx
PRICING = {
    'sections': [
        {
            'type': 'hero',
            'eyebrow': 'Pricing',
            'title': 'One price per plan. No per-country surcharge.',
            'title_accent': '',
            'subtitle': 'Every plan includes the same configurable payroll engine — pick '
                        "a plan by team size, not by which country you're in.",
            'primary_cta': '',
            'primary_href': '',
            'secondary_cta': '',
            'secondary_href': '',
        },
        {
            'type': 'pricing',
            'eyebrow': '',
            'title': '',
            'subtitle': '',
            # `plan` links each card to the plan it describes. `price` and the
            # capacity sentence in `blurb` are left out on purpose: they are
            # derived from PLAN_PRICES and the limit tables when the page is
            # served (see hrcloudpay.pricing_sync), so a price change needs one
            # edit and the page cannot advertise a plan checkout would refuse.
            # What remains here - features, highlight, tagline - is the admin's.
            'plans': [
                {
                    'plan': 'starter',
                    'name': 'Starter',
                    'tagline': 'Core HR and payroll for a small team',
                    'features': ['Employee management', 'Basic payroll',
                                 'Payslip PDFs'],
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
                                 'Departments & warning letters',
                                 'Compliance document rules',
                                 'Automated HR notifications'],
                    'highlight': True,
                },
                {
                    'plan': 'scale',
                    'name': 'Scale',
                    'tagline': 'For larger teams running several departments',
                    'features': ['Everything in Professional',
                                 'AI company knowledge base',
                                 'Custom integrations',
                                 'Priority support'],
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
            ],
            'notes': [
                {
                    'title': 'Upgrade any time',
                    'body': 'Move to a higher plan as your team grows — your data, payroll '
                            'history, and configuration carry over.',
                },
                {
                    'title': 'Team accounts included',
                    'body': 'Each plan includes HR Manager, Finance Manager, and Department '
                            'Manager logins, not just one admin seat.',
                },
                {
                    'title': 'No setup fee',
                    'body': 'Configure your own tax brackets and statutory contributions '
                            'once, free, on every plan.',
                },
            ],
        },
    ],
}

# Transcribed from DEFAULT_HERO in frontend/src/pages/Home.jsx
HOME = {
    'sections': [
        {
            'type': 'hero',
            'eyebrow': 'The intelligent operating system for people, payroll & HR',
            'title': 'Run your people operations',
            'title_accent': 'with clarity.',
            'subtitle': 'HRCloudPay brings payroll, employee 360°, attendance, leave, '
                        'compliance, documents, and an AI HR assistant into one secure '
                        'workspace.',
            'primary_cta': 'Start for free',
            'primary_href': '/register',
            'secondary_cta': 'Explore the platform',
            'secondary_href': '/platform',
        },
    ],
}

# Transcribed from DEFAULT_SECURITY_HERO in frontend/src/pages/Security.jsx
SECURITY = {
    'sections': [
        {
            'type': 'hero',
            'eyebrow': 'Security & Trust',
            'title': 'Enterprise control without enterprise complexity.',
            'title_accent': '',
            'subtitle': 'HRCloudPay gives growing companies role-aware access, immutable '
                        'auditability, controlled payroll workflows, and a clear compliance '
                        'trail from employee record to payment evidence.',
            'primary_cta': 'Build your workspace',
            'primary_href': '/register',
            'secondary_cta': 'View plans',
            'secondary_href': '/pricing',
        },
    ],
}

PAGES = [
    ('home', 'Homepage', HOME),
    ('platform', 'Platform', PLATFORM),
    ('payroll-product', 'Payroll product', PAYROLL_PRODUCT),
    ('hr', 'HR product', HR_PRODUCT),
    ('about', 'About', ABOUT),
    ('pricing', 'Pricing', PRICING),
    ('security', 'Security & Trust', SECURITY),
]


def apply_seed(MarketingPage):
    """Create the five missing pages and fill in the two empty ones.

    A plain `get_or_create` would leave `home` and `security` empty forever:
    those rows were created by migration 0012 with `content={}`, so the create
    half never runs and the pages stay unmanageable. Existing rows are therefore
    only filled in when they hold no sections at all - the state 0012 left them
    in, and one that no admin edit could have produced on purpose. Anything with
    real content is left exactly as it is, so re-running this never overwrites
    live edits.

    Takes the model as an argument so a test can drive it against the real table
    and prove both halves of that behaviour, rather than only inspecting the
    data above.
    """
    for slug, name, content in PAGES:
        page, created = MarketingPage.objects.get_or_create(
            slug=slug,
            defaults={'name': name, 'content': content, 'is_published': True},
        )
        if not created and not (page.content or {}).get('sections'):
            page.content = content
            page.save(update_fields=['content', 'updated_at'])


def seed_pages(apps, schema_editor):
    apply_seed(apps.get_model('accounts', 'MarketingPage'))


def unseed_pages(apps, schema_editor):
    """Remove only pages still holding the copy this migration wrote.

    Guarded on the content itself rather than just the slug: if an admin has
    since edited a page, reversing the migration must not throw away their work.
    The `home` row predates this migration and is never removed.
    """
    MarketingPage = apps.get_model('accounts', 'MarketingPage')
    for slug, _, content in PAGES:
        if slug == 'home':
            continue
        MarketingPage.objects.filter(slug=slug, content=content).delete()


class Migration(migrations.Migration):

    dependencies = [('accounts', '0017_alter_paymentproviderconfig_provider_and_more')]

    operations = [
        migrations.RunPython(seed_pages, unseed_pages),
    ]
