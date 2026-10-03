import hashlib
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from .models import SecuritySession
from django.utils import timezone
User = get_user_model()
class SecurityCookieAuthentication(BaseAuthentication):
    keyword = 'hrcloudpay_session'
    def authenticate(self, request):
        raw = request.COOKIES.get(self.keyword)
        if not raw: return None
        session = SecuritySession.objects.select_related('user','company').filter(secret_hash=hashlib.sha256(raw.encode()).hexdigest(), revoked_at__isnull=True, expires_at__gt=timezone.now()).first()
        if not session or not session.user.is_active: return None
        session.save(update_fields=['last_seen_at'])
        return (session.user, session)
