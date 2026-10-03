from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Company, User, PLAN_CHOICES
from regional.countries.registry import COUNTRY_PACKS
from regional.models import CompanyCountryProfile


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = [
            'id', 'name', 'country', 'country_code', 'address', 'email', 'phone', 'plan',
            'is_active', 'payroll_configured', 'employee_limit',
            'logo', 'logo_url',
            'created_at',
        ]
        read_only_fields = ['is_active', 'payroll_configured', 'country_code']
        extra_kwargs = {'logo': {'write_only': True, 'required': False}}

    country_code = serializers.SerializerMethodField()

    def get_country_code(self, obj):
        profile = getattr(obj, 'country_profile', None)
        return profile.country_code if profile else ''

    logo_url = serializers.SerializerMethodField()

    def get_logo_url(self, obj):
        if not obj.logo:
            return None
        request = self.context.get('request')
        url = obj.logo.url
        if request is not None:
            return request.build_absolute_uri(url)
        return url


class RegisterSerializer(serializers.Serializer):
    """
    Registers a new company + its first (owner) user in one step.
    The company starts inactive until the activation link is used.
    """
    company_name = serializers.CharField(max_length=255)
    country = serializers.ChoiceField(choices=[(code, pack.name) for code, pack in COUNTRY_PACKS.items()])
    company_email = serializers.EmailField()

    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])

    def validate_company_email(self, value):
        if Company.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('A company with this email already exists.')
        return value

    def validate_country(self, value):
        if value not in COUNTRY_PACKS:
            raise serializers.ValidationError('Unsupported country.')
        return value

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('This username is already taken.')
        return value

    def create(self, validated_data):
        country_code = validated_data['country']
        country_pack = COUNTRY_PACKS[country_code]
        company = Company.objects.create(
            name=validated_data['company_name'],
            country=country_pack.name,
            email=validated_data['company_email'],
        )
        CompanyCountryProfile.objects.create(
            company=company,
            country_code=country_code,
            currency_code=country_pack.currency,
            timezone=country_pack.timezone,
            payroll_frequency=country_pack.payroll_frequencies[0],
        )
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            company=company,
            role='owner',
            is_active=True,  # the User account is usable immediately;
                              # it's the Company that needs activation
                              # before core features unlock.
        )
        from .platform_models import Subscription
        from .billing import start_trial
        subscription = Subscription.objects.create(company=company, status='trial', monthly_price=0, currency='USD')
        start_trial(subscription, 14)
        return {'company': company, 'user': user}


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(username=attrs['username'], password=attrs['password'])
        if not user:
            raise serializers.ValidationError('Invalid username or password.')
        attrs['user'] = user
        return attrs


class UserSerializer(serializers.ModelSerializer):
    company = CompanySerializer(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'role', 'managed_department', 'company', 'is_staff', 'is_superuser']


STAFF_ROLE_CHOICES = ['admin', 'hr', 'finance', 'department_manager', 'employee']


class StaffUserSerializer(serializers.ModelSerializer):
    """Read shape for listing a company's staff/team accounts."""
    employee_name = serializers.CharField(source='employee_profile.full_name', read_only=True, default=None)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'role', 'managed_department', 'is_active', 'employee_name']


class StaffUserCreateSerializer(serializers.Serializer):
    """
    Creates a new user account under the CURRENT company only - there
    is no public/independent signup for staff. Only an owner/admin can
    call this (enforced by the view's permission_classes).
    """
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    role = serializers.ChoiceField(choices=STAFF_ROLE_CHOICES)

    # Required only when role == 'department_manager'
    managed_department = serializers.CharField(max_length=150, required=False, allow_blank=True)

    # Required only when role == 'employee' - links the login to an
    # existing Employee record so self-service scoping works.
    employee_id = serializers.IntegerField(required=False)

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('This username is already taken.')
        return value

    def validate(self, attrs):
        company = self.context['request'].user.company
        from .billing import user_limit
        limit = user_limit(company)
        if limit is not None and company.users.filter(is_active=True).count() >= limit:
            raise serializers.ValidationError({'detail': f"Your '{company.plan}' plan allows up to {limit} active user accounts. Upgrade your plan to add more."})

        if attrs['role'] == 'department_manager' and not attrs.get('managed_department'):
            raise serializers.ValidationError(
                {'managed_department': 'Required when role is department_manager.'}
            )

        if attrs['role'] == 'employee':
            employee_id = attrs.get('employee_id')
            if not employee_id:
                raise serializers.ValidationError(
                    {'employee_id': 'Required when role is employee, to link the login to their profile.'}
                )
            from employees.models import Employee
            try:
                employee = Employee.objects.get(id=employee_id, company=company)
            except Employee.DoesNotExist:
                raise serializers.ValidationError({'employee_id': 'No such employee in your company.'})
            if hasattr(employee, 'user') and employee.user is not None:
                raise serializers.ValidationError({'employee_id': 'This employee already has a login.'})
            attrs['_employee'] = employee

        return attrs

    def create(self, validated_data):
        company = self.context['request'].user.company
        employee = validated_data.pop('_employee', None)
        validated_data.pop('employee_id', None)

        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            company=company,
            role=validated_data['role'],
            managed_department=validated_data.get('managed_department', ''),
            is_active=True,
        )
        if employee:
            employee.user = user
            employee.save(update_fields=['user'])
        return user

class PlatformCompanySerializer(serializers.ModelSerializer):
    employee_limit = serializers.ReadOnlyField()
    user_count = serializers.IntegerField(read_only=True, default=0)
    employee_count = serializers.IntegerField(read_only=True, default=0)
    owner_name = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = [
            'id', 'name', 'country', 'email', 'phone', 'plan', 'is_active',
            'payroll_configured', 'employee_limit', 'user_count', 'employee_count',
            'owner_name', 'created_at', 'updated_at',
        ]

    def get_owner_name(self, obj):
        owner = obj.users.filter(role='owner').order_by('id').first()
        return owner.username if owner else None


class PlatformCompanyCreateSerializer(serializers.Serializer):
    company_name = serializers.CharField(max_length=255)
    country = serializers.ChoiceField(choices=[(code, pack.name) for code, pack in COUNTRY_PACKS.items()])
    company_email = serializers.EmailField()
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    plan = serializers.ChoiceField(choices=[x[0] for x in PLAN_CHOICES])
    owner_username = serializers.CharField(max_length=150)
    owner_email = serializers.EmailField()
    owner_password = serializers.CharField(write_only=True, validators=[validate_password])
    activate_immediately = serializers.BooleanField(default=False)
    payroll_configured = serializers.BooleanField(default=False)

    def validate(self, attrs):
        if Company.objects.filter(email__iexact=attrs['company_email']).exists():
            raise serializers.ValidationError({'company_email': 'A company with this email already exists.'})
        if User.objects.filter(username__iexact=attrs['owner_username']).exists():
            raise serializers.ValidationError({'owner_username': 'This username is already taken.'})
        return attrs

    def create(self, validated_data):
        from django.db import transaction
        from django.conf import settings
        with transaction.atomic():
            company = Company.objects.create(
                name=validated_data['company_name'],
                country=validated_data.get('country', ''),
                email=validated_data['company_email'],
                phone=validated_data.get('phone', ''),
                plan=validated_data['plan'],
                is_active=validated_data.get('activate_immediately', False),
                payroll_configured=validated_data.get('payroll_configured', False),
            )
            owner = User.objects.create_user(
                username=validated_data['owner_username'],
                email=validated_data['owner_email'],
                password=validated_data['owner_password'],
                company=company,
                role='owner',
                is_active=True,
            )
        return {
            'company': company,
            'owner': owner,
            'activation_url': f"{settings.FRONTEND_URL}/activate/{company.id}/{company.activation_token}",
        }


class PlatformUserSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='company.name', read_only=True, default=None)
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'role', 'is_active', 'is_staff', 'is_superuser', 'company', 'company_name', 'date_joined']
