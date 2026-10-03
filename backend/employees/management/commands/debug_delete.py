from django.core.management.base import BaseCommand
from employees.models import Employee
from employees.services import EmployeeService
import traceback

class Command(BaseCommand):
    help = 'Debug employee deletion 500 error'

    def add_arguments(self, parser):
        parser.add_argument('employee_id', type=int, help='ID of employee to delete')

    def handle(self, *args, **options):
        emp_id = options['employee_id']
        self.stdout.write(f"Attempting to delete employee ID: {emp_id}...")
        
        try:
            employee = Employee.objects.get(pk=emp_id)
            EmployeeService.delete_employee(employee)
            self.stdout.write(self.style.SUCCESS(f"Successfully deleted employee {emp_id}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Caught exception: {str(e)}"))
            traceback.print_exc()
