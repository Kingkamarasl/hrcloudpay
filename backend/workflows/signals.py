from django.db.models.signals import post_save
from django.dispatch import receiver
from employees.models import Employee
from .services import onboard_employee

@receiver(post_save, sender=Employee)
def employee_created(sender, instance, created, **kwargs):
    if created:
        onboard_employee(instance)
