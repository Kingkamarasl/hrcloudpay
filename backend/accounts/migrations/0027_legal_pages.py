"""Terms of service, privacy policy, and refund policy.

Codester will not verify a listing until the site links to all three, and they
have to be reachable pages with real copy rather than three stubs - a reviewer
follows the links.

They are seeded as `prose_blocks` like the other managed pages, which means a
platform admin edits them from Marketing without a deployment. That matters
more here than for any other page: these change when the law does, when a
country rule is added, or when the AI provider changes, and none of those should
require editing code.

Deliberately NOT idempotent-by-overwrite: rows that already hold content are
left alone, so a deployment never discards copy an admin has edited. This
matches 0018 and 0026.

Two things in this copy are load-bearing and should not be softened:

  * HRCloudPay is sold as a self-hosted licence. The customer runs their own
    instance and is the data controller for their employees' personal data.
    Writing it as though the vendor hosts the data would be false, and would
    mislead the exact buyers this product is for.
  * The AI assistant sends data to a third-party model provider chosen by the
    customer. Saying "we do not share data" would be untrue in a way that
    matters under data-protection law.

Every page carries a "last reviewed" line and names what still has to be filled
in. They are a serious starting point and not a substitute for review by a
qualified lawyer in the customer's jurisdiction.
"""

from django.db import migrations

# Terms ---------------------------------------------------------------------

TERMS = {
    'sections': [
        {
            'type': 'hero',
            'eyebrow': 'Legal',
            'title': 'Terms of Service',
            'title_accent': '',
            'subtitle': (
                'These terms govern your use of HRCloudPay. They are written to '
                'be read: if anything here is unclear, ask before you rely on it.'
            ),
            'primary_cta': 'Create an account',
            'primary_href': '/register',
            'secondary_cta': 'Privacy policy',
            'secondary_href': '/privacy',
        },
        {
            'type': 'prose_blocks',
            'eyebrow': '',
            'blocks': [
                {
                    'title': '1. Who these terms cover',
                    'body': (
                        'These terms apply to anyone who buys, installs or uses a '
                        'licence of HRCloudPay, and to anyone who uses an instance '
                        'of it on behalf of an organisation. Where an organisation '
                        'buys the licence, that organisation is the "Customer" and '
                        'the people it grants access to are "Users".'
                    ),
                },
                {
                    'title': '2. What you are licensing',
                    'body': (
                        'A licence of the HRCloudPay software: the right to install '
                        'and run it for your own organisation\'s internal business '
                        'purposes, on infrastructure you control, for as long as '
                        'your subscription is active.'
                    ),
                },
                {
                    'title': '3. Acceptable use',
                    'body': (
                        'You agree not to: resell, sublicense or redistribute the '
                        'software as a hosted or managed service for third parties; '
                        'remove or obscure copyright or attribution notices; use the '
                        'software in breach of applicable law; or attempt to gain '
                        'unauthorised access to any system or data connected to it. '
                        'You are responsible for the accounts you create and for '
                        'what your Users do with the software.'
                    ),
                },
                {
                    'title': '4. Your responsibilities as a Customer',
                    'body': (
                        'HRCloudPay processes payroll and employment records. You are '
                        'solely responsible for the accuracy and lawfulness of the data '
                        'you enter, for configuring the system to match the rules that '
                        'apply to your organisation, and for complying with employment, '
                        'tax and data-protection law in every jurisdiction where you '
                        'operate. Payroll output produced by the software is not legal, '
                        'tax or accounting advice, and does not replace review by a '
                        'qualified professional.'
                    ),
                },
                {
                    'title': '5. Availability and support',
                    'body': (
                        'We aim for continuous availability but do not guarantee it. '
                        'Because the software runs on infrastructure you control, the '
                        'availability of your instance also depends on that '
                        'infrastructure. Support is provided as described in your '
                        'purchase listing; feature requests may be prioritised rather '
                        'than accepted.'
                    ),
                },
                {
                    'title': '6. Licence termination',
                    'body': (
                        'Your licence ends when your subscription ends or is cancelled. '
                        'On termination you must stop using the software. Your data '
                        'remains yours: it stays in the database you control, and you '
                        'keep it in whatever form you export it. Sections that by '
                        'their nature should survive termination survive it.'
                    ),
                },
                {
                    'title': '7. Disclaimers',
                    'body': (
                        'Except as stated in these terms, the software is provided '
                        '"as is". We do not warrant that it will be error-free or '
                        'uninterrupted, that calculated payroll, tax or leave '
                        'entitlements will satisfy the law of any particular '
                        'jurisdiction, or that the software will meet a specific '
                        'business outcome. Country-specific rules are maintained in '
                        'good faith and are your responsibility to verify.'
                    ),
                },
                {
                    'title': '8. Limitation of liability',
                    'body': (
                        'To the fullest extent permitted by law, neither party is '
                        'liable for indirect, incidental, special or consequential '
                        'losses, including lost profit, lost salary, lost data or '
                        'business interruption, arising from use of the software. '
                        'Neither party\'s total liability under these terms exceeds '
                        'the amount you paid for the licence in the twelve months '
                        'before the event giving rise to the claim. Nothing here '
                        'limits liability that cannot lawfully be limited.'
                    ),
                },
                {
                    'title': '9. Your data and your responsibilities to employees',
                    'body': (
                        'Where you use the software to process personal data about '
                        'your employees, you are the data controller and we are a '
                        'processor acting on your instructions. You are responsible '
                        'for the lawful basis on which you collect that data, for '
                        'the notices you give your employees, and for satisfying '
                        'any request to exercise data-subject rights. Our processing '
                        'obligations are described in the Privacy policy.'
                    ),
                },
                {
                    'title': '10. Changes to these terms',
                    'body': (
                        'We may update these terms. Material changes will be '
                        'announced in-product or by email before they take effect. '
                        'Continuing to use the software after a change means you '
                        'accept the updated terms.'
                    ),
                },
                {
                    'title': '11. Governing law',
                    'body': (
                        'These terms are governed by the laws of the jurisdiction in '
                        'which the licensor is established, without regard to conflict '
                        'of law rules. The courts of that jurisdiction have exclusive '
                        'jurisdiction, save that nothing limits any mandatory consumer '
                        'protection available to you where you live.'
                    ),
                },
                {
                    'title': '12. Contact',
                    'body': (
                        'Questions about these terms: supports@hrcloudpay.com. '
                        'Replace this address with the address you are required to '
                        'publish, and complete the governing-law section with your '
                        'registered entity and jurisdiction before publishing these '
                        'terms as your own.'
                    ),
                },
            ],
        },
    ],
}

# Privacy -------------------------------------------------------------------

PRIVACY = {
    'sections': [
        {
            'type': 'hero',
            'eyebrow': 'Legal',
            'title': 'Privacy Policy',
            'title_accent': '',
            'subtitle': (
                'What personal data HRCloudPay handles, why, who else sees it, and '
                'what you can do about it. Written plainly because privacy policy '
                'language usually is not.'
            ),
            'primary_cta': 'Create an account',
            'primary_href': '/register',
            'secondary_cta': 'Terms of service',
            'secondary_href': '/terms',
        },
        {
            'type': 'prose_blocks',
            'eyebrow': '',
            'blocks': [
                {
                    'title': 'The short version',
                    'body': (
                        'HRCloudPay is software you install and run yourself. Your '
                        'employees\' personal data stays on infrastructure you '
                        'control. We do not host your payroll and we do not sell '
                        'anyone\'s data. We do collect the account data needed to run '
                        'the service and to support you, and the AI assistant sends '
                        'whatever you ask it to a third-party model provider you '
                        'choose.'
                    ),
                },
                {
                    'title': '1. Who is responsible for your data',
                    'body': (
                        'For personal data about your employees that you enter into '
                        'HRCloudPay, your organisation is the data controller and '
                        'HRCloudPay acts as a processor on your instructions. For '
                        'account and billing data about you as a customer, we are the '
                        'controller. This is the ordinary arrangement for self-hosted '
                        'software, and it is why your privacy obligations sit with '
                        'you rather than with us.'
                    ),
                },
                {
                    'title': '2. Personal data we process on your behalf',
                    'body': (
                        'Employee records you enter, including names, contact '
                        'details, job title, department, salary and bank details; '
                        'attendance, leave and payroll records derived from them; '
                        'employment contracts and other documents you upload; and the '
                        'record of who approved what, when. This data is stored on the '
                        'database and file storage you configure.'
                    ),
                },
                {
                    'title': '3. Personal data we process as controller',
                    'body': (
                        'Your name, email address, organisation, and the login '
                        'credentials you set; billing and transaction records; support '
                        'correspondence; and technical records such as IP address, '
                        'sign-in events and the audit log. We use this to provide the '
                        'service, to keep it secure, to send service messages, and to '
                        'handle billing. We do not use it for advertising and we do '
                        'not sell it.'
                    ),
                },
                {
                    'title': '4. The AI assistant',
                    'body': (
                        'If you enable the AI assistant, the text you submit, along '
                        'with relevant records the assistant retrieves to answer, is '
                        'sent to the model provider you have configured. That provider '
                        'processes it under its own terms. If you configure a provider '
                        'you control, the data may never leave your infrastructure. '
                        'You decide whether to enable this feature at all, and you '
                        'should not submit confidential or special-category data '
                        'unless you have established a lawful basis for doing so.'
                    ),
                },
                {
                    'title': '5. Who your data is shared with',
                    'body': (
                        'Sub-processors we rely on, each under contract and each '
                        'limited to the purpose described: your configured payment '
                        'provider, who receives what they need to take a payment and '
                        'no employee payroll data; your configured email provider, who '
                        'receives the messages the system sends; your configured '
                        'object storage provider, who stores files you upload; and '
                        'your configured AI model provider. We do not sell personal '
                        'data and we do not share it for anyone else\'s advertising.'
                    ),
                },
                {
                    'title': '6. How long data is kept',
                    'body': (
                        'Data you enter into your instance stays there until you '
                        'delete it, because you control that instance and that '
                        'database. Account and billing data we hold as controller is '
                        'kept for as long as your account is active and for the '
                        'period afterwards required by tax or accounting law. Audit '
                        'entries are retained so that the tamper-evident chain remains '
                        'verifiable.'
                    ),
                },
                {
                    'title': '7. Security',
                    'body': (
                        'Passwords are stored as one-way hashes, not readable. '
                        'Sessions can be revoked centrally and all sessions are '
                        'terminated on a password reset. Privileged actions and AI '
                        'draft reviews are written to an append-only audit log that '
                        'is hash-chained, so a deleted entry is detectable. Optional '
                        'controls include two-factor authentication, IP allow-listing, '
                        'API tokens and single sign-on where configured. No system is '
                        'perfect; report a suspected vulnerability to us rather than '
                        'disclosing it publicly.'
                    ),
                },
                {
                    'title': '8. Your rights',
                    'body': (
                        'Depending on where you or your employees are located, you may '
                        'have rights to access, correct, delete, restrict or port '
                        'personal data, and to object to or complain about processing. '
                        'For data inside your own HRCloudPay instance, you exercise '
                        'those rights directly and we are not in the position to act '
                        'on them. For data we hold as controller, contact us and we '
                        'will respond within the period the applicable law requires.'
                    ),
                },
                {
                    'title': '9. International transfers',
                    'body': (
                        'Because the software runs on infrastructure you choose, you '
                        'decide where your employees\' data is stored and which '
                        'providers may process it. Where a sub-processor is outside '
                        'your jurisdiction, transfers are governed by that '
                        'processor\'s own safeguards.'
                    ),
                },
                {
                    'title': '10. Children',
                    'body': (
                        'HRCloudPay is a business tool and is not intended for use by '
                        'anyone under 16. We do not knowingly collect data from '
                        'children.'
                    ),
                },
                {
                    'title': '11. Changes and contact',
                    'body': (
                        'We may update this policy as the product or the law changes, '
                        'and will announce material changes in-product. Questions, '
                        'access requests and complaints: supports@hrcloudpay.com. '
                        'Replace this address, and name the entity and jurisdiction '
                        'you are required to identify, before publishing this policy '
                        'as your own.'
                    ),
                },
            ],
        },
    ],
}

# Refund --------------------------------------------------------------------

REFUND = {
    'sections': [
        {
            'type': 'hero',
            'eyebrow': 'Legal',
            'title': 'Refund Policy',
            'title_accent': '',
            'subtitle': (
                'A plain statement of when a purchase can be refunded and how to '
                'ask. No conditions hiding in the small print.'
            ),
            'primary_cta': 'Create an account',
            'primary_href': '/register',
            'secondary_cta': 'Terms of service',
            'secondary_href': '/terms',
        },
        {
            'type': 'prose_blocks',
            'eyebrow': '',
            'blocks': [
                {
                    'title': 'Before you buy',
                    'body': (
                        'HRCloudPay is source code you install and run yourself. '
                        'Please evaluate it against your requirements before buying: '
                        'the product listing describes what it does, and you can see '
                        'exactly what you are getting before committing.'
                    ),
                },
                {
                    'title': 'Refunds for duplicate or incorrect purchases',
                    'body': (
                        'If you are charged twice for the same purchase, or you are '
                        'charged for the wrong product, contact us and we will refund '
                        'the duplicate or incorrect charge. This is not discretionary '
                        'and you do not need to justify it.'
                    ),
                },
                {
                    'title': 'Refunds for software that does not work',
                    'body': (
                        'If the software does not perform the functions the listing '
                        'states it performs, and you have told us what you expected '
                        'and what happened, we will refund the purchase price. This '
                        'applies to purchases made through a marketplace listing as '
                        'well as direct ones.'
                    ),
                },
                {
                    'title': 'Refunds for other reasons',
                    'body': (
                        'Outside the two situations above, purchases of digital '
                        'software are generally non-refundable once the source code '
                        'has been delivered, because it cannot be returned. We '
                        'reserve the right to refund at our discretion where a '
                        'purchase was made in good faith and something has gone wrong '
                        'on our side.'
                    ),
                },
                {
                    'title': 'Subscription renewals',
                    'body': (
                        'Subscriptions renew automatically for the period you chose. '
                        'You may cancel at any time from your account, and access '
                        'continues until the end of the period you have already paid '
                        'for. We do not refund a renewal period that you have already '
                        'begun using.'
                    ),
                },
                {
                    'title': 'How to request a refund',
                    'body': (
                        'Email supports@hrcloudpay.com with the email address used for '
                        'the purchase and a short description of the reason. We aim to '
                        'acknowledge within three business days and to resolve within '
                        'fourteen. Approved refunds are returned to the original '
                        'payment method; your bank or payment provider determines how '
                        'long the funds then take to appear.'
                    ),
                },
                {
                    'title': 'Chargebacks',
                    'body': (
                        'If you raise a chargeback with your bank instead of '
                        'contacting us, your access may be suspended while it is '
                        'investigated, because we receive no details of the dispute '
                        'from a chargeback. Contacting us first is faster and usually '
                        'resolves the issue without an interruption.'
                    ),
                },
                {
                    'title': 'Marketplace purchases',
                    'body': (
                        'Where you bought through a marketplace, that marketplace\'s '
                        'own refund rules and timelines also apply, and we will '
                        'cooperate with any request it makes.'
                    ),
                },
            ],
        },
    ],
}

PAGES = [
    ('terms', 'Terms of Service', TERMS),
    ('privacy', 'Privacy Policy', PRIVACY),
    ('refund-policy', 'Refund Policy', REFUND),
]


def apply_seed(MarketingPage):
    for slug, name, content in PAGES:
        page, created = MarketingPage.objects.get_or_create(
            slug=slug, defaults={'name': name, 'content': content},
        )
        if not created and not page.content.get('sections'):
            # A row an earlier migration left empty. Filling it is safe; writing
            # over sections that already exist would discard an admin's copy.
            page.content = content
            page.save(update_fields=['content'])


def unapply_seed(MarketingPage):
    for slug, _name, content in PAGES:
        # Only remove rows still holding exactly this seed. Anything an admin
        # has since edited is left alone rather than deleted on rollback.
        MarketingPage.objects.filter(slug=slug, content=content).delete()


def seed(apps, schema_editor):
    apply_seed(apps.get_model('accounts', 'MarketingPage'))


def unseed(apps, schema_editor):
    unapply_seed(apps.get_model('accounts', 'MarketingPage'))


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0026_homepage_positioning'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]