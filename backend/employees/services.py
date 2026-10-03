from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from rest_framework.exceptions import ValidationError
from django.db.models import Q
from .models import Contract, EmploymentEvent, Employee, HRRequest
from accounts.audit import audit
import logging

logger = logging.getLogger('hrcloudpay')

class EmployeeService:
    """Service layer for handling employee-related business logic."""

    @staticmethod
    def is_period_locked(employee, date):
        """Check if a date falls within a finalized payroll period."""
        from payroll.models import PayrollRun
        locked_periods = PayrollRun.objects.filter(
            company=employee.company,
            status__in=['approved', 'paid'],
            period_start__lte=date,
            period_end__gte=date
        )
        if locked_periods.exists():
            period = locked_periods.first()
            raise ValidationError(
                f"Cannot modify records for this date. Payroll period {period.period_start} to {period.period_end} is already {period.status}."
            )
        return False

    @staticmethod
    def delete_employee(employee, user=None):
        """Handles the robust deletion of an employee and their associated data."""
        with transaction.atomic():
            company = employee.company
            employee_id = employee.id
            full_name = employee.full_name

            # 1. Audit the deletion before the record is gone
            try:
                audit(user, 'delete', f'Deleted employee {full_name}',
                      company, 'employee', employee_id,
                      {'employee_code': employee.employee_code})
            except Exception as e:
                logger.error(f"Audit failure in delete_employee: {e}")

            # 2. Handle the associated User account
            # Employee.user is SET_NULL, so the user persists.
            # We deactivate the user to prevent login.
            if employee.user:
                employee.user.is_active = False
                employee.user.save(update_fields=['is_active'])

            # 3. Delete the employee (Django CASCADE handles contracts, profile, etc.)
            employee.delete()

        return True

    @staticmethod
    def submit_hr_request(employee, request_type, payload, user):
        """Submit a change request for HR/Owner approval."""
        with transaction.atomic():
            request = HRRequest.objects.create(
                employee=employee,
                request_type=request_type,
                payload=payload,
                requested_by=user,
                status='pending'
            )
            
            # Audit the submission
            try:
                audit(user, 'request_submitted', f'Submitted {request_type} request for {employee.full_name}',
                      employee.company, 'hr_request', request.id, 
                      {'payload': payload})
            except Exception as e:
                logger.error(f"Audit failure in submit_hr_request: {e}")
                
        return request

    @staticmethod
    def approve_hr_request(request_id, user, comments=""):
        """Approve a pending request and apply the changes to the employee record."""
        with transaction.atomic():
            try:
                hr_request = HRRequest.objects.select_for_update().get(pk=request_id, status='pending')
            except HRRequest.DoesNotExist:
                raise ValidationError("Pending request not found.")

            employee = hr_request.employee
            payload = hr_request.payload
            request_type = hr_request.request_type

            # Apply changes based on request type
            if request_type == 'salary':
                EmployeeService.change_salary(
                    employee, 
                    payload.get('new_salary'), 
                    payload.get('effective_date'), 
                    payload.get('reason', 'Approved salary change'), 
                    user=user
                )
            elif request_type == 'position':
                # Handle department_obj ID conversion if necessary
                dept_obj = None
                if payload.get('department_obj'):
                    from .models import Department
                    dept_obj = Department.objects.filter(id=payload['department_obj'], company=employee.company).first()
                
                EmployeeService.change_position(
                    employee, 
                    payload.get('job_title'), 
                    dept_obj, 
                    payload.get('effective_date'), 
                    payload.get('reason', 'Approved position change'), 
                    user=user
                )
            elif request_type == 'contract':
                # For contracts, we might delegate to ContractService
                from .services import ContractService
                if payload.get('contract_id'):
                    contract = Contract.objects.get(pk=payload['contract_id'])
                    ContractService.renew_contract(
                        contract, 
                        payload.get('end_date'), 
                        payload.get('start_date'), 
                        payload.get('contract_type'), 
                        payload.get('notes'), 
                        user=user
                    )

            # Update request status
            hr_request.status = 'approved'
            hr_request.approved_by = user
            hr_request.comments = comments
            hr_request.save()

            try:
                audit(user, 'request_approved', f'Approved {request_type} for {employee.full_name}',
                      employee.company, 'hr_request', hr_request.id, 
                      {'comments': comments})
            except Exception as e:
                logger.error(f"Audit failure in approve_hr_request: {e}")

        return hr_request

    @staticmethod
    def reject_hr_request(request_id, user, comments=""):
        """Reject a pending request."""
        with transaction.atomic():
            try:
                hr_request = HRRequest.objects.select_for_update().get(pk=request_id, status='pending')
            except HRRequest.DoesNotExist:
                raise ValidationError("Pending request not found.")

            hr_request.status = 'rejected'
            hr_request.approved_by = user 
            hr_request.comments = comments
            hr_request.save()

            try:
                audit(user, 'request_rejected', f'Rejected {hr_request.request_type} for {hr_request.employee.full_name}',
                      hr_request.employee.company, 'hr_request', hr_request.id, 
                      {'comments': comments})
            except Exception as e:
                logger.error(f"Audit failure in reject_hr_request: {e}")

        return hr_request

    @staticmethod
    def change_salary(employee, new_salary, effective_date=None, reason="Salary change", user=None):
        effective_date = effective_date or timezone.localdate()
        EmployeeService.is_period_locked(employee, effective_date)
        old_salary = str(employee.base_salary)

        with transaction.atomic():
            employee.base_salary = new_salary
            employee.save(update_fields=['base_salary', 'updated_at'])

            EmploymentEvent.objects.create(
                employee=employee,
                event_type='salary_change',
                effective_date=effective_date,
                title='Salary changed',
                description=f'{reason}. Previous: {old_salary}. New: {new_salary}.',
                created_by=user
            )

            try:
                audit(user, 'salary_change', f'Changed salary for {employee.full_name}',
                      employee.company, 'employee', employee.id,
                      {'before': old_salary, 'after': str(new_salary), 'effective_date': str(effective_date), 'reason': reason})
            except Exception as e:
                logger.error(f"Audit failure in change_salary: {e}")

        return employee

    @staticmethod
    def change_position(employee, new_title, department_obj=None, effective_date=None, reason="Position change", user=None):
        effective_date = effective_date or timezone.localdate()
        EmployeeService.is_period_locked(employee, effective_date)
        old_title = employee.job_title
        old_dept = employee.effective_department

        with transaction.atomic():
            employee.job_title = new_title
            if department_obj:
                employee.department_obj = department_obj
                employee.department = department_obj.name

            employee.save(update_fields=['job_title', 'department_obj', 'department', 'updated_at'])

            event_type = 'transfer' if employee.effective_department != old_dept else 'promotion'
            EmploymentEvent.objects.create(
                employee=employee,
                event_type=event_type,
                effective_date=effective_date,
                title='Position change',
                description=f'{reason}. Position: {old_title or "Unassigned"} -> {new_title}.',
                created_by=user
            )

            try:
                audit(user, 'update', f'Changed position for {employee.full_name}',
                      employee.company, 'employee', employee.id,
                      {'old_title': old_title, 'new_title': new_title, 'effective_date': str(effective_date)})
            except Exception as e:
                logger.error(f"Audit failure in change_position: {e}")

        return employee

class ContractService:
    """Service layer for handling contract-related business logic."""

    @staticmethod
    def end_contract(contract, end_date=None, user=None):
        end_date = end_date or timezone.localdate()
        EmployeeService.is_period_locked(contract.employee, end_date)
        if end_date < contract.start_date:
            raise ValidationError({'end_date': 'End date cannot be before the contract start date.'})

        employee = contract.employee

        with transaction.atomic():
            # 1. Update contract end date
            contract.end_date = end_date
            contract.save(update_fields=['end_date'])

            # 2. Check if this was the active contract and update employee status
            # We use a simple query instead of the property to avoid potential property-recursion or state issues
            is_current = Contract.objects.filter(
                pk=contract.pk,
                employee=employee,
                start_date__lte=end_date,
            ).filter(
                Q(end_date__isnull=True) | Q(end_date__gte=end_date)
            ).exists()

            if is_current:
                employee.employment_status = 'terminated'
                employee.save(update_fields=['employment_status', 'updated_at'])

            try:
                EmploymentEvent.objects.create(
                    employee=employee,
                    event_type='contract_change',
                    effective_date=end_date,
                    title='Contract ended',
                    description=f'Contract end date recorded. Employee status updated to {employee.employment_status}.',
                    created_by=user
                )
                audit(user, 'contract_change', f'Ended contract for {employee.full_name}',
                      employee.company, 'contract', contract.id,
                      {'end_date': str(end_date), 'employment_status': employee.employment_status})
            except Exception as e:
                logger.error(f"Audit failure in end_contract: {e}")

        return contract

    @staticmethod
    def renew_contract(contract, end_date, start_date=None, contract_type=None, notes=None, user=None):
        if not contract.end_date:
            raise ValidationError({'detail': 'End the current open-ended contract before assigning a new term.'})

        # Ensure new start date is strictly AFTER the old end date to avoid overlap validation errors
        start_date = start_date or (contract.end_date + timedelta(days=1))
        EmployeeService.is_period_locked(contract.employee, start_date)
        if not end_date:
            raise ValidationError({'end_date': 'New contract end date is required.'})

        with transaction.atomic():
            # 1. Reactivate Employee if they were terminated by the previous contract end
            employee = contract.employee
            if employee.employment_status in ('terminated', 'resigned'):
                employee.employment_status = 'active'
                employee.save(update_fields=['employment_status', 'updated_at'])

            # 2. Create the new contract
            try:
                new_contract = Contract.objects.create(
                    employee=employee,
                    contract_type=contract_type or contract.contract_type,
                    start_date=start_date,
                    end_date=end_date,
                    notes=notes or contract.notes
                )
            except Exception as e:
                from django.core.exceptions import ValidationError as DjangoValidationError
                if isinstance(e, DjangoValidationError):
                    raise ValidationError(e.message_dict)
                raise e

            EmploymentEvent.objects.create(
                employee=employee,
                event_type='contract_change',
                effective_date=start_date,
                title='Contract renewed',
                description=f'New {new_contract.get_contract_type_display()} contract period created. Employee reactivated.',
                created_by=user
            )

            try:
                audit(user, 'contract_change', f'Renewed contract for {employee.full_name}',
                      employee.company, 'contract', new_contract.id,
                      {'from_contract': contract.id, 'start_date': str(start_date), 'end_date': str(end_date)})
            except Exception as e:
                logger.error(f"Audit failure in renew_contract: {e}")

        return new_contract
