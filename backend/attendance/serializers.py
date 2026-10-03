from rest_framework import serializers

from .models import Attendance


class AttendanceSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)
    worked_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = Attendance
        fields = [
            'id', 'employee', 'employee_name', 'date', 'check_in', 'check_out',
            'crossed_midnight', 'worked_minutes', 'status', 'notes',
        ]

    def validate(self, attrs):
        """Reject what the database would happily store.

        Every rule here exists because the alternative is a row that looks
        valid and means something wrong. A 400 at write time is recoverable; a
        31-hour shift in next month's payroll is not.
        """
        request = self.context.get('request')

        # --- tenant isolation ------------------------------------------------
        # The `employee` PrimaryKeyRelatedField accepts any Employee id in the
        # database. The view used to re-fetch it scoped to the caller's company
        # and let Employee.DoesNotExist escape, so an owner/admin/hr posting
        # another tenant's employee id produced a 500 - which both looks like a
        # server fault and works as an existence oracle: 500 means "that id
        # exists somewhere", 400 means "no such id". Validating here covers
        # create *and* update, including a PATCH that reassigns an existing
        # record to a foreign employee.
        employee = attrs.get('employee') or getattr(self.instance, 'employee', None)
        if request is not None and employee is not None:
            if getattr(employee, 'company_id', None) != request.user.company_id:
                raise serializers.ValidationError({
                    'employee': 'That employee does not belong to your company.',
                })

        # --- check-in / check-out -------------------------------------------
        check_in = attrs.get('check_in', getattr(self.instance, 'check_in', None))
        check_out = attrs.get('check_out', getattr(self.instance, 'check_out', None))
        crossed = attrs.get('crossed_midnight', getattr(self.instance, 'crossed_midnight', False))

        if check_out and not check_in:
            raise serializers.ValidationError({
                'check_out': 'A check-out needs a check-in on the same record.',
            })

        if check_in and check_out:
            if crossed and check_out > check_in:
                raise serializers.ValidationError({
                    'crossed_midnight': (
                        'Marked as crossing midnight, but the check-out is later '
                        'than the check-in on the same day.'
                    ),
                })
            if not crossed and check_out < check_in:
                raise serializers.ValidationError({
                    'check_out': (
                        'The check-out is earlier than the check-in. If this is a '
                        'shift that ends the next day, set crossed_midnight.'
                    ),
                })

        return attrs