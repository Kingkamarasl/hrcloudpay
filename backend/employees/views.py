from django.db.models import Q
import csv
import io
from rest_framework import viewsets, serializers
from rest_framework.views import APIView
from django.db import transaction
from datetime import timedelta
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from accounts.permissions import CanManageHR, IsCompanyActive, IsCompanyMember
from accounts.audit import audit, changed_fields, snapshot_fields
from security.step_up import mfa_enrolled, mfa_is_fresh as fresh_mfa
from .models import Department, Contract, Employee, EmployeeAllowance, EmployeeDeduction, WarningLetter, EmployeePersonalDetails, EmergencyContact, EmploymentEvent, EmployeeDocument, RequiredDocumentRule, EmployeeStatutoryProfile, HRRequest
from .serializers import DepartmentSerializer, ContractSerializer, EmployeeAllowanceSerializer, EmployeeDeductionSerializer, EmployeeSerializer, WarningLetterSerializer, EmployeePersonalDetailsSerializer, EmergencyContactSerializer, EmploymentEventSerializer, EmployeeDocumentSerializer, RequiredDocumentRuleSerializer, EmployeeStatutoryProfileSerializer, HRRequestSerializer
from .services import EmployeeService, ContractService

class ScopedMixin:
    def scope(self, qs):
        user = self.request.user
        if user.role == 'employee' and user.employee_id is not None:
            return qs.filter(employee_id=user.employee_id) if hasattr(qs.model, 'employee_id') else qs.filter(id=user.employee_id)
        if user.role == 'department_manager':
            dept = user.managed_department
            return qs.filter(employee__department=dept) if hasattr(qs.model, 'employee_id') else qs.filter(department__name=dept)
        return qs

class HRRequestViewSet(viewsets.ModelViewSet):
    """Management of HR change requests (Salary, Position, Contract).

    A salary change is a money and privilege action, so `approve` re-confirms
    MFA via `RequiresFreshMfa`; `reject` is not gated because refusing a change
    cannot move money.
    """
    serializer_class = HRRequestSerializer
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManageHR]

    def get_queryset(self):
        user = self.request.user
        qs = HRRequest.objects.filter(employee__company=user.company)
        if user.role == 'department_manager':
            # Managers only see requests they created or for their department
            return qs.filter(Q(requested_by=user) | Q(employee__department=user.managed_department))
        return qs

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        hr_request = self.get_object()
        if request.user.role == 'department_manager':
            return Response({'detail': 'Only HR or Owners can approve requests.'}, status=403)
        # Salary and position changes land in the employee record, so a live
        # session by itself is not sufficient authority.
        if not fresh_mfa(getattr(request, 'auth', None)):
            return Response({
                'detail': 'A fresh MFA code is required to approve this change.',
                'mfa_required': True,
                'enrollment_required': not mfa_enrolled(request.user),
            }, status=403)

        comments = request.data.get('comments', '')
        approved_req = EmployeeService.approve_hr_request(hr_request.id, request.user, comments)
        return Response(HRRequestSerializer(approved_req).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        hr_request = self.get_object()
        if request.user.role == 'department_manager':
            return Response({'detail': 'Only HR or Owners can reject requests.'}, status=403)

        comments = request.data.get('comments', '')
        rejected_req = EmployeeService.reject_hr_request(hr_request.id, request.user, comments)
        return Response(HRRequestSerializer(rejected_req).data)

class DepartmentViewSet(viewsets.ModelViewSet):
    serializer_class = DepartmentSerializer
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManageHR]
    def get_queryset(self):
        qs = Department.objects.filter(company=self.request.user.company).prefetch_related('employees')
        user = self.request.user
        if user.role == 'department_manager': qs = qs.filter(name=user.managed_department)
        elif user.role == 'employee' and user.employee_id is not None and user.employee_profile.department_obj_id:
            qs = qs.filter(id=user.employee_profile.department_obj_id)
        return qs


    def perform_create(self, serializer):
        obj = serializer.save(company=self.request.user.company)
        audit(self.request.user, 'create', f'Created department {obj.name}', obj.company, 'department', obj.id, request=self.request)
    def perform_update(self, serializer):
        instance=self.get_object(); before=snapshot_fields(instance, ['name','description','is_active']); obj=serializer.save(); changes=changed_fields(obj, ['name','description','is_active'], before=before)
        if changes: audit(self.request.user, 'update', f'Updated department {obj.name}', obj.company, 'department', obj.id, {'changes':changes}, request=self.request)
    def perform_destroy(self, instance):
        audit(self.request.user, 'delete', f'Deleted department {instance.name}', instance.company, 'department', instance.id, request=self.request); instance.delete()

class EmployeeViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeeSerializer
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManageHR]

    def get_permissions(self):
        # Self-service action: the view resolves the target employee from
        # request.user.employee_id and ignores any client-supplied id, so the
        # only requirement is a linked employee profile. CanManageHR would
        # otherwise reject exactly the employees this action exists for.
        if self.action == 'submit_self_request':
            from accounts.permissions import IsCompanyMember, IsCompanyActive
            from rest_framework.permissions import BasePermission

            class CanSubmitSelfRequest(BasePermission):
                def has_permission(self, request, view):
                    u = request.user
                    return bool(u and u.is_authenticated and u.employee_id is not None)

            return [IsCompanyMember(), IsCompanyActive(), CanSubmitSelfRequest()]
        # Finance needs read/search for OT, advances, payslip tools
        if self.action in ('list', 'retrieve', 'photo'):
            from accounts.permissions import IsCompanyMember, IsCompanyActive
            from rest_framework.permissions import BasePermission

            class CanReadEmployees(BasePermission):
                def has_permission(self, request, view):
                    u = request.user
                    if not u or not u.is_authenticated:
                        return False
                    if getattr(u, 'is_staff', False):
                        return True
                    return u.role in ('owner', 'admin', 'hr', 'finance', 'department_manager', 'employee')

            return [IsCompanyMember(), IsCompanyActive(), CanReadEmployees()]
        return super().get_permissions()
    def get_queryset(self):
        qs = Employee.objects.filter(company=self.request.user.company).select_related('department_obj').prefetch_related('contracts','warning_letters','attendance_records','leave_requests','break_requests','personal_details','emergency_contacts','employment_events','statutory_profile')
        user = self.request.user
        if user.role == 'employee' and user.employee_id is not None: qs = qs.filter(id=user.employee_id)
        elif user.role == 'department_manager': qs = qs.filter(department=user.managed_department)
        dept = self.request.query_params.get('department')
        if dept: qs = qs.filter(department__iexact=dept)
        status = self.request.query_params.get('employment_status')
        if status: qs = qs.filter(employment_status=status)
        # Search by ID number, employee code, name, email, phone
        q = (self.request.query_params.get('q') or self.request.query_params.get('search') or '').strip()
        if q:
            qs = qs.filter(
                Q(id_card_no__icontains=q)
                | Q(employee_code__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(email__icontains=q)
                | Q(phone__icontains=q)
            )
        id_exact = (self.request.query_params.get('id_card_no') or '').strip()
        if id_exact:
            qs = qs.filter(id_card_no__iexact=id_exact)
        code_exact = (self.request.query_params.get('employee_code') or '').strip()
        if code_exact:
            qs = qs.filter(employee_code__iexact=code_exact)
        return qs



    @action(detail=True, methods=['post', 'delete'], url_path='photo',
            parser_classes=[MultiPartParser, FormParser])
    def photo(self, request, pk=None):
        """Upload or remove profile photo. Multipart field: photo or profile_photo."""
        from rest_framework.response import Response
        from rest_framework import status as http_status
        employee = self.get_object()
        u = request.user
        is_self = u.role == 'employee' and u.employee_id == employee.id
        is_hr = u.role in ('owner', 'admin', 'hr') or getattr(u, 'is_staff', False)
        if not (is_self or is_hr):
            return Response({'detail': 'Only HR or the employee can change this photo.'}, status=403)
        if request.method == 'DELETE':
            if employee.profile_photo:
                employee.profile_photo.delete(save=False)
                employee.profile_photo = None
                employee.save(update_fields=['profile_photo'])
            return Response({'detail': 'Photo removed.', 'profile_photo_url': None})
        f = request.FILES.get('photo') or request.FILES.get('profile_photo')
        if not f:
            return Response({'detail': 'No file uploaded. Use field name "photo".'}, status=http_status.HTTP_400_BAD_REQUEST)
        name = (getattr(f, 'name', '') or '').lower()
        if not any(name.endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp')):
            return Response({'detail': 'Use a JPG, PNG, GIF, or WebP image.'}, status=http_status.HTTP_400_BAD_REQUEST)
        if getattr(f, 'size', 0) and f.size > 5 * 1024 * 1024:
            return Response({'detail': 'Image must be 5 MB or smaller.'}, status=http_status.HTTP_400_BAD_REQUEST)
        if employee.profile_photo:
            employee.profile_photo.delete(save=False)
        employee.profile_photo = f
        employee.save(update_fields=['profile_photo'])
        ser = self.get_serializer(employee)
        return Response({'detail': 'Photo updated.', 'profile_photo_url': ser.data.get('profile_photo_url')})

    def perform_create(self, serializer):
        company=self.request.user.company; limit=company.employee_limit
        from datetime import timedelta
        with transaction.atomic():
            locked_company = company.__class__.objects.select_for_update().get(pk=company.pk)
            if limit is not None and Employee.objects.filter(company=locked_company).count() >= limit:
                raise ValidationError(f"Your '{company.plan}' plan allows up to {limit} employees. Upgrade your plan to add more.")
            employee = serializer.save(company=locked_company)
        EmploymentEvent.objects.create(employee=employee, event_type='hired', effective_date=employee.hire_date or timezone.localdate(), title='Employee created', description='Employee record created.', created_by=self.request.user)
        audit(self.request.user, 'create', f'Created employee {employee.full_name}', company, 'employee', employee.id, request=self.request)

    def perform_update(self, serializer):
        instance = self.get_object()
        tracked = ['base_salary', 'employment_status', 'department', 'department_obj_id', 'job_title', 'id_card_no', 'email', 'phone']
        before = snapshot_fields(instance, tracked)
        employee = serializer.save()
        changes = changed_fields(employee, tracked, before=before)
        if changes:
            status_after = changes.get('employment_status', {}).get('after')
            if 'employment_status' in changes:
                before_status = changes.get('employment_status', {}).get('before')
                event_type = 'terminated' if status_after == 'terminated' else ('resigned' if status_after == 'resigned' else ('rehired' if status_after == 'active' and before_status in ('terminated','resigned') else 'status_change'))
                title = f'Employment status changed to {employee.get_employment_status_display()}'
            elif 'department_obj_id' in changes or 'department' in changes:
                event_type = 'transfer'; title = f'Department changed to {employee.effective_department or "Unassigned"}'
            elif 'job_title' in changes:
                event_type = 'promotion' if employee.job_title else 'job_change'; title = f'Position changed to {employee.job_title or "Unassigned"}'
            elif 'base_salary' in changes:
                event_type = 'salary_change'; title = 'Salary changed'
            else:
                event_type = 'note'; title = 'Employee record updated'
            EmploymentEvent.objects.create(employee=employee, event_type=event_type, effective_date=timezone.localdate(), title=title, description='Employee record change recorded automatically.', created_by=self.request.user)
            action = 'salary_change' if 'base_salary' in changes else ('termination' if status_after in ('terminated','resigned') else 'update')
            audit(self.request.user, action, f'Updated employee {employee.full_name}', employee.company, 'employee', employee.id, {'changes': changes}, request=self.request)

    def perform_destroy(self, instance):
        EmployeeService.delete_employee(instance, user=self.request.user)

    @action(detail=True, methods=['post'], url_path='salary-change')
    def salary_change(self, request, pk=None):
        employee=self.get_object(); new_salary=request.data.get('new_salary'); effective_date=request.data.get('effective_date'); reason=request.data.get('reason','Salary change')
        if new_salary is None: raise ValidationError({'new_salary':'New salary is required.'})

        if request.user.role == 'department_manager':
            payload = {'new_salary': new_salary, 'effective_date': effective_date, 'reason': reason}
            req = EmployeeService.submit_hr_request(employee, 'salary', payload, request.user)
            return Response(HRRequestSerializer(req).data, status=201)

        employee = EmployeeService.change_salary(employee, new_salary, effective_date, reason, user=request.user)
        return Response(EmployeeSerializer(employee, context={'request':request}).data)

    @action(detail=True, methods=['post'], url_path='position-change')
    def position_change(self, request, pk=None):
        employee=self.get_object(); new_title=request.data.get('job_title'); effective_date=request.data.get('effective_date'); reason=request.data.get('reason','Position change'); dept_id=request.data.get('department_obj')
        if not new_title: raise ValidationError({'job_title':'New job title is required.'})

        if request.user.role == 'department_manager':
            payload = {'job_title': new_title, 'department_obj': dept_id, 'effective_date': effective_date, 'reason': reason}
            req = EmployeeService.submit_hr_request(employee, 'position', payload, request.user)
            return Response(HRRequestSerializer(req).data, status=201)

        dept_obj = None
        if dept_id is not None:
            from .models import Department
            dept_obj = Department.objects.filter(id=dept_id, company=employee.company).first()
            if not dept_obj: raise ValidationError({'department_obj':'Department not found in your company.'})

        employee = EmployeeService.change_position(employee, new_title, dept_obj, effective_date, reason, user=request.user)
        return Response(EmployeeSerializer(employee, context={'request':request}).data)

    @action(detail=True, methods=['get'], url_path='360')
    def profile_360(self, request, pk=None):
        """Return the employee's complete HR 360 profile in one request."""
        employee = self.get_object()
        from attendance.serializers import AttendanceSerializer
        from leave.serializers import BreakRequestSerializer, LeaveRequestSerializer
        from payroll.serializers import PayslipSerializer

        contracts = employee.contracts.all()
        attendance = employee.attendance_records.all()[:30]
        leave_requests = employee.leave_requests.all()[:20]
        break_requests = employee.break_requests.all()[:20]
        payslips = employee.payslips.select_related('payroll_run').all()[:12]
        current_contract = employee.current_contract
        personal_details = getattr(employee, 'personal_details', None)
        emergency_contacts = employee.emergency_contacts.all()
        employment_events = employee.employment_events.select_related('created_by').all()[:50]
        documents = employee.documents.select_related('uploaded_by').all()[:50]
        statutory_profile = getattr(employee, 'statutory_profile', None)
        documents = employee.documents.select_related('uploaded_by').all()[:50] if (request.user.role in ('owner','admin','hr') or (request.user.role == 'employee' and request.user.employee_id == employee.id)) else []

        return Response({
            'employee': self.get_serializer(employee).data,
            'contracts': ContractSerializer(contracts, many=True, context={'request': request}).data,
            'attendance': AttendanceSerializer(attendance, many=True, context={'request': request}).data,
            'leave_requests': LeaveRequestSerializer(leave_requests, many=True, context={'request': request}).data,
            'break_requests': BreakRequestSerializer(break_requests, many=True, context={'request': request}).data,
            'payslips': PayslipSerializer(payslips, many=True, context={'request': request}).data,
            'current_contract_id': current_contract.id if current_contract else None,
            'personal_details': (EmployeePersonalDetailsSerializer(personal_details, context={'request': request}).data if personal_details and (request.user.role in ('owner','admin','hr') or (request.user.role == 'employee' and request.user.employee_id == employee.id)) else None),
            'emergency_contacts': (EmergencyContactSerializer(emergency_contacts, many=True, context={'request': request}).data if (request.user.role in ('owner','admin','hr') or (request.user.role == 'employee' and request.user.employee_id == employee.id)) else []),
            'employment_events': EmploymentEventSerializer(employment_events, many=True, context={'request': request}).data,
            'documents': EmployeeDocumentSerializer(documents, many=True, context={'request': request}).data,
            'statutory_profile': (EmployeeStatutoryProfileSerializer(statutory_profile, context={'request': request}).data if statutory_profile and (request.user.role in ('owner','admin','hr') or (request.user.role == 'employee' and request.user.employee_id == employee.id)) else None),
            'statutory_fields': ([{'key': k, 'label': label, 'required': required} for k,label,required in __import__('regional.countries.registry', fromlist=['get_country_pack']).get_country_pack(employee.company.country_profile.country_code).employee_fields] if getattr(employee.company, 'country_profile', None) else []),
        })

    @action(detail=False, methods=['post'], url_path='import-csv', parser_classes=[MultiPartParser, FormParser])
    def import_csv(self, request):
        """Bulk import employees from a CSV file."""
        if request.user.role not in ('owner', 'admin', 'hr'):
            return Response({'detail': 'Insufficient permissions for importing employees.'}, status=403)

        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'detail': 'No file uploaded.'}, status=400)

        if not file_obj.name.endswith('.csv'):
            return Response({'detail': 'Please upload a CSV file.'}, status=400)

        try:
            decoded_file = file_obj.read().decode('utf-8').splitlines()
            reader = csv.DictReader(decoded_file)
            
            success_count = 0
            failures = []

            with transaction.atomic():
                for i, row in enumerate(reader, start=1):
                    try:
                        # Basic validation
                        if not row.get('first_name') or not row.get('last_name') or not row.get('email'):
                            raise ValidationError(f"Row {i}: Missing required fields (first_name, last_name, email).")

                        # Create employee using serializer to maintain validation logic
                        serializer = EmployeeSerializer(data={
                            'first_name': row.get('first_name'),
                            'last_name': row.get('last_name'),
                            'email': row.get('email'),
                            'phone': row.get('phone', ''),
                            'job_title': row.get('job_title', ''),
                            'department_obj': row.get('department_obj'), # Note: may need mapping if name is provided
                            'base_salary': row.get('base_salary'),
                            'hire_date': row.get('hire_date'),
                            'employment_status': row.get('employment_status', 'active'),
                            'employment_category': row.get('employment_category', 'long_time'),
                        }, context={'request': request})

                        if serializer.is_valid():
                            serializer.save(company=request.user.company)
                            success_count += 1
                        else:
                            failures.append({'row': i, 'errors': serializer.errors})

                    except Exception as e:
                        failures.append({'row': i, 'error': str(e)})

            return Response({
                'imported': success_count,
                'failed': len(failures),
                'failures': failures
            }, status=201 if success_count > 0 else 400)

        except Exception as e:
            return Response({'detail': f'Critical error parsing CSV: {str(e)}'}, status=400)

    @action(detail=False, methods=['post'], url_path='bulk-salary-update')
    def bulk_salary_update(self, request):
        """Update base salary for multiple employees in one go."""
        if request.user.role not in ('owner', 'admin', 'hr'):
            return Response({'detail': 'Insufficient permissions for bulk salary updates.'}, status=403)

        employee_ids = request.data.get('employees', [])
        new_salary = request.data.get('new_salary')
        effective_date = request.data.get('effective_date')
        reason = request.data.get('reason', 'Bulk salary update')

        if not employee_ids or new_salary is None:
            raise ValidationError({'detail': 'Both "employees" (list) and "new_salary" are required.'})

        results = {'success': [], 'failure': []}
        with transaction.atomic():
            employees = Employee.objects.filter(id__in=employee_ids, company=request.user.company)
            for emp in employees:
                try:
                    # Inner atomic() acts as a savepoint, so one failed employee
                    # does not poison the outer transaction for the rest.
                    with transaction.atomic():
                        EmployeeService.change_salary(emp, new_salary, effective_date, reason, user=request.user)
                    results['success'].append(emp.id)
                except Exception as e:
                    results['failure'].append({'id': emp.id, 'error': str(e)})

        # Report ids that were requested but did not resolve within the company.
        found = set(results['success']) | {f['id'] for f in results['failure']}
        for missing_id in [i for i in employee_ids if i not in found]:
            results['failure'].append({'id': missing_id, 'error': 'Employee not found in your company.'})

        return Response(results)

    @action(detail=False, methods=['post'], url_path='bulk-status-update')
    def bulk_status_update(self, request):
        """Update employment status for multiple employees."""
        if request.user.role not in ('owner', 'admin', 'hr'):
            return Response({'detail': 'Insufficient permissions for bulk status updates.'}, status=403)

        employee_ids = request.data.get('employees', [])
        new_status = request.data.get('new_status')
        reason = request.data.get('reason', 'Bulk status update')

        if not employee_ids or not new_status:
            raise ValidationError({'detail': 'Both "employees" (list) and "new_status" are required.'})

        results = {'success': [], 'failure': []}
        with transaction.atomic():
            employees = Employee.objects.filter(id__in=employee_ids, company=request.user.company)
            for emp in employees:
                try:
                    old_status = emp.employment_status
                    emp.employment_status = new_status
                    emp.save(update_fields=['employment_status', 'updated_at'])
                    
                    EmploymentEvent.objects.create(
                        employee=emp, event_type='status_change', effective_date=timezone.localdate(),
                        title='Bulk Status Update', description=f'{reason}. {old_status} -> {new_status}.',
                        created_by=request.user
                    )
                    audit(request.user, 'update', f'Bulk status update for {emp.full_name}', emp.company, 'employee', emp.id, {'old_status': old_status, 'new_status': new_status}, request=request)
                    results['success'].append(emp.id)
                except Exception as e:
                    results['failure'].append({'id': emp.id, 'error': str(e)})

        return Response(results)

    @action(detail=False, methods=['get'], url_path='my-profile')
    def my_profile(self, request):
        """Return the current logged-in employee's profile."""
        if request.user.employee_id is None:
            return Response({'detail': 'User is not linked to an employee profile.'}, status=404)

        employee = self.get_queryset().filter(id=request.user.employee_id).first()
        if not employee:
            return Response({'detail': 'Employee profile not found.'}, status=404)
            
        return Response(self.get_serializer(employee).data)

    @action(detail=False, methods=['post'], url_path='submit-self-request')
    def submit_self_request(self, request):
        """Allows employees to submit their own change requests."""
        if request.user.employee_id is None:
            return Response({'detail': 'User is not linked to an employee profile.'}, status=403)

        employee = Employee.objects.filter(id=request.user.employee_id, company=request.user.company).first()
        if not employee:
            return Response({'detail': 'Employee profile not found.'}, status=404)

        request_type = request.data.get('request_type')
        payload = request.data.get('payload', {})
        
        if not request_type:
            raise ValidationError({'request_type': 'Request type is required.'})

        req = EmployeeService.submit_hr_request(employee, request_type, payload, request.user)
        return Response(HRRequestSerializer(req).data, status=201)


class EmployeeStatutoryProfileViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeeStatutoryProfileSerializer
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManageHR]

    def get_queryset(self):
        return ScopedMixin.scope(self, EmployeeStatutoryProfile.objects.filter(employee__company=self.request.user.company).select_related('employee','employee__company__country_profile'))

    def perform_create(self, serializer):
        employee = Employee.objects.filter(id=self.request.data.get('employee'), company=self.request.user.company).first()
        if not employee:
            raise ValidationError({'employee':'Employee not found in your company.'})
        obj = serializer.save(employee=employee)
        audit(self.request.user, 'update', f'Created statutory profile for {employee.full_name}', employee.company, 'employee_statutory_profile', obj.id, request=self.request)

    def perform_update(self, serializer):
        obj = serializer.save()
        audit(self.request.user, 'update', f'Updated statutory profile for {obj.employee.full_name}', obj.employee.company, 'employee_statutory_profile', obj.id, request=self.request)


class EmployeeDocumentViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeeDocumentSerializer
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManageHR]
    def get_queryset(self):
        return ScopedMixin.scope(self, EmployeeDocument.objects.filter(employee__company=self.request.user.company).select_related('employee','uploaded_by'))


    def perform_create(self, serializer):
        employee = Employee.objects.filter(id=self.request.data.get('employee'), company=self.request.user.company).first()
        if not employee: raise ValidationError({'employee':'Employee not found in your company.'})
        obj = serializer.save(employee=employee, uploaded_by=self.request.user)
        EmploymentEvent.objects.create(employee=employee, event_type='note', effective_date=timezone.localdate(), title=f'Document uploaded: {obj.title}', description=f'{obj.get_document_type_display()} document added to employee records.', created_by=self.request.user)
        audit(self.request.user, 'update', f'Uploaded employee document for {employee.full_name}', employee.company, 'employee_document', obj.id, {'document_type': obj.document_type, 'title': obj.title}, request=self.request)
    def perform_update(self, serializer):
        obj=serializer.save(); audit(self.request.user,'update',f'Updated employee document {obj.title}',obj.employee.company,'employee_document',obj.id,request=self.request)
    def perform_destroy(self, instance):
        audit(self.request.user,'delete',f'Deleted employee document {instance.title}',instance.employee.company,'employee_document',instance.id,request=self.request); instance.delete()


class ContractViewSet(viewsets.ModelViewSet):
    serializer_class=ContractSerializer; permission_classes=[IsCompanyMember,IsCompanyActive,CanManageHR]
    def get_queryset(self): return ScopedMixin.scope(self, Contract.objects.filter(employee__company=self.request.user.company).select_related('employee'))


    def perform_create(self, serializer):
        employee=Employee.objects.get(id=serializer.validated_data['employee'].id, company=self.request.user.company); contract=serializer.save(employee=employee)
        EmploymentEvent.objects.create(employee=employee, event_type='contract_change', effective_date=contract.start_date, title='Contract created', description=f'{contract.get_contract_type_display()} contract recorded.', created_by=self.request.user)
        audit(self.request.user, 'contract_change', f'Created contract for {employee.full_name}', employee.company, 'contract', contract.id, request=self.request)

    def perform_update(self, serializer):
        instance=self.get_object(); before=snapshot_fields(instance, ['contract_type','start_date','end_date','notes']); contract=serializer.save(); changes=changed_fields(contract, ['contract_type','start_date','end_date','notes'], before=before)
        EmploymentEvent.objects.create(employee=contract.employee, event_type='contract_change', effective_date=contract.start_date, title='Contract updated', description='Contract record updated.', created_by=self.request.user)
        audit(self.request.user, 'contract_change', f'Updated contract for {contract.employee.full_name}', contract.employee.company, 'contract', contract.id, {'changes': changes}, request=self.request)
    @action(detail=True, methods=['post'])
    def renew(self, request, pk=None):
        contract=self.get_object(); end_date=request.data.get('end_date')
        start_date=request.data.get('start_date')
        contract_type=request.data.get('contract_type')
        notes=request.data.get('notes')

        if request.user.role == 'department_manager':
            payload = {
                'contract_id': contract.id,
                'end_date': end_date,
                'start_date': start_date,
                'contract_type': contract_type,
                'notes': notes
            }
            req = EmployeeService.submit_hr_request(contract.employee, 'contract', payload, request.user)
            return Response(HRRequestSerializer(req).data, status=201)

        new_contract = ContractService.renew_contract(
            contract, end_date, start_date, contract_type, notes, user=request.user
        )
        return Response(ContractSerializer(new_contract, context={'request':request}).data, status=201)

    @action(detail=True, methods=['post'])
    def end(self, request, pk=None):
        contract = self.get_object()
        raw_end_date = request.data.get('end_date')
        try:
            end_date = serializers.DateField().to_internal_value(raw_end_date) if raw_end_date else timezone.localdate()
        except serializers.ValidationError:
            raise ValidationError({'end_date': 'Enter a valid date in YYYY-MM-DD format.'})

        if request.user.role == 'department_manager':
            payload = {'contract_id': contract.id, 'end_date': end_date}
            req = EmployeeService.submit_hr_request(contract.employee, 'contract', payload, request.user)
            return Response(HRRequestSerializer(req).data, status=201)

        contract = ContractService.end_contract(contract, end_date, user=request.user)
        return Response(ContractSerializer(contract, context={'request': request}).data)


    def perform_destroy(self, instance):
        audit(self.request.user, 'contract_change', f'Deleted contract for {instance.employee.full_name}', instance.employee.company, 'contract', instance.id, request=self.request); instance.delete()

class WarningLetterViewSet(viewsets.ModelViewSet):
    serializer_class=WarningLetterSerializer; permission_classes=[IsCompanyMember,IsCompanyActive,CanManageHR]
    def get_queryset(self):
        qs = ScopedMixin.scope(self, WarningLetter.objects.filter(employee__company=self.request.user.company).select_related('employee','issued_by'))
        dept = self.request.query_params.get('department')
        if dept: qs = qs.filter(employee__department__iexact=dept)
        return qs


    def perform_create(self, serializer):
        employee=Employee.objects.get(id=serializer.validated_data['employee'].id, company=self.request.user.company); warning=serializer.save(employee=employee, issued_by=self.request.user)
        audit(self.request.user, 'disciplinary_action', f'Issued warning letter to {employee.full_name}', employee.company, 'warning_letter', warning.id, {'warning_level': warning.warning_level, 'subject': warning.subject}, request=self.request)

    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        obj=self.get_object(); obj.acknowledged=True; obj.save(update_fields=['acknowledged'])
        if request.data.get('employee_response') is not None: obj.employee_response=request.data.get('employee_response',''); obj.save(update_fields=['employee_response'])
        audit(request.user,'disciplinary_action',f'Acknowledged warning letter for {obj.employee.full_name}',obj.employee.company,'warning_letter',obj.id,request=request)
        return Response(WarningLetterSerializer(obj, context={'request':request}).data)

    def perform_update(self, serializer):
        obj=serializer.save(); audit(self.request.user, 'update', f'Updated warning letter for {obj.employee.full_name}', obj.employee.company, 'warning_letter', obj.id, request=self.request)
    def perform_destroy(self, instance):
        audit(self.request.user, 'delete', f'Deleted warning letter for {instance.employee.full_name}', instance.employee.company, 'warning_letter', instance.id, request=self.request); instance.delete()

class EmployeeAllowanceViewSet(viewsets.ModelViewSet):
    serializer_class=EmployeeAllowanceSerializer; permission_classes=[IsCompanyMember,IsCompanyActive,CanManageHR]
    def get_queryset(self): return ScopedMixin.scope(self, EmployeeAllowance.objects.filter(employee__company=self.request.user.company))


    def perform_create(self, serializer):
        employee = Employee.objects.get(id=serializer.validated_data['employee'].id, company=self.request.user.company)
        obj=serializer.save(employee=employee); audit(self.request.user, 'salary_change', f'Added allowance {obj.name} for {obj.employee.full_name}', obj.employee.company, 'employee_allowance', obj.id, {'amount': str(obj.amount)}, request=self.request)
    def perform_update(self, serializer):
        obj=serializer.save(); audit(self.request.user, 'salary_change', f'Updated allowance {obj.name} for {obj.employee.full_name}', obj.employee.company, 'employee_allowance', obj.id, request=self.request)
    def perform_destroy(self, instance):
        audit(self.request.user, 'salary_change', f'Removed allowance {instance.name} for {instance.employee.full_name}', instance.employee.company, 'employee_allowance', instance.id, request=self.request); instance.delete()

class EmployeeDeductionViewSet(viewsets.ModelViewSet):
    serializer_class=EmployeeDeductionSerializer; permission_classes=[IsCompanyMember,IsCompanyActive,CanManageHR]
    def get_queryset(self): return ScopedMixin.scope(self, EmployeeDeduction.objects.filter(employee__company=self.request.user.company))


    def perform_create(self, serializer):
        employee = Employee.objects.get(id=serializer.validated_data['employee'].id, company=self.request.user.company)
        obj=serializer.save(employee=employee); audit(self.request.user, 'salary_change', f'Added deduction {obj.name} for {obj.employee.full_name}', obj.employee.company, 'employee_deduction', obj.id, {'amount': str(obj.amount)}, request=self.request)
    def perform_update(self, serializer):
        obj=serializer.save(); audit(self.request.user, 'salary_change', f'Updated deduction {obj.name} for {obj.employee.full_name}', obj.employee.company, 'employee_deduction', obj.id, request=self.request)
    def perform_destroy(self, instance):
        audit(self.request.user, 'salary_change', f'Removed deduction {instance.name} for {instance.employee.full_name}', instance.employee.company, 'employee_deduction', instance.id, request=self.request); instance.delete()


class DashboardSummaryView(APIView):
    permission_classes = [IsCompanyMember, IsCompanyActive]

    def get(self, request):
        company = request.user.company
        today = timezone.localdate()
        
        expiring_docs = EmployeeDocument.objects.filter(
            employee__company=company,
            expiry_date__gte=today,
            expiry_date__lte=today + timedelta(days=30)
        ).count()

        expiring_contracts = Contract.objects.filter(
            employee__company=company,
            end_date__gte=today,
            end_date__lte=today + timedelta(days=15)
        ).count()

        pending_reqs = 0
        if request.user.role in ('owner', 'admin', 'hr'):
            pending_reqs = HRRequest.objects.filter(
                employee__company=company,
                status='pending'
            ).count()

        active = Employee.objects.filter(company=company, employment_status='active').count()
        
        return Response({
            'kpis': {
                'expiring_documents': expiring_docs,
                'expiring_contracts': expiring_contracts,
                'pending_requests': pending_reqs,
                'active_employees': active,
            },
            'alerts': {
                'critical_docs': expiring_docs > 0,
                'critical_contracts': expiring_contracts > 0,
                'action_required': pending_reqs > 0,
            }
        })

class ComplianceDashboardView(viewsets.ViewSet):
    permission_classes = [IsCompanyMember, IsCompanyActive]

    def list(self, request):
        if request.user.role == 'employee' and request.user.employee_id is not None:
            employees = Employee.objects.filter(id=request.user.employee_id)
        elif request.user.role == 'department_manager':
            employees = Employee.objects.filter(company=request.user.company, department=request.user.managed_department)
        else:
            employees = Employee.objects.filter(company=request.user.company)
        employees = employees.select_related('department_obj').prefetch_related('documents','contracts')
        rules = list(RequiredDocumentRule.objects.filter(company=request.user.company, is_active=True))
        summaries = []
        alerts = []
        total_score = 0
        today = timezone.localdate()
        for employee in employees:
            result = _employee_compliance(employee, rules, today)
            total_score += result['score']
            summaries.append({'employee_id': employee.id, 'employee_code': employee.employee_code, 'employee_name': employee.full_name, 'department': employee.effective_department, **{k: result[k] for k in ('score','required_count','missing_count','expired_count','expiring_count')}})
            for item in result['missing']:
                alerts.append({'category':'document_missing','severity':'critical','employee_id':employee.id,'employee_name':employee.full_name,'title':f"Missing {item['rule']}",'due_date':None,'details':f"Required {item['document_type']} document is not on file."})
            for item in result['expired']:
                alerts.append({'category':'document_expired','severity':'critical','employee_id':employee.id,'employee_name':employee.full_name,'title':f"{item['title']} expired",'due_date':item['expiry_date'],'details':f"Expired {item['days_overdue']} day(s) ago."})
            for item in result['expiring']:
                severity = 'warning' if item['days_to_expiry'] > 7 else 'critical'
                alerts.append({'category':'document_expiring','severity':severity,'employee_id':employee.id,'employee_name':employee.full_name,'title':f"{item['title']} expires soon",'due_date':item['expiry_date'],'details':f"{item['days_to_expiry']} day(s) remaining."})
            contracts = sorted(employee.contracts.all(), key=lambda c: c.start_date, reverse=True)
            contract = contracts[0] if contracts else None
            if contract and contract.end_date:
                days = (contract.end_date - today).days
                if days < 0:
                    alerts.append({'category':'contract_expired','severity':'critical','employee_id':employee.id,'employee_name':employee.full_name,'title':'Latest contract expired','due_date':contract.end_date,'details':f"Contract ended {abs(days)} day(s) ago."})
                elif days <= 30:
                    alerts.append({'category':'contract_expiring','severity':'warning' if days > 7 else 'critical','employee_id':employee.id,'employee_name':employee.full_name,'title':'Contract expires soon','due_date':contract.end_date,'details':f"{days} day(s) remaining."})
        avg = round(total_score / len(summaries)) if summaries else 100
        alerts.sort(key=lambda x: (0 if x['severity']=='critical' else 1, x['due_date'] or today))
        return Response({'summary': {'employees':len(summaries),'compliant':sum(1 for x in summaries if x['score'] == 100),'needs_attention':sum(1 for x in summaries if x['score'] < 100),'average_score':avg,'missing_documents':sum(x['missing_count'] for x in summaries),'expired_documents':sum(x['expired_count'] for x in summaries),'expiring_documents':sum(x['expiring_count'] for x in summaries),'open_alerts':len(alerts)}, 'employees':summaries, 'alerts':alerts[:100], 'rules_count':len(rules)})

class EmployeePersonalDetailsViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeePersonalDetailsSerializer
    permission_classes = [IsCompanyMember, IsCompanyActive]

    def get_queryset(self):
        qs = EmployeePersonalDetails.objects.filter(employee__company=self.request.user.company).select_related('employee')
        user = self.request.user
        if user.role == 'employee' and user.employee_id is not None:
            qs = qs.filter(employee_id=user.employee_id)
        elif user.role == 'department_manager':
            qs = qs.filter(employee__department=user.managed_department)
        return qs

    def _can_write(self, employee):
        user = self.request.user
        return user.role in ('owner','admin','hr') or (user.role == 'employee' and employee.id == user.employee_id)



    def perform_create(self, serializer):
        employee_id = self.request.data.get('employee')
        if not employee_id:
            raise ValidationError({'employee':'Employee is required.'})
        employee = Employee.objects.filter(id=employee_id, company=self.request.user.company).first()
        if not employee:
            raise ValidationError({'employee':'Employee not found in your company.'})
        if not self._can_write(employee):
            raise ValidationError({'detail':'You do not have permission to update this employee profile.'})
        if EmployeePersonalDetails.objects.filter(employee=employee).exists():
            raise ValidationError({'employee':'Personal details already exist. Update the existing record instead.'})
        obj = serializer.save(employee=employee)
        audit(self.request.user, 'update', f'Updated personal details for {employee.full_name}', employee.company, 'employee_personal_details', obj.id, request=self.request)

    def perform_update(self, serializer):
        employee = self.get_object().employee
        if not self._can_write(employee):
            raise ValidationError({'detail':'You do not have permission to update this employee profile.'})
        obj = serializer.save()
        audit(self.request.user, 'update', f'Updated personal details for {employee.full_name}', employee.company, 'employee_personal_details', obj.id, request=self.request)


class EmergencyContactViewSet(viewsets.ModelViewSet):
    serializer_class = EmergencyContactSerializer
    permission_classes = [IsCompanyMember, IsCompanyActive]
    http_method_names = ['get', 'post', 'patch', 'put', 'delete']

    def get_queryset(self):
        qs = EmergencyContact.objects.filter(employee__company=self.request.user.company).select_related('employee')
        user = self.request.user
        if user.role == 'employee' and user.employee_id is not None:
            qs = qs.filter(employee_id=user.employee_id)
        elif user.role == 'department_manager':
            qs = qs.filter(employee__department=user.managed_department)
        employee_id = self.request.query_params.get('employee')
        if employee_id: qs = qs.filter(employee_id=employee_id)
        return qs

    def _employee_from_request(self):
        employee_id = self.request.data.get('employee')
        if employee_id:
            return Employee.objects.filter(id=employee_id, company=self.request.user.company).first()
        obj = getattr(self, 'get_object', lambda: None)()
        return obj.employee if obj else None

    def _can_write(self, employee):
        user = self.request.user
        return bool(employee) and (user.role in ('owner','admin','hr') or (user.role == 'employee' and user.employee_id is not None and employee.id == user.employee_id))



    def perform_create(self, serializer):
        employee = self._employee_from_request()
        if not self._can_write(employee): raise ValidationError({'employee':'You cannot modify this employee.'})
        if serializer.validated_data.get('is_primary'):
            EmergencyContact.objects.filter(employee=employee, is_primary=True).update(is_primary=False)
        obj = serializer.save(employee=employee)
        audit(self.request.user, 'update', f'Added emergency contact for {employee.full_name}', employee.company, 'emergency_contact', obj.id, request=self.request)

    def perform_update(self, serializer):
        employee = self.get_object().employee
        if not self._can_write(employee): raise ValidationError({'detail':'You cannot modify this employee.'})
        if serializer.validated_data.get('is_primary'):
            EmergencyContact.objects.filter(employee=employee, is_primary=True).exclude(pk=self.get_object().pk).update(is_primary=False)
        obj = serializer.save()
        audit(self.request.user, 'update', f'Updated emergency contact for {employee.full_name}', employee.company, 'emergency_contact', obj.id, request=self.request)

    def perform_destroy(self, instance):
        if not self._can_write(instance.employee): raise ValidationError({'detail':'You cannot modify this employee.'})
        audit(self.request.user, 'delete', f'Removed emergency contact for {instance.employee.full_name}', instance.employee.company, 'emergency_contact', instance.id, request=self.request)
        instance.delete()


class EmploymentEventViewSet(viewsets.ModelViewSet):
    serializer_class = EmploymentEventSerializer
    permission_classes = [IsCompanyMember, IsCompanyActive]
    http_method_names = ['get', 'post']

    def get_queryset(self):
        qs = EmploymentEvent.objects.filter(employee__company=self.request.user.company).select_related('employee','created_by')
        user = self.request.user
        if user.role == 'employee' and user.employee_id is not None:
            qs = qs.filter(employee_id=user.employee_id)
        elif user.role == 'department_manager':
            qs = qs.filter(employee__department=user.managed_department)
        employee_id = self.request.query_params.get('employee')
        if employee_id: qs = qs.filter(employee_id=employee_id)
        return qs



    def perform_create(self, serializer):
        if self.request.user.role not in ('owner','admin','hr'):
            raise ValidationError({'detail':'Only HR, admins, and owners can add employment history events.'})
        employee_id = self.request.data.get('employee')
        employee = Employee.objects.filter(id=employee_id, company=self.request.user.company).first()
        if not employee: raise ValidationError({'employee':'Employee not found in your company.'})
        obj = serializer.save(employee=employee, created_by=self.request.user)
        audit(self.request.user, 'update', f'Added employment history event for {employee.full_name}', employee.company, 'employment_event', obj.id, request=self.request)


class RequiredDocumentRuleViewSet(viewsets.ModelViewSet):
    serializer_class = RequiredDocumentRuleSerializer
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManageHR]

    def get_queryset(self):
        qs = RequiredDocumentRule.objects.filter(company=self.request.user.company).select_related('employee')
        user = self.request.user
        if user.role == 'department_manager':
            qs = qs.filter(employee__department=user.managed_department) | qs.filter(employee__isnull=True)
        return qs.distinct()



    def perform_create(self, serializer):
        obj = serializer.save(company=self.request.user.company)
        audit(self.request.user, 'create', f'Created compliance document rule {obj.name}', obj.company, 'required_document_rule', obj.id, request=self.request)

    def perform_update(self, serializer):
        obj = serializer.save()
        audit(self.request.user, 'update', f'Updated compliance document rule {obj.name}', obj.company, 'required_document_rule', obj.id, request=self.request)

    def perform_destroy(self, instance):
        audit(self.request.user, 'delete', f'Deleted compliance document rule {instance.name}', instance.company, 'required_document_rule', instance.id, request=self.request)
        instance.delete()


def _document_matches_rule(document, rule):
    if document.document_type != rule.document_type:
        return False
    if rule.name and rule.name.lower() not in document.title.lower():
        return False
    return True


def _employee_compliance(employee, rules, today=None):
    today = today or timezone.localdate()
    docs = list(employee.documents.all())
    applicable = [r for r in rules if r.is_active and (r.employee_id is None or r.employee_id == employee.id) and (not r.contract_type or (employee.current_contract and employee.current_contract.contract_type == r.contract_type))]
    required = []
    missing = []
    expired = []
    expiring = []
    for rule in applicable:
        matches = [d for d in docs if _document_matches_rule(d, rule)]
        if not matches:
            missing.append({'rule_id': rule.id, 'rule': rule.name, 'document_type': rule.document_type, 'warning_days': rule.warning_days})
            continue
        best = sorted(matches, key=lambda d: d.expiry_date or today, reverse=True)[0]
        required.append(best.id)
        if best.expiry_date:
            days = (best.expiry_date - today).days
            if days < 0:
                expired.append({'document_id': best.id, 'title': best.title, 'rule': rule.name, 'expiry_date': best.expiry_date, 'days_overdue': abs(days)})
            elif days <= rule.warning_days:
                expiring.append({'document_id': best.id, 'title': best.title, 'rule': rule.name, 'expiry_date': best.expiry_date, 'days_to_expiry': days})
    total = len(applicable)
    problems = len(missing) + len(expired)
    score = 100 if total == 0 else max(0, round(((total - problems) / total) * 100))
    return {'score': score, 'required_count': total, 'missing_count': len(missing), 'expired_count': len(expired), 'expiring_count': len(expiring), 'missing': missing, 'expired': expired, 'expiring': expiring}


