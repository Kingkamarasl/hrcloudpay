from django.db import models
from django.conf import settings
from django.utils import timezone


# NOTE: this file is restored to match migrations 0001-0023 and the code in
# platform.py / billing.py / site_icons.py. Do not run `makemigrations` until
# `python manage.py makemigrations --check --dry-run` reports no changes.

class AuditLog(models.Model):
    ACTIONS = [
        ('create', 'Create'), ('update', 'Update'), ('delete', 'Delete'),
        ('activate', 'Activate'), ('suspend', 'Suspend'), ('login', 'Login'),
        ('logout', 'Logout'), ('login_failed', 'Login failed'), ('invite', 'Invite'),
        ('permission_change', 'Permission change'), ('salary_change', 'Salary change'),
        ('termination', 'Termination'), ('contract_change', 'Contract change'),
        ('payroll_process', 'Payroll process'), ('payroll_approve', 'Payroll approval'),
        ('payroll_payment', 'Payroll payment'), ('system', 'System'),
        ('security', 'Security event'), ('integration_import', 'Integration import'),
        ('integration_rollback', 'Integration rollback'), ('account_status', 'Account status'),
        ('data_export', 'Data export'), ('disciplinary_action', 'Disciplinary action'),
        ('leave_approve', 'Leave approval'), ('leave_reject', 'Leave rejection'),
    ]
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='audit_actions')
    company = models.ForeignKey('Company', null=True, blank=True, on_delete=models.SET_NULL, related_name='audit_logs')
    action = models.CharField(max_length=30, choices=ACTIONS, default='system')
    target_type = models.CharField(max_length=80, blank=True)
    target_id = models.CharField(max_length=80, blank=True)
    message = models.CharField(max_length=500)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    request_id = models.CharField(max_length=64, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    chain_sequence = models.BigIntegerField(null=True, editable=False)
    previous_hash = models.CharField(max_length=64, blank=True, editable=False)
    integrity_hash = models.CharField(max_length=64, blank=True, editable=False)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['company', '-created_at'], name='accounts_au_company_54fc08_idx'),
            models.Index(fields=['action', '-created_at'], name='accounts_au_action_f18cdc_idx'),
            models.Index(fields=['target_type', 'target_id'], name='accounts_au_target__0c7dca_idx'),
        ]

    def __str__(self):
        return f'{self.created_at} {self.actor} {self.action}'

    def _seal(self):
        """Link this record into the chain and write its digest.

        Called after the INSERT, not before, because `created_at` is covered by
        the digest and `auto_now_add` only assigns it during the insert. Hashing
        a predicted timestamp would produce a digest that never matches the row
        actually stored, and every record would read as tampered.

        The chain state row is locked so two concurrent writers cannot claim the
        same sequence number. Locking it before reading `last_sequence` and
        releasing after the update is the only ordering that cannot deadlock:
        every writer takes the same lock first, so there is no cycle to form.
        """
        from django.db import transaction

        from .audit_chain import GENESIS_HASH, compute_integrity_hash

        with transaction.atomic():
            state = AuditChainState.objects.select_for_update().get(key='global')
            self.chain_sequence = state.last_sequence + 1
            self.previous_hash = state.last_hash or GENESIS_HASH
            self.integrity_hash = compute_integrity_hash(self)

            AuditLog.objects.filter(pk=self.pk).update(
                chain_sequence=self.chain_sequence,
                previous_hash=self.previous_hash,
                integrity_hash=self.integrity_hash,
            )
            state.last_sequence = self.chain_sequence
            state.last_hash = self.integrity_hash
            state.save(update_fields=['last_sequence', 'last_hash'])

    def save(self, *args, **kwargs):
        """Seal new records into the chain; never re-seal existing ones.

        Re-sealing on update would be actively dangerous: anyone able to edit an
        audit row through the ORM could recompute its digest and leave no trace.
        So an update leaves the stored digest alone, and a legitimate edit
        therefore shows up as tampering - which for an append-only log is the
        correct outcome, not a bug to be smoothed over.
        """
        from .audit_chain import GENESIS_HASH

        adding = self._state.adding
        if adding and not self.chain_sequence:
            # Created outside the lock so two writers racing on the very first
            # audit row of a fresh database do not both try to insert it.
            AuditChainState.objects.get_or_create(
                key='global', defaults={'last_sequence': 0, 'last_hash': GENESIS_HASH},
            )
            super().save(*args, **kwargs)
            self._seal()
            return
        super().save(*args, **kwargs)


class AuditChainState(models.Model):
    key = models.CharField(max_length=32, unique=True, default='global')
    last_sequence = models.BigIntegerField(default=0)
    last_hash = models.CharField(max_length=64, default='0' * 64)

    def __str__(self):
        return f'AuditChainState({self.key})'


class Subscription(models.Model):
    STATUS_CHOICES = [('trial', 'Trial'), ('active', 'Active'), ('past_due', 'Past due'),
                      ('cancelled', 'Cancelled'), ('grace', 'Grace'), ('expired', 'Expired')]
    CYCLES = [('monthly', 'Monthly'), ('annual', 'Annual')]
    PROVIDERS = [('manual', 'Manual'), ('flutterwave', 'Flutterwave'), ('paystack', 'Paystack'),
                 ('stripe', 'Stripe'), ('paddle', 'Paddle')]

    company = models.OneToOneField('Company', on_delete=models.CASCADE, related_name='subscription')
    plan = models.CharField(max_length=20, default='starter')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='trial')
    billing_cycle = models.CharField(max_length=10, choices=CYCLES, default='monthly')
    monthly_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default='USD')
    started_at = models.DateTimeField(null=True, blank=True)
    renews_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    external_customer_id = models.CharField(max_length=150, blank=True)
    external_subscription_id = models.CharField(max_length=150, blank=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    grace_ends_at = models.DateTimeField(null=True, blank=True)
    provider = models.CharField(max_length=20, choices=PROVIDERS, default='manual')
    provider_plan_id = models.CharField(max_length=150, blank=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    cancellation_reason = models.CharField(max_length=255, blank=True)
    last_payment_at = models.DateTimeField(null=True, blank=True)
    failed_payment_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.company} - {self.status}'


class SuspensionEvent(models.Model):
    company = models.ForeignKey('Company', on_delete=models.CASCADE, related_name='suspensions')
    suspended_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    reason = models.CharField(max_length=255)
    notes = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']


class PlatformNotification(models.Model):
    LEVELS = [('info', 'Info'), ('success', 'Success'), ('warning', 'Warning'), ('danger', 'Urgent')]
    title = models.CharField(max_length=180)
    message = models.TextField()
    level = models.CharField(max_length=10, choices=LEVELS, default='info')
    company = models.ForeignKey('Company', null=True, blank=True, on_delete=models.CASCADE, related_name='platform_notifications')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']


class SupportTicket(models.Model):
    STATUS = [('open', 'Open'), ('in_progress', 'In progress'), ('waiting', 'Waiting'), ('resolved', 'Resolved')]
    PRIORITY = [('low', 'Low'), ('normal', 'Normal'), ('high', 'High'), ('urgent', 'Urgent')]
    company = models.ForeignKey('Company', on_delete=models.CASCADE, related_name='support_tickets')
    subject = models.CharField(max_length=180)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS, default='open')
    priority = models.CharField(max_length=10, choices=PRIORITY, default='normal')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='support_tickets_created')
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='support_tickets_assigned')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f'#{self.id} {self.subject}'


class PaymentProviderConfig(models.Model):
    PROVIDERS = [('flutterwave', 'Flutterwave'), ('paystack', 'Paystack'), ('stripe', 'Stripe'), ('paddle', 'Paddle')]
    ENVIRONMENTS = [('test', 'Test'), ('live', 'Live')]
    provider = models.CharField(max_length=30, choices=PROVIDERS, unique=True)
    enabled = models.BooleanField(default=False)
    public_key = models.CharField(max_length=255, blank=True)
    encrypted_secret_key = models.TextField(blank=True)
    webhook_secret = models.TextField(blank=True)
    environment = models.CharField(max_length=10, choices=ENVIRONMENTS, default='test')
    configured_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['provider']

    def __str__(self):
        return f'{self.provider} ({self.environment})'


class PaymentPlan(models.Model):
    provider = models.CharField(max_length=30)
    plan = models.CharField(max_length=20)
    billing_cycle = models.CharField(max_length=10)
    currency = models.CharField(max_length=10)
    external_plan_id = models.CharField(max_length=150)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('provider', 'plan', 'billing_cycle', 'currency')]


class PaymentEvent(models.Model):
    provider = models.CharField(max_length=30)
    event_id = models.CharField(max_length=180, unique=True)
    event_type = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, default='received')
    payload = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-received_at']


class PaymentTransaction(models.Model):
    STATUS = [('pending', 'Pending'), ('paid', 'Paid'), ('failed', 'Failed'), ('cancelled', 'Cancelled')]
    company = models.ForeignKey('Company', on_delete=models.CASCADE, related_name='payment_transactions')
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name='payment_transactions')
    provider = models.CharField(max_length=30)
    reference = models.CharField(max_length=120, unique=True)
    provider_transaction_id = models.CharField(max_length=150, blank=True)
    plan = models.CharField(max_length=20)
    billing_cycle = models.CharField(max_length=10)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10)
    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    checkout_url = models.URLField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


class BillingInvoice(models.Model):
    STATUS = [('issued', 'Issued'), ('paid', 'Paid'), ('void', 'Void')]
    company = models.ForeignKey('Company', on_delete=models.CASCADE, related_name='billing_invoices')
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name='billing_invoices')
    transaction = models.OneToOneField(PaymentTransaction, null=True, blank=True, on_delete=models.SET_NULL, related_name='invoice')
    number = models.CharField(max_length=60, unique=True)
    plan = models.CharField(max_length=20)
    billing_cycle = models.CharField(max_length=10)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10)
    status = models.CharField(max_length=12, choices=STATUS, default='issued')
    issued_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-issued_at']
        indexes = [models.Index(fields=['company', '-issued_at'], name='accounts_bi_company_02cdab_idx')]


class FeatureFlag(models.Model):
    ENVIRONMENTS = [('all', 'All'), ('test', 'Test'), ('live', 'Live')]
    key = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=False)
    rollout_percent = models.PositiveSmallIntegerField(default=100)
    environment = models.CharField(max_length=10, choices=ENVIRONMENTS, default='all')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']


class MarketingPage(models.Model):
    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=160)
    content = models.JSONField(default=dict, blank=True)
    is_published = models.BooleanField(default=True)

    # Search metadata. Injected into the served HTML by hrcloudpay.seo, because
    # every public route is a SPA route and they would otherwise all ship the
    # same hardcoded title and description. Blank means "fall back", not "empty":
    # an empty meta description tells a crawler the page has nothing to say.
    meta_title = models.CharField(
        max_length=120, blank=True, default='',
        help_text='Overrides the title a crawler sees. Aim for 50-60 characters.',
    )
    meta_description = models.CharField(
        max_length=320, blank=True, default='',
        help_text='Overrides the description a crawler sees. Aim for 140-160.',
    )
    og_image_url = models.CharField(
        max_length=500, blank=True, default='',
        help_text='Absolute URL of the link-preview image. Blank shares without one.',
    )
    noindex = models.BooleanField(
        default=False,
        help_text='Keep out of search engines, and out of sitemap.xml.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='marketing_pages_updated')
    draft_content = models.JSONField(null=True, blank=True)
    draft_name = models.CharField(max_length=160, blank=True)
    draft_is_published = models.BooleanField(null=True, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.slug


class SiteBranding(models.Model):
    favicon = models.ImageField(upload_to='site_icons/', null=True, blank=True)
    apple_touch_icon = models.ImageField(upload_to='site_icons/', null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='site_branding_updated')

    class Meta:
        verbose_name = 'site branding'
        verbose_name_plural = 'site branding'



class BillingPlan(models.Model):
    PLAN_CHOICES = [
        ('starter', 'Starter'),
        ('business', 'Business'),
        ('professional', 'Professional'),
        ('scale', 'Scale'),
        ('enterprise', 'Enterprise'),
    ]
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, unique=True)
    name = models.CharField(max_length=60)
    monthly_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    annual_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    employee_limit = models.IntegerField(null=True, blank=True)
    user_limit = models.IntegerField(null=True, blank=True)
    ai_enabled = models.BooleanField(default=False)
    highlight = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.name


class EmailConfig(models.Model):
    """Site-wide outbound SMTP configuration, set by a platform superuser.

    A singleton: at most one row. This lives in the database rather than the
    environment because the person who can make mail work is the person who runs
    the platform, and they should not need a deployment edit to do it.
    EMAIL_BACKEND in the environment still wins when set explicitly, so an
    operator is never locked out of the setting.

    The SMTP password is encrypted at rest with the same Fernet helper that
    protects payment provider secrets and the AI provider key
    (`accounts.secrets`). The API returns only `password_set`, a boolean, and
    the audit row records `password_changed` - never the value itself.
    """

    host = models.CharField(max_length=255, blank=True)
    port = models.PositiveIntegerField(default=587)
    username = models.CharField(max_length=255, blank=True)
    encrypted_password = models.TextField(blank=True)
    use_tls = models.BooleanField(
        default=True,
        help_text='STARTTLS on an existing connection. Mutually exclusive with SSL.')
    use_ssl = models.BooleanField(
        default=False,
        help_text='Implicit TLS from the first byte, usually port 465. '
                  'Mutually exclusive with TLS.')
    from_email = models.EmailField(blank=True)
    timeout_seconds = models.PositiveIntegerField(default=30)
    # Off until a host is supplied. An active-but-wrong config silently swallows
    # every message, which is worse than the console backend's noise.
    is_active = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='email_config_updates',
    )

    class Meta:
        verbose_name = 'email configuration'

    def __str__(self):
        return f'Email via {self.host}:{self.port}' if self.host else 'Email (not configured)'

    def set_password(self, value):
        from .secrets import encrypt_secret
        self.encrypted_password = encrypt_secret(value or '')

    def get_password(self):
        from .secrets import decrypt_secret
        return decrypt_secret(self.encrypted_password)

    @property
    def password_set(self):
        return bool(self.encrypted_password)

    @property
    def usable(self):
        """Whether a send should be attempted over SMTP.

        Needs a host and the active flag. Credentials are not required: local
        relays commonly take none, and some authenticate on the from address
        alone, so demanding a password here would reject working configurations.
        """
        return bool(self.is_active and self.host)
