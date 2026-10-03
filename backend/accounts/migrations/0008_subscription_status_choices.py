from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('accounts','0007_customer_billing')]
    operations = [
        migrations.AlterField(
            model_name='subscription', name='status',
            field=models.CharField(choices=[('trial','Trial'),('active','Active'),('past_due','Past due'),('cancelled','Cancelled'),('grace','Grace'),('expired','Expired')], default='trial', max_length=20),
        ),
    ]
