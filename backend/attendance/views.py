from datetime import date as date_cls

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import CanManageHROrDepartment, IsCompanyActive, IsCompanyMember
from accounts.audit import audit, changed_fields, snapshot_fields

from .models import STATUS_CHOICES, Attendance
from .serializers import AttendanceSerializer

TRACKED = ['date', 'check_in', 'check_out', 'crossed_midnight', 'status', 'notes']


class AttendanceMonthGridView(APIView):
    """One row per employee, one column per day, for a calendar view.

    Distinct from `records/` because a grid is not a list of records and cannot
    be assembled by paginating one. A month of records for a hundred employees
    is three thousand rows; asking the client to stitch that into a grid would
    move the work to the slowest part of the system and cap the month at whatever
    the page size happened to be.

    The query is one per employee for the whole month, not one per cell, so the
    number of round trips is proportional to headcount rather than to
    headcount x days.
    """

    permission_classes = [IsCompanyMember, IsCompanyActive]

    def get(self, request):
        from datetime import date as _date

        from django.db.models import Q

        from employees.models import Employee

        from .grid import (
            DEFAULT_EXPECTED_HOURS,
            DEFAULT_GRACE_MINUTES,
            STATUS_LABELS,
            day_cells,
            month_bounds,
            summarise,
        )

        now = _date.today()
        try:
            year = int(request.query_params.get('year', now.year))
            month = int(request.query_params.get('month', now.month))
            start, end = month_bounds(year, month)
        except (TypeError, ValueError):
            return Response({'detail': 'year and month must be whole numbers.'},
                            status=400)
        if not 1 <= month <= 12:
            return Response({'detail': 'month must be between 1 and 12.'},
                            status=400)

        try:
            expected_hours = float(
                request.query_params.get('expected_hours', DEFAULT_EXPECTED_HOURS))
        except (TypeError, ValueError):
            return Response({'detail': 'expected_hours must be a number.'},
                            status=400)

        company = request.user.company
        employees = Employee.objects.filter(company=company)
        department = request.query_params.get('department', '').strip()
        if department:
            employees = employees.filter(
                Q(department__iexact=department) | Q(department_obj__name__iexact=department))
        employee_id = request.query_params.get('employee', '').strip()
        if employee_id:
            employees = employees.filter(id=employee_id)

        records = {}
        for record in Attendance.objects.filter(
                employee__company=company, date__range=(start, end)).select_related('employee'):
            records.setdefault(record.employee_id, {})[record.date.isoformat()] = record

        rows = []
        for employee in employees.select_related('department_obj'):
            cells = day_cells(
                start, end, records.get(employee.id, {}),
                expected_hours=expected_hours,
                grace_minutes=DEFAULT_GRACE_MINUTES,
            )
            rows.append({
                'employee': {
                    'id': employee.id,
                    'name': employee.full_name,
                    'employee_code': employee.employee_code,
                    'department': (employee.effective_department
                                   if hasattr(employee, 'effective_department')
                                   else employee.department),
                    'job_title': employee.job_title,
                },
                'days': [cell.as_dict() for cell in cells],
                'summary': summarise(cells),
            })

        return Response({
            'year': year,
            'month': month,
            'start': start.isoformat(),
            'end': end.isoformat(),
            'expected_hours': expected_hours,
            'status_labels': STATUS_LABELS,
            'rows': rows,
        })


class AttendanceViewSet(viewsets.ModelViewSet):
    serializer_class = AttendanceSerializer
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManageHROrDepartment]

    def get_queryset(self):
        """Company-scoped always, then narrowed by role. Deny by default.

        The employee branch used to be guarded by `hasattr(user,
        'employee_profile')`, which is False for an account with no linked
        Employee row. That made the whole branch - including its queryset
        filter - disappear, so such an account fell through to the unfiltered
        company queryset and saw every attendance record in the tenant. Writes
        were still blocked by CanManageHROrDepartment, which is why this was a
        read leak and not a write one.

        Now an employee with no profile matches nothing. An unlinked account is
        a provisioning mistake, and the safe reading of it is "no records",
        never "all records".
        """
        user = self.request.user
        qs = Attendance.objects.filter(employee__company=user.company)

        if user.role == 'employee':
            profile_id = user.employee_id
            return qs.filter(employee_id=profile_id) if profile_id else qs.none()

        if user.role == 'department_manager':
            if not user.managed_department:
                return qs.none()
            return qs.filter(employee__department=user.managed_department)

        employee_id = self.request.query_params.get('employee')
        if employee_id:
            qs = qs.filter(employee_id=employee_id)

        start = self.request.query_params.get('start')
        end = self.request.query_params.get('end')
        if start:
            qs = qs.filter(date__gte=start)
        if end:
            qs = qs.filter(date__lte=end)

        return qs

    def perform_create(self, serializer):
        # The employee is validated against the caller's company in the
        # serializer, so there is nothing left to look up here. The previous
        # unguarded Employee.objects.get() was what turned a cross-tenant id
        # into a 500.
        obj = serializer.save()
        audit(
            self.request.user, 'create',
            f'Recorded attendance for {obj.employee.full_name}',
            obj.employee.company, 'attendance', obj.id,
            {'date': str(obj.date), 'status': obj.status},
            request=self.request,
        )

    def perform_update(self, serializer):
        before = snapshot_fields(serializer.instance, TRACKED)
        obj = serializer.save()
        changes = changed_fields(obj, TRACKED, before=before)
        audit(
            self.request.user, 'update',
            f'Updated attendance for {obj.employee.full_name}',
            obj.employee.company, 'attendance', obj.id,
            {'changes': changes},
            request=self.request,
        )

    def perform_destroy(self, instance):
        audit(
            self.request.user, 'delete',
            f'Deleted attendance for {instance.employee.full_name}',
            instance.employee.company, 'attendance', instance.id,
            {'date': str(instance.date)},
            request=self.request,
        )
        instance.delete()


class BulkMarkView(APIView):
    """Mark a date for many employees in one call.

    Marking a whole department present is the everyday clerical case: twenty-odd
    rows that would otherwise be twenty-odd form submissions.

    Three decisions:

    **Existing records are skipped, never overwritten.** Someone who clocked in
    at 08:58 has real hours in that row. A bulk mark that flipped them to
    `absent` would destroy the clock times and leave an attendance trail that
    says they never arrived. The response says how many were skipped so the
    mismatch is visible rather than inferred.

    **Out-of-scope employees reject the whole batch.** Taking 19 of 20 and
    failing on the 20th is worse than doing nothing: the caller cannot tell
    which half took effect. This is all-or-nothing inside a transaction.

    **One audit row for the batch, naming the ids.** Twenty individual rows
    would bury the action; one row that cannot say who it touched would be
    useless. It does both.
    """

    permission_classes = [IsCompanyMember, IsCompanyActive]

    def post(self, request):
        from employees.models import Employee

        user = request.user
        # Batch marking is an HR action. An employee could already write their
        # own record through the viewset, so allowing it here adds no reach -
        # but it would let anyone mark a batch of one, which is a confusing way
        # to do something the clock action already does properly.
        if user.role == 'employee':
            raise PermissionDenied(
                'Only HR, an owner, or a department manager can mark attendance '
                'in bulk. Employees can clock in for themselves.')
        if user.role == 'department_manager' and not user.managed_department:
            # Without this the department filter matches nothing and the
            # response is an empty success - which reads as "nobody in your
            # department was marked" rather than "your account is not set up".
            raise PermissionDenied(
                'Your account has no department set, so there is no team whose '
                'attendance you can mark. Ask an owner or admin to set it on the '
                'Team page - it has to match an employee department exactly.')
        payload = request.data
        try:
            day = date_cls.fromisoformat(str(payload.get('date', '')))
        except ValueError:
            raise ValidationError({'date': 'Required as YYYY-MM-DD.'})
        status = payload.get('status')
        if status not in dict(STATUS_CHOICES):
            raise ValidationError({
                'status': f'Must be one of: {", ".join(dict(STATUS_CHOICES))}.',
            })

        ids = payload.get('employee_ids') or []
        department = payload.get('department')
        if not ids and not department:
            raise ValidationError({
                'detail': 'Give employee_ids, a department, or both.',
            })

        employees = Employee.objects.filter(company=user.company)
        if ids:
            employees = employees.filter(id__in=ids)
            if employees.count() != len(set(ids)):
                # Either an unknown id or one belonging to another tenant. Both
                # are refused the same way, so this is not a probe for which
                # employee ids exist elsewhere.
                raise ValidationError({
                    'employee_ids': 'One or more employees are not in your company.',
                })
        if department:
            employees = employees.filter(department=department)

        employees = list(employees.order_by('id'))
        if not employees:
            return Response({'created': [], 'created_count': 0,
                             'skipped_existing': 0, 'skipped_existing_ids': []})

        # All-or-nothing: 19 of 20 applied with the 20th refused leaves the
        # caller unable to tell which half took effect.
        rule = CanManageHROrDepartment()
        if not all(rule.employee_in_scope(request, e) for e in employees):
            raise PermissionDenied('You cannot record attendance for all of these employees.')

        existing = set(
            Attendance.objects.filter(
                employee__in=employees, date=day,
            ).values_list('employee_id', flat=True)
        )

        created, skipped = [], []
        with transaction.atomic():
            for employee in employees:
                if employee.id in existing:
                    skipped.append(employee.id)
                    continue
                record = Attendance.objects.create(
                    employee=employee, date=day, status=status,
                    notes=f'Bulk marked as {status}',
                )
                created.append(record)

        if created:
            audit(
                request.user, 'create',
                f'Bulk marked {len(created)} employees as {status} for {day}',
                user.company, 'attendance', '',
                {
                    'date': str(day),
                    'status': status,
                    'department': department or '',
                    'created_ids': [r.id for r in created],
                    'employee_ids': [r.employee_id for r in created],
                    'skipped_existing_ids': skipped,
                },
                request=request,
            )

        return Response({
            'created': [{'id': r.id, 'employee_id': r.employee_id,
                         'employee': r.employee.full_name} for r in created],
            'created_count': len(created),
            'skipped_existing': len(skipped),
            'skipped_existing_ids': skipped,
        }, status=201)


class ClockView(APIView):
    """Clock in and clock out, for yourself or on someone's behalf.

    Two design points that are not obvious:

    **Clock-out finds the open record, not today's.** Someone who clocks in at
    22:00 clocks out at 06:00 the next morning, and that shift belongs to the
    day they started. Looking up "today" would refuse the clock-out and leave
    the shift permanently open, so the record is found by "has a check-in and no
    check-out" instead.

    **A second clock-in is refused rather than silently replacing the first.**
    Re-clocking in over a forgotten open record would destroy real hours and
    leave no trace, which is the kind of quiet data loss that only surfaces at
    payroll.

    Scope reuses `CanManageHROrDepartment.employee_in_scope` rather than
    re-deciding who may mark whom: an employee can only clock themselves, and
    the roles that manage attendance keep the reach they already had.
    """

    permission_classes = [IsCompanyMember, IsCompanyActive]

    def _target_employee(self, request):
        from accounts.permissions import CanManageHROrDepartment
        from employees.models import Employee

        user = request.user
        if user.role == 'employee':
            profile_id = user.employee_id
            if not profile_id:
                raise ValidationError({
                    'detail': 'This account is not linked to an employee record, '
                              'so there is nothing to clock in for.',
                })
            employee = Employee.objects.filter(id=profile_id).first()
            if employee is None:
                raise ValidationError({
                    'detail': 'This account is not linked to an employee record.',
                })
            # Refuse rather than quietly clock in the caller instead. Silently
            # ignoring the id would return 201 and record the wrong person,
            # which is how a client's bug becomes a payroll correction.
            supplied = request.data.get('employee')
            if supplied not in (None, '', employee.id, str(employee.id)):
                raise ValidationError({
                    'employee': 'You can only clock in for yourself.',
                })
            return employee

        employee_id = request.data.get('employee')
        if not employee_id:
            raise ValidationError({
                'employee': 'Required when clocking on behalf of someone else.',
            })
        employee = Employee.objects.filter(
            id=employee_id, company=user.company).first()
        if employee is None:
            raise ValidationError({'employee': 'Unknown employee.'})
        if not CanManageHROrDepartment().employee_in_scope(request, employee):
            raise PermissionDenied('You cannot record attendance for this employee.')
        return employee

    def post(self, request):
        action = request.data.get('action')
        if action not in ('clock_in', 'clock_out'):
            raise ValidationError({
                'action': 'Must be clock_in or clock_out.',
            })
        employee = self._target_employee(request)
        now = timezone.localtime() if timezone.is_aware(timezone.now()) else timezone.now()
        today = now.date()
        current_time = now.time().replace(tzinfo=None)

        if action == 'clock_in':
            already_today = Attendance.objects.filter(
                employee=employee, date=today).first()
            if already_today is not None:
                raise ValidationError({
                    'detail': f'{employee.full_name} already has a record for '
                              f'{today}. Edit it rather than clocking in again.',
                })
            record = Attendance.objects.create(
                employee=employee, date=today, status='present',
                check_in=current_time,
                notes='Clocked in',
            )
            audit(
                request.user, 'create',
                f'Clocked in {employee.full_name}',
                employee.company, 'attendance', record.id,
                {'date': str(record.date), 'check_in': str(current_time)},
                request=request,
            )
            return Response(AttendanceSerializer(record).data, status=201)

        # clock_out: the open record, which may not be today's.
        open_record = Attendance.objects.filter(
            employee=employee, check_in__isnull=False, check_out__isnull=True,
        ).order_by('-date').first()
        if open_record is None:
            raise ValidationError({
                'detail': f'{employee.full_name} has no open shift to clock out of.',
            })
        # Earlier than the check-in means the shift ended the next day. Without
        # this the serializer would reject it, because a bare 22:00 -> 06:00 is
        # indistinguishable from a typo until somebody says which it is.
        crossed = current_time < open_record.check_in
        open_record.check_out = current_time
        open_record.crossed_midnight = crossed
        open_record.save(update_fields=['check_out', 'crossed_midnight'])
        audit(
            request.user, 'update',
            f'Clocked out {employee.full_name}',
            employee.company, 'attendance', open_record.id,
            {
                'date': str(open_record.date),
                'check_out': str(current_time),
                'crossed_midnight': crossed,
            },
            request=request,
        )
        return Response(AttendanceSerializer(open_record).data, status=200)