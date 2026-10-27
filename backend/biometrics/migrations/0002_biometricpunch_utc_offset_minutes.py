from django.db import migrations, models


class Migration(migrations.Migration):
    """Remember the offset each device reported its clock in.

    ``punch_time`` is stored as an instant, which is what orders punches
    correctly, but it is not what attendance is made of: a shift is "08:00 at
    the Accra terminal". Without the offset, any punch read back from the
    database is a UTC instant and its wall clock is gone - so reprocessing a
    stored punch (reconciliation) would write 06:00 for that same arrival.

    Existing rows keep NULL: their offset was never recorded and cannot be
    recovered, so they retain the previous behaviour rather than being given a
    guess.
    """

    dependencies = [
        ('biometrics', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='biometricpunch',
            name='utc_offset_minutes',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
