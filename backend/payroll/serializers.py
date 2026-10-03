from decimal import Decimal

from rest_framework import serializers

from .models import PayrollConfig, PayrollRun, Payslip, StatutoryContribution, TaxBracket


class TaxBracketSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxBracket
        fields = ['id', 'min_amount', 'max_amount', 'rate']

    def validate(self, attrs):
        minimum = attrs.get('min_amount', getattr(self.instance, 'min_amount', None))
        maximum = attrs.get('max_amount', getattr(self.instance, 'max_amount', None))
        rate = attrs.get('rate', getattr(self.instance, 'rate', None))
        if minimum is not None and minimum < 0:
            raise serializers.ValidationError({'min_amount': 'Minimum amount cannot be negative.'})
        if maximum is not None and maximum <= minimum:
            raise serializers.ValidationError({'max_amount': 'Maximum amount must be greater than minimum amount.'})
        if rate is not None and not Decimal('0') <= rate <= Decimal('100'):
            raise serializers.ValidationError({'rate': 'Tax rate must be between 0 and 100 percent.'})
        return attrs


class StatutoryContributionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StatutoryContribution
        fields = ['id', 'name', 'is_percentage', 'employee_rate', 'employer_rate']

    def validate(self, attrs):
        for field in ('employee_rate', 'employer_rate'):
            value = attrs.get(field, getattr(self.instance, field, Decimal('0')))
            if value < 0 or (attrs.get('is_percentage', getattr(self.instance, 'is_percentage', True)) and value > 100):
                raise serializers.ValidationError({field: 'Rate must be non-negative and cannot exceed 100 percent.'})
        return attrs


class PayrollConfigSerializer(serializers.ModelSerializer):
    """
    Serializes the full onboarding form: currency + pay frequency +
    nested tax brackets + nested statutory contributions, all writable
    in a single request so the onboarding form can submit once.
    """
    tax_brackets = TaxBracketSerializer(many=True)
    contributions = StatutoryContributionSerializer(many=True)

    class Meta:
        model = PayrollConfig
        fields = [
            'id', 'currency', 'pay_frequency', 'tax_calculation_enabled',
            'tax_brackets', 'contributions', 'updated_at',
        ]

    def create(self, validated_data):
        tax_brackets_data = validated_data.pop('tax_brackets', [])
        contributions_data = validated_data.pop('contributions', [])
        company = self.context['request'].user.company

        brackets = sorted(tax_brackets_data, key=lambda item: item['min_amount'])
        for current, following in zip(brackets, brackets[1:]):
            if current.get('max_amount') is None:
                raise serializers.ValidationError({'tax_brackets': 'Only the final tax bracket may be open-ended.'})
            if current['max_amount'] != following['min_amount']:
                raise serializers.ValidationError({'tax_brackets': 'Tax brackets must be contiguous with no gaps or overlaps.'})
        if brackets and brackets[-1].get('max_amount') is not None:
            raise serializers.ValidationError({'tax_brackets': 'The final tax bracket must be open-ended (leave maximum amount blank).'} )

        config, _ = PayrollConfig.objects.update_or_create(
            company=company, defaults=validated_data,
        )
        config.tax_brackets.all().delete()
        config.contributions.all().delete()
        for bracket in tax_brackets_data:
            TaxBracket.objects.create(payroll_config=config, **bracket)
        for contribution in contributions_data:
            StatutoryContribution.objects.create(payroll_config=config, **contribution)

        company.payroll_configured = True
        company.save(update_fields=['payroll_configured'])
        return config

    def update(self, instance, validated_data):
        return self.create(validated_data)


class PayslipSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)
    employee_id_card_no = serializers.CharField(source='employee.id_card_no', read_only=True)
    employee_code = serializers.CharField(source='employee.employee_code', read_only=True)
    payroll_period_start = serializers.DateField(source='payroll_run.period_start', read_only=True)
    payroll_period_end = serializers.DateField(source='payroll_run.period_end', read_only=True)

    class Meta:
        model = Payslip
        fields = [
            'id', 'payroll_run', 'payroll_period_start', 'payroll_period_end', 'employee', 'employee_name',
            'employee_id_card_no', 'employee_code', 'base_salary',
            'total_allowances', 'gross_salary', 'tax_amount', 'total_contributions',
            'total_other_deductions', 'net_salary', 'breakdown',
            'payment_method', 'payment_reference', 'paid_at', 'generated_at',
        ]
        read_only_fields = [
            'base_salary', 'total_allowances', 'gross_salary', 'tax_amount',
            'total_contributions', 'total_other_deductions', 'net_salary', 'breakdown',
        ]


class PayrollRunSerializer(serializers.ModelSerializer):
    payslips = PayslipSerializer(many=True, read_only=True)
    compliance_gaps = serializers.SerializerMethodField()

    class Meta:
        model = PayrollRun
        fields = ['id', 'period_start', 'period_end', 'status', 'run_date', 'approved_at', 'approved_by', 'payslips', 'compliance_gaps']
        read_only_fields = ['status', 'run_date', 'approved_at', 'approved_by', 'payslips', 'compliance_gaps']

    def get_compliance_gaps(self, run):
        """Surfaced on the run so the UI can warn *before* approval is attempted.

        Derived from the payslips, so it is always the truth about what was
        actually calculated rather than a flag that could be stale.
        """
        from .services import collect_compliance_gaps
        return collect_compliance_gaps(run)

    def validate(self, attrs):
        start = attrs.get('period_start', getattr(self.instance, 'period_start', None))
        end = attrs.get('period_end', getattr(self.instance, 'period_end', None))
        if start and end and end < start:
            raise serializers.ValidationError({'period_end': 'Period end must be on or after period start.'})
        company = self.context['request'].user.company
        existing = PayrollRun.objects.filter(company=company, period_start=start, period_end=end)
        if self.instance:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError('A payroll run already exists for this exact period.')
        return attrs
