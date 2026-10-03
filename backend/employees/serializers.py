from django.db.models import Q
from rest_framework import serializers
from .models import Department, Contract, Employee, EmployeeAllowance, EmployeeDeduction, WarningLetter, EmployeePersonalDetails, EmergencyContact, EmploymentEvent, EmployeeDocument, RequiredDocumentRule, EmployeeStatutoryProfile, HRRequest

class DepartmentSerializer(serializers.ModelSerializer):
    employee_count = serializers.IntegerField(read_only=True)
    class Meta:
        model = Department
        fields = ['id','name','description','is_active','employee_count','created_at']

class EmployeeAllowanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeAllowance
        fields = ['id','employee','name','amount','is_percentage_of_base']

class EmployeeDeductionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeDeduction
        fields = ['id','employee','name','amount','is_percentage_of_base']

class ContractSerializer(serializers.ModelSerializer):
    status = serializers.ReadOnlyField()

    def validate(self, attrs):
        employee = attrs.get('employee') or getattr(self.instance, 'employee', None)
        start_date = attrs.get('start_date') or getattr(self.instance, 'start_date', None)
        end_date = attrs.get('end_date', getattr(self.instance, 'end_date', None))

        if end_date and start_date and end_date < start_date:
            raise serializers.ValidationError({'end_date': 'End date cannot be before the start date.'})

        request = self.context.get('request')
        if employee and request and getattr(request.user, 'company_id', None) != employee.company_id:
            raise serializers.ValidationError({'employee': 'Employee not found in your company.'})

        # One employee cannot have two terms covering the same day. This keeps
        # current-contract and payroll calculations deterministic.
        if employee and start_date:
            overlapping = Contract.objects.filter(employee=employee)
            if self.instance:
                overlapping = overlapping.exclude(pk=self.instance.pk)
            if end_date:
                overlapping = overlapping.filter(start_date__lte=end_date)
            overlapping = overlapping.filter(
                Q(end_date__isnull=True) | Q(end_date__gte=start_date)
            )
            if overlapping.exists():
                raise serializers.ValidationError({
                    'start_date': 'This period overlaps an existing contract. End or adjust the existing contract first.'
                })
        return attrs

    class Meta:
        model = Contract
        fields = ['id','employee','contract_type','start_date','end_date','status','document','notes']

class WarningLetterSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)
    issued_by_name = serializers.CharField(source='issued_by.get_full_name', read_only=True)
    class Meta:
        model = WarningLetter
        fields = ['id','employee','employee_name','issued_by','issued_by_name','warning_level','subject','incident_date','issued_date','details','employee_response','acknowledged','document','created_at']
        read_only_fields = ['issued_by']

class EmployeeSerializer(serializers.ModelSerializer):
    allowances = EmployeeAllowanceSerializer(many=True, read_only=True)
    deductions = EmployeeDeductionSerializer(many=True, read_only=True)
    warning_letters = WarningLetterSerializer(many=True, read_only=True)
    full_name = serializers.ReadOnlyField()
    effective_department = serializers.ReadOnlyField()
    profile_photo_url = serializers.SerializerMethodField()
    contract_status = serializers.SerializerMethodField()
    contract_start_date = serializers.SerializerMethodField()
    contract_end_date = serializers.SerializerMethodField()
    attendance_count = serializers.SerializerMethodField()
    leave_request_count = serializers.SerializerMethodField()
    break_request_count = serializers.SerializerMethodField()
    warning_letter_count = serializers.SerializerMethodField()
    emergency_contact_count = serializers.SerializerMethodField()
    employment_event_count = serializers.SerializerMethodField()
    class Meta:
        model = Employee
        fields = ['id','employee_code','id_card_no','profile_photo','profile_photo_url','first_name','last_name','full_name','email','phone','job_title','department','department_obj','effective_department','pay_point','bank_account_number','base_salary','hire_date','employment_status','employment_category','contract_status','contract_start_date','contract_end_date','attendance_count','leave_request_count','break_request_count','warning_letter_count','emergency_contact_count','employment_event_count','allowances','deductions','warning_letters','created_at']
        read_only_fields = ['employee_code', 'profile_photo_url']
        extra_kwargs = {'profile_photo': {'write_only': True, 'required': False}}
    def get_profile_photo_url(self, obj):
        if not obj.profile_photo:
            return None
        request = self.context.get('request')
        url = obj.profile_photo.url
        if request is not None:
            return request.build_absolute_uri(url)
        return url
    def get_contract_status(self, obj):
        c = obj.current_contract
        return c.status if c else 'none'
    def get_contract_start_date(self, obj):
        c = obj.current_contract
        return c.start_date if c else None
    def get_contract_end_date(self, obj):
        c = obj.current_contract
        return c.end_date if c else None
    def get_attendance_count(self, obj): return obj.attendance_records.count()
    def get_leave_request_count(self, obj): return obj.leave_requests.count()
    def get_break_request_count(self, obj): return obj.break_requests.count()
    def get_warning_letter_count(self, obj): return obj.warning_letters.count()
    def get_emergency_contact_count(self, obj): return obj.emergency_contacts.count()
    def get_employment_event_count(self, obj): return obj.employment_events.count()
    def create(self, validated_data):
        from .models import Employee
        company = self.context['request'].user.company
        validated_data['company'] = company
        if validated_data.get('department_obj') and validated_data['department_obj'].company_id != company.id:
            raise serializers.ValidationError({'department_obj': 'Department does not belong to this company.'})
        if validated_data.get('department_obj'):
            validated_data['department'] = validated_data['department_obj'].name
        # System-assigned ID: CA/ST/LT + 4 random digits (never client-supplied)
        validated_data.pop('employee_code', None)
        category = validated_data.get('employment_category') or 'long_time'
        validated_data['employment_category'] = category
        validated_data['employee_code'] = Employee.allocate_employee_code(company, category)
        return super().create(validated_data)
    def update(self, instance, validated_data):
        if validated_data.get('department_obj'):
            if validated_data['department_obj'].company_id != instance.company_id:
                raise serializers.ValidationError({'department_obj':'Department does not belong to this company.'})
            validated_data['department'] = validated_data['department_obj'].name
        return super().update(instance, validated_data)


class EmployeeStatutoryProfileSerializer(serializers.ModelSerializer):
    country_code = serializers.SerializerMethodField()
    country_name = serializers.SerializerMethodField()
    available_fields = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeStatutoryProfile
        fields = ['id','employee','country_code','country_name','available_fields','identifiers','tax_region','social_security_region','bank_name','bank_branch','account_name','mobile_money_provider','mobile_money_number','notes','created_at','updated_at']
        read_only_fields = ['employee','country_code','country_name','available_fields','created_at','updated_at']

    def _pack(self, obj):
        from regional.countries.registry import get_country_pack
        profile = getattr(obj.employee.company, 'country_profile', None)
        if not profile:
            raise serializers.ValidationError('Company country profile is not configured.')
        return get_country_pack(profile.country_code)

    def get_country_code(self, obj): return self._pack(obj).code
    def get_country_name(self, obj): return self._pack(obj).name
    def get_available_fields(self, obj):
        return [{'key': k, 'label': label, 'required': required} for k,label,required in self._pack(obj).employee_fields]

    def validate_identifiers(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Identifiers must be an object.')
        from regional.countries.registry import get_country_pack
        employee = self.instance.employee if self.instance else self.context['request'].user.company.employees.filter(id=self.initial_data.get('employee')).first()
        if not employee or employee.company_id != self.context['request'].user.company_id:
            raise serializers.ValidationError('Employee does not belong to your company.')
        allowed = {x[0] for x in get_country_pack(employee.company.country_profile.country_code).employee_fields}
        unknown = set(value) - allowed
        if unknown:
            raise serializers.ValidationError(f'Unsupported statutory fields: {", ".join(sorted(unknown))}')
        return value


class EmployeePersonalDetailsSerializer(serializers.ModelSerializer):
    def validate_date_of_birth(self, value):
        from django.utils import timezone
        if value and value > timezone.localdate():
            raise serializers.ValidationError('Date of birth cannot be in the future.')
        return value

    class Meta:
        model = EmployeePersonalDetails
        fields = ['id','employee','date_of_birth','gender','marital_status','nationality','address_line_1','address_line_2','city','state_region','postal_code','country','notes','created_at','updated_at']
        read_only_fields = ['employee','created_at','updated_at']


class EmergencyContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmergencyContact
        fields = ['id','employee','name','relationship','phone','email','address','is_primary','created_at','updated_at']
        read_only_fields = ['employee','created_at','updated_at']


class EmploymentEventSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    event_type_label = serializers.CharField(source='get_event_type_display', read_only=True)
    class Meta:
        model = EmploymentEvent
        fields = ['id','employee','event_type','event_type_label','effective_date','title','description','created_by','created_by_name','created_at']
        read_only_fields = ['employee','created_by','created_at']


class EmployeeDocumentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source='uploaded_by.get_full_name', read_only=True)
    document_type_label = serializers.CharField(source='get_document_type_display', read_only=True)
    def validate(self, attrs):
        if attrs.get('issue_date') and attrs.get('expiry_date') and attrs['expiry_date'] < attrs['issue_date']:
            raise serializers.ValidationError({'expiry_date':'Expiry date cannot be before issue date.'})
        return attrs
    class Meta:
        model = EmployeeDocument
        fields = ['id','employee','document_type','document_type_label','title','document','issue_date','expiry_date','notes','uploaded_by','uploaded_by_name','created_at']
        read_only_fields = ['employee','uploaded_by','created_at']


class RequiredDocumentRuleSerializer(serializers.ModelSerializer):
    document_type_label = serializers.CharField(source='get_document_type_display', read_only=True)
    contract_type_label = serializers.CharField(source='get_contract_type_display', read_only=True)
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)

    class Meta:
        model = RequiredDocumentRule
        fields = ['id','name','document_type','document_type_label','contract_type','contract_type_label','employee','employee_name','warning_days','is_active','created_at']
        read_only_fields = ['created_at']

    def validate(self, attrs):
        request = self.context.get('request')
        employee = attrs.get('employee')
        if employee and request and employee.company_id != request.user.company_id:
            raise serializers.ValidationError({'employee':'Employee does not belong to this company.'})
        warning_days = attrs.get('warning_days', getattr(self.instance, 'warning_days', 30))
        if warning_days > 365:
            raise serializers.ValidationError({'warning_days':'Warning window cannot exceed 365 days.'})
        return attrs

class HRRequestSerializer(serializers.ModelSerializer):
    requested_by_name = serializers.CharField(source='requested_by.get_full_name', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.get_full_name', read_only=True)
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)

    class Meta:
        model = HRRequest
        fields = ['id','employee','employee_name','request_type','status','payload','requested_by','requested_by_name','approved_by','approved_by_name','comments','created_at','updated_at']
        read_only_fields = ['status', 'approved_by', 'approved_by_name']
