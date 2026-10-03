from django.db.models import Count, Sum
from django.utils import timezone

from accounts.models import Company, User
from accounts.platform_models import AuditLog, PaymentTransaction, Subscription, SupportTicket
from attendance.models import Attendance
from employees.models import Employee
from payroll.models import PayrollRun


def dashboard_callback(request, context):
    """Prepare the internal developer/back-office dashboard."""
    now = timezone.now()
    companies = Company.objects.all()
    subscriptions = Subscription.objects.all()
    context.update(
        {
            "hc_companies": companies.count(),
            "hc_active_companies": companies.filter(is_active=True).count(),
            "hc_employees": Employee.objects.count(),
            "hc_users": User.objects.count(),
            "hc_active_subscriptions": subscriptions.filter(status__in=["trial", "active", "grace"]).count(),
            "hc_mrr": subscriptions.filter(status__in=["active", "trial"]).aggregate(total=Sum("monthly_price"))["total"] or 0,
            "hc_payroll_runs": PayrollRun.objects.count(),
            "hc_open_tickets": SupportTicket.objects.exclude(status__in=["resolved", "closed"]).count(),
            "hc_recent_audits": AuditLog.objects.select_related("actor", "company").order_by("-created_at")[:8],
            "hc_recent_transactions": PaymentTransaction.objects.select_related("company").order_by("-created_at")[:8],
            "hc_payroll_ready": companies.filter(payroll_configured=True).count(),
            "hc_today_attendance": Attendance.objects.filter(date=timezone.localdate()).count(),
            "hc_now": now,
        }
    )
    return context


def environment_callback(request):
    if getattr(request, "is_secure", lambda: False)() and not request.user.is_superuser:
        return ["Production", "success"]
    return ["Development", "warning"]
