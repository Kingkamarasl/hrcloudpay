from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    """Track when the current idempotent attempt started.

    ``created_at`` records when a key was first seen, which is not enough to
    distinguish a request that is still running from one whose worker crashed
    before ``complete()``. Without that distinction a crashed attempt held the
    key forever and every retry returned 409.

    Existing rows are treated as freshly started: they predate the field and a
    deploy is the wrong moment to let a retry duplicate work.
    """

    dependencies = [
        ('accounts', '0028_idempotencyrecord'),
    ]

    operations = [
        migrations.AddField(
            model_name='idempotencyrecord',
            name='started_at',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
    ]
