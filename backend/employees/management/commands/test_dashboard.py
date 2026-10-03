from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from employees.views import DashboardSummaryView
from rest_framework.test import APIRequestFactory
from django.test import RequestFactory

User = get_user_model()

class Command(BaseCommand):
    help = 'Tests the DashboardSummaryView logic'

    def handle(self, *args, **options):
        self.stdout.write("Testing DashboardSummaryView...")

        # 1. Get a user to simulate the request
        try:
            user = User.objects.filter(role='owner').first()
            if not user:
                user = User.objects.first()
            
            if not user:
                self.stdout.write(self.style.ERROR("No users found in database. Please create a user first."))
                return

            self.stdout.write(f"Simulating request for user: {user.username} (Role: {user.role})")

            # 2. Mock a request using APIRequestFactory
            factory = APIRequestFactory()
            request = factory.get('/api/employees/dashboard-summary/')
            request.user = user

            # 3. Call the view directly
            view = DashboardSummaryView.as_view()
            response = view(request)

            # 4. Verify the output
            data = response.data
            self.stdout.write(f"Response Data: {data}")

            if 'kpis' in data and 'alerts' in data:
                self.stdout.write(self.style.SUCCESS("Test Passed: Dashboard summary data returned successfully."))
            else:
                self.stdout.write(self.style.ERROR("Test Failed: Missing kpis or alerts in response."))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"An error occurred during testing: {str(e)}"))
