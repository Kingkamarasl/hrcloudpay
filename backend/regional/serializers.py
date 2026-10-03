from rest_framework import serializers
from django.utils import timezone
from .models import CompanyCountryProfile, StatutoryFilingRule, StatutoryFiling, StatutoryCompliancePack, StatutoryFilingPayment
from .countries.registry import COUNTRY_PACKS


class CountryOptionSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()
    currency = serializers.CharField()
    timezone = serializers.CharField()
    payroll_frequencies = serializers.ListField(child=serializers.CharField())
    employee_identifiers = serializers.ListField(child=serializers.CharField())
    compliance_domains = serializers.ListField(child=serializers.CharField())
    integration_tags = serializers.ListField(child=serializers.CharField())
    employee_fields = serializers.ListField(child=serializers.DictField())
    # Sent so the compliance view can state the language fact rather than
    # hardcode a note per country. ISO 639 codes, not display strings - the
    # frontend holds the English names, and
    # `regional.tests_country_registry.LanguageDataTest` fails if a pack
    # introduces a code the frontend cannot name, so a language can never
    # surface as a bare two-letter code in the UI.
    official_languages = serializers.ListField(child=serializers.CharField())
    localized_name = serializers.CharField()


class CompanyCountryProfileSerializer(serializers.ModelSerializer):
    country_name = serializers.SerializerMethodField()
    available_payroll_frequencies = serializers.SerializerMethodField()

    class Meta:
        model = CompanyCountryProfile
        fields = [
            'id', 'company', 'country_code', 'country_name', 'currency_code',
            'payroll_frequency', 'available_payroll_frequencies', 'timezone',
            'onboarding_completed', 'created_at', 'updated_at',
        ]
        read_only_fields = ['company', 'country_name', 'available_payroll_frequencies', 'currency_code', 'timezone']

    def get_country_name(self, obj):
        pack = COUNTRY_PACKS.get(obj.country_code)
        return pack.name if pack else obj.country_code

    def get_available_payroll_frequencies(self, obj):
        pack = COUNTRY_PACKS.get(obj.country_code)
        return list(pack.payroll_frequencies) if pack else []

    def validate_payroll_frequency(self, value):
        country_code = self.instance.country_code if self.instance else self.initial_data.get('country_code')
        pack = COUNTRY_PACKS.get(country_code) if country_code else None
        if country_code and pack is None:
            raise serializers.ValidationError('Unknown country code.')
        if pack and value not in pack.payroll_frequencies:
            raise serializers.ValidationError('Payroll frequency is not available for this country pack.')
        return value


class StatutoryFilingRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = StatutoryFilingRule
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']


class StatutoryFilingSerializer(serializers.ModelSerializer):
    rule_code = serializers.CharField(source='rule.code', read_only=True)
    rule_name = serializers.CharField(source='rule.name', read_only=True)
    authority = serializers.CharField(source='rule.authority', read_only=True)
    filing_type = serializers.CharField(source='rule.filing_type', read_only=True)
    source_reference = serializers.URLField(source='rule.source_reference', read_only=True)
    is_overdue = serializers.SerializerMethodField()
    payment_record = serializers.SerializerMethodField()

    class Meta:
        model = StatutoryFiling
        fields = [
            'id', 'rule_code', 'rule_name', 'authority', 'filing_type',
            'period_start', 'period_end', 'due_date', 'status', 'amount',
            'reference', 'notes', 'filed_at', 'source_reference', 'payroll_run', 'reviewed_at', 'reviewed_by', 'approved_at', 'approved_by', 'submitted_at', 'submitted_by', 'submission_reference', 'closed_at', 'payment_record', 'is_overdue',
        ]
        read_only_fields = ['id', 'rule_code', 'rule_name', 'authority', 'filing_type', 'due_date', 'status', 'filed_at', 'source_reference', 'reviewed_at', 'reviewed_by', 'approved_at', 'approved_by', 'submitted_at', 'submitted_by', 'closed_at', 'payment_record', 'is_overdue']

    def get_is_overdue(self, obj):
        return obj.due_date < timezone.localdate() and obj.status not in ('submitted', 'closed', 'filed')

    def get_payment_record(self, obj):
        payment = getattr(obj, 'payment_record', None)
        if payment is None and hasattr(obj, 'payments'):
            try:
                payment = obj.payments.filter(status='paid').order_by('-payment_date', '-created_at').first()
            except Exception:
                payment = None
        if not payment:
            return None
        return StatutoryFilingPaymentSerializer(payment).data

class StatutoryCompliancePackSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='company.name', read_only=True)
    payroll_status = serializers.CharField(source='payroll_run.status', read_only=True)

    class Meta:
        model = StatutoryCompliancePack
        fields = [
            'id', 'company_name', 'country_code', 'period_start', 'period_end',
            'payroll_run', 'payroll_status', 'status', 'filing_count', 'report_count',
            'generated_at', 'updated_at', 'submitted_at', 'notes',
        ]
        read_only_fields = fields


class StatutoryFilingPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = StatutoryFilingPayment
        fields = ['id','filing','amount','payment_date','method','transaction_reference','status','receipt_reference','notes','recorded_by','created_at','updated_at']
        read_only_fields = ['id','filing','status','recorded_by','created_at','updated_at']
