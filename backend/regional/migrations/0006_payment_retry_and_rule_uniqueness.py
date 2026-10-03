from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('regional', '0005_statutory_filing_workflow_states'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='statutoryrule',
            constraint=models.UniqueConstraint(
                fields=['country_code', 'code', 'effective_from'],
                name='unique_country_rule_effective',
            ),
        ),
        migrations.AlterField(
            model_name='statutoryfilingpayment',
            name='filing',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='payments',
                to='regional.statutoryfiling',
            ),
        ),
        migrations.AddIndex(
            model_name='statutoryfilingpayment',
            index=models.Index(fields=['filing', 'status'], name='regional_pa_filing__idx'),
        ),
        migrations.AddConstraint(
            model_name='statutoryfilingpayment',
            constraint=models.UniqueConstraint(
                condition=models.Q(status='paid'),
                fields=['filing'],
                name='unique_paid_payment_per_filing',
            ),
        ),
    ]
