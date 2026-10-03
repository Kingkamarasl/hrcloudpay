from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q
from django.utils import timezone
from security.models import SecuritySession
from .audit import audit, changed_fields, snapshot_fields

from .models import Company, User
from .permissions import IsCompanyActive, IsCompanyMember, IsOwnerOrAdminOnly, CanViewCompanyAudit
from .serializers import LoginSerializer, RegisterSerializer, StaffUserCreateSerializer, StaffUserSerializer, UserSerializer, CompanySerializer


class RegisterView(APIView):
    """
    Creates a Company + owner User. The company is inactive until the
    activation link (emailed here, printed to console in dev) is used.
    """
    permission_classes = [AllowAny]
    authentication_classes = []  # Token-only SPA; avoid SessionAuth CSRF on public endpoint

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        company = result['company']
        user = result['user']

        activation_link = (
            f"{settings.FRONTEND_URL}/activate/{company.id}/{company.activation_token}"
        )
        send_mail(
            subject='Activate your HRCLOUDPAY account',
            message=(
                f"Welcome to HRCLOUDPAY, {company.name}!\n\n"
                f"Activate your account here:\n{activation_link}"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[company.email],
            fail_silently=True,
        )

        return Response(
            {
                'message': 'Company registered. Check your email to activate your account.',
                'user': UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class ActivateView(APIView):
    """Activates a company account from the emailed link."""
    permission_classes = [AllowAny]
    authentication_classes = []  # Token-only SPA; avoid SessionAuth CSRF on public endpoint

    def post(self, request, company_id, token):
        import secrets
        company = get_object_or_404(Company, id=company_id)
        expected = str(company.activation_token or '')
        provided = str(token or '')
        if not expected or not secrets.compare_digest(provided, expected):
            return Response({'detail': 'Invalid activation link.'}, status=400)
        if company.is_active:
            return Response({'detail': 'Account already active.'})
        company.is_active = True
        company.save(update_fields=['is_active'])
        audit(None, 'activate', f'Company {company.name} activated from activation link', company, 'company', company.id, request=request)
        return Response({
            'detail': 'Account activated. Please complete your payroll setup.',
            'payroll_configured': company.payroll_configured,
        })


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # Token-only SPA; avoid SessionAuth CSRF on public endpoint
    throttle_scope = 'login'

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception:
            # Per-account lockout: DRF's throttle only buckets by IP, so a
            # rotating set of addresses would otherwise be unlimited here.
            from security.login_lockout import check_locked, record_failure, lockout_message
            identifier = str(
                request.data.get('username', request.data.get('email', ''))
            ).strip()
            audit(None, 'login_failed', f'Failed login attempt for {identifier}', None, 'authentication', '', request=request)
            remaining = record_failure('username', identifier)
            if remaining:
                return Response(
                    {'detail': lockout_message(remaining), 'locked_for': remaining},
                    status=429, headers={'Retry-After': str(remaining)},
                )
            raise
        from security.login_lockout import record_success
        user = serializer.validated_data['user']
        record_success('username', user.username)
        audit(user, 'login', f'User {user.username} logged in', user.company, 'user', user.id, request=request)
        # No API token is issued here. Authentication for the SPA is the
        # HttpOnly `hrcloudpay_session` cookie set by security.views; a
        # long-lived bearer token in this response was never used by the
        # client, could not be revoked without affecting unrelated sessions,
        # and had no expiry. See SECURITY_OPERATIONS.md.
        return Response({'user': UserSerializer(user).data})


class LogoutView(APIView):
    """
    Revoke the caller's session.

    The SPA authenticates with the `hrcloudpay_session` cookie
    (security.authentication.SecurityCookieAuthentication), so revoking only
    the DRF Token here left the session fully usable after "Log out". Revoke
    whatever the request actually authenticated with, and clear the cookie.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        audit(request.user, 'logout', f'User {request.user.username} logged out', request.user.company, 'user', request.user.id, request=request)

        # Cookie-based session (the SPA path) - request.auth is the SecuritySession.
        session = getattr(request, 'auth', None)
        if isinstance(session, SecuritySession):
            if session.revoked_at is None:
                session.revoked_at = timezone.now()
                session.save(update_fields=['revoked_at'])

        # Token-based session (API clients) - reverse accessor for DRF Token.
        token = getattr(request.user, 'auth_token', None)
        if token:
            token.delete()

        # Django session, for anything that fell back to SessionAuthentication.
        if request.session.session_key:
            request.session.flush()

        response = Response(status=status.HTTP_204_NO_CONTENT)
        response.delete_cookie('hrcloudpay_session')
        return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class CompanyUsersView(APIView):
    """
    Team account management, restricted to owner/admin. This is the
    ONLY way non-owner accounts get created - there is no public signup
    for HR/Finance/Department Manager/Employee logins. An owner/admin
    invites them here, under their own company.
    """
    permission_classes = [IsCompanyMember, IsCompanyActive, IsOwnerOrAdminOnly]

    def get(self, request):
        users = User.objects.filter(company=request.user.company).exclude(role='owner').order_by('username')
        return Response(StaffUserSerializer(users, many=True).data)

    def post(self, request):
        serializer = StaffUserCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        audit(request.user, 'invite', f'Created team account {user.username}', user.company, 'user', user.id, {'role': user.role}, request=request)
        return Response(StaffUserSerializer(user).data, status=status.HTTP_201_CREATED)


class CompanyUserDetailView(APIView):
    """
    Update a staff account's role/department, or deactivate it
    (soft-delete via is_active=False, so audit history is preserved).
    Owner/admin only. The 'owner' account itself cannot be edited here.
    """
    permission_classes = [IsCompanyMember, IsCompanyActive, IsOwnerOrAdminOnly]

    def get_user(self, request, user_id):
        return get_object_or_404(User.objects.exclude(role='owner'), id=user_id, company=request.user.company)

    def patch(self, request, user_id):
        user = self.get_user(request, user_id)
        before = {'role': user.role, 'managed_department': user.managed_department}
        role = request.data.get('role')
        if role:
            if role not in ('admin', 'hr', 'finance', 'department_manager', 'employee'):
                return Response({'detail': 'Invalid role.'}, status=400)
            user.role = role
        if 'managed_department' in request.data:
            user.managed_department = request.data.get('managed_department') or ''
        changes = {k: {'from': before[k], 'to': getattr(user, k)} for k in before if before[k] != getattr(user, k)}
        if changes:
            user.save(update_fields=['role', 'managed_department'])
            audit(request.user, 'permission_change', f'Changed permissions for {user.username}', user.company, 'user', user.id, {'changes': changes}, request=request)
        return Response(StaffUserSerializer(user).data)

    def delete(self, request, user_id):
        user = self.get_user(request, user_id)
        user.is_active = False
        user.save(update_fields=['is_active'])
        audit(request.user, 'permission_change', f'Deactivated user {user.username}', user.company, 'user', user.id, {'is_active': False}, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CompanyAuditLogsView(APIView):
    permission_classes = [IsCompanyMember, IsCompanyActive, CanViewCompanyAudit]

    def get(self, request):
        from .platform_models import AuditLog
        qs = AuditLog.objects.select_related('actor', 'company').filter(company=request.user.company).order_by('-created_at', '-id')
        action = request.query_params.get('action','').strip()
        target_type = request.query_params.get('target_type','').strip()
        actor = request.query_params.get('actor','').strip()
        if action: qs = qs.filter(action=action)
        if target_type: qs = qs.filter(target_type=target_type)
        if actor: qs = qs.filter(Q(actor__username__icontains=actor) | Q(actor__email__icontains=actor))
        try:
            limit = min(max(int(request.query_params.get('limit', '100') or 100), 1), 500)
        except (TypeError, ValueError):
            limit = 100
        rows = []
        for x in qs[:limit]:
            rows.append({'id':x.id,'action':x.action,'message':x.message,'actor':x.actor.username if x.actor else 'System','target_type':x.target_type,'target_id':x.target_id,'metadata':x.metadata,'request_id':x.request_id,'user_agent':x.user_agent,'chain_sequence':x.chain_sequence,'integrity_hash':x.integrity_hash,'created_at':x.created_at})
        return Response(rows)


class PublicFeaturesView(APIView):
    """Authenticated users: which platform features are enabled for their company.

    Returns ``{"features": {key: bool}, "reasons": {key: reason}}`` so the client
    can distinguish a feature that was switched off from one this tenant is not
    yet part of. "reasons" only carries entries for disabled features.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .features import public_feature_status_map, ensure_default_flags
        ensure_default_flags()
        company = getattr(request.user, 'company', None)
        status = public_feature_status_map(company=company)
        return Response({
            'features': {key: value['enabled'] for key, value in status.items()},
            'reasons': {key: value['reason'] for key, value in status.items()
                        if value['reason']},
            'messages': {key: value['message'] for key, value in status.items()
                         if value['message']},
        })


class CompanySettingsView(APIView):
    """
    Company profile for owner/admin: name, address, phone.
    Billing/plan changes live on /auth/billing/, not here. Every action is
    audited and tenant-scoped to the requesting user's company.
    """
    permission_classes = [IsCompanyMember, IsCompanyActive, IsOwnerOrAdminOnly]

    def get(self, request):
        company = request.user.company
        return Response(CompanySerializer(company, context={'request': request}).data)

    def patch(self, request):
        company = request.user.company
        # Only allow textual profile fields here. Logo is a file upload and
        # must go through the multipart CompanyLogoView endpoint instead.
        updatable = {
            k: v for k, v in request.data.items()
            if k in ('name', 'address', 'phone')
        }
        ser = CompanySerializer(
            company, data=updatable, partial=True, context={'request': request}
        )
        ser.is_valid(raise_exception=True)
        tracked = ['name', 'address', 'phone']
        before = snapshot_fields(company, tracked)
        ser.save()

        changes = changed_fields(company, tracked, before=before)
        if changes:
            audit(
                request.user, 'update', 'Updated company profile',
                company, 'company', company.id, {'changes': changes}, request=request,
            )
        return Response(CompanySerializer(company, context={'request': request}).data)


# Keep multipart upload parsing isolated to the logo endpoint, mirroring the
# employee profile-photo pattern in employees/views.py.
class CompanyLogoView(APIView):
    """
    Upload (POST) or remove (DELETE) the company logo.

    The logo is rendered on payslips and break-request forms. Multipart field
    name: ``logo``. Only owner/admin may manage company branding.
    """
    permission_classes = [IsCompanyMember, IsCompanyActive, IsOwnerOrAdminOnly]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        company = request.user.company
        f = request.FILES.get('logo')
        if not f:
            return Response({'detail': 'No file uploaded. Use field name "logo".'},
                            status=status.HTTP_400_BAD_REQUEST)
        name = (getattr(f, 'name', '') or '').lower()
        if not any(name.endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp')):
            return Response({'detail': 'Use a JPG, PNG, GIF, or WebP image.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if getattr(f, 'size', 0) and f.size > 5 * 1024 * 1024:
            return Response({'detail': 'Logo must be 5 MB or smaller.'},
                            status=status.HTTP_400_BAD_REQUEST)

        # Replace any existing logo so old files don't pile up on disk.
        if company.logo:
            company.logo.delete(save=False)
        company.logo = f
        company.save(update_fields=['logo'])

        audit(request.user, 'update', 'Updated company logo',
                company, 'company', company.id, request=request)
        return Response({
            'detail': 'Logo updated.',
            'logo_url': request.build_absolute_uri(company.logo.url),
        })

    def delete(self, request):
        company = request.user.company
        if not company.logo:
            return Response({'detail': 'No logo to remove.', 'logo_url': None})
        company.logo.delete(save=False)
        company.logo = None
        company.save(update_fields=['logo'])
        audit(request.user, 'update', 'Removed company logo',
                company, 'company', company.id, request=request)
        return Response({'detail': 'Logo removed.', 'logo_url': None})
