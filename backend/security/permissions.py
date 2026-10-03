from rest_framework.permissions import BasePermission
class IsITSecurityAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and request.user.role in ('owner','admin'))
class IsPrivileged(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and request.user.role in ('owner','admin'))
