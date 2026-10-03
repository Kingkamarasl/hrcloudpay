from django.core.management.base import BaseCommand
from django.core.exceptions import ObjectDoesNotExist
from employees.models import Employee
from employees.services import EmployeeService
import sys

class Command(BaseCommand):
    help = 'Permanently deletes an employee record, deactivates their user account, and audits the action.'

    def add_arguments(self, parser):
        parser.add_argument('employee_id', type=int, help='The ID of the employee to delete')
        parser.add_argument(
            '--user_id', 
            type=int, 
            help='The ID of the user performing the deletion (for audit purposes). If omitted, it will be marked as a system action.',
            default=None
        )

    def handle(self, *args, **options):
        employee_id = options['employee_id']
        user_id = options['user_id']
        
        try:
            employee = Employee.objects.get(pk=employee_id)
        except Employee.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Employee with ID {employee_id} not found."))
            sys.exit(1)

        # If a user_id was provided, try to fetch the user object for the audit log
        admin_user = None
        if user_id:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                admin_user = User.objects.get(pk=user_id)
            except User.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"User ID {user_id} not found. Proceeding as system action."))

        self.stdout.write(
            f"WARNING: You are about to permanently delete employee {employee.full_name} (Code: {employee.employee_code}). "
            "This will remove all contracts, payroll data, and deactivate their user account. "
            "This action is irreversible."
        )
        
        # In a real CLI, we might ask for confirmation, but for management commands 
        # we typically assume the operator knows what they are doing or use a --force flag.
        
        try:
            EmployeeService.delete_employee(employee, user=admin_user)
            self.stdout.write(self.style.SUCCESS(f"Successfully deleted employee {employee.full_name}."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"An error occurred during deletion: {e}"))
            sys.exit(1)
