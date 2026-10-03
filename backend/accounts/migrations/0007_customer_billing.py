from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('accounts','0006_billing_and_payment_providers')]
    operations = [
        migrations.CreateModel(
            name='PaymentPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(max_length=30)),
                ('plan', models.CharField(max_length=20)),
                ('billing_cycle', models.CharField(max_length=10)),
                ('currency', models.CharField(max_length=10)),
                ('external_plan_id', models.CharField(max_length=150)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'unique_together': {('provider','plan','billing_cycle','currency')}},
        ),
        migrations.CreateModel(
            name='PaymentTransaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(max_length=30)),
                ('reference', models.CharField(max_length=120, unique=True)),
                ('provider_transaction_id', models.CharField(blank=True, max_length=150)),
                ('plan', models.CharField(max_length=20)),
                ('billing_cycle', models.CharField(max_length=10)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('currency', models.CharField(max_length=10)),
                ('status', models.CharField(choices=[('pending','Pending'),('paid','Paid'),('failed','Failed'),('cancelled','Cancelled')], default='pending', max_length=20)),
                ('checkout_url', models.URLField(blank=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('paid_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payment_transactions', to='accounts.company')),
                ('subscription', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payment_transactions', to='accounts.subscription')),
            ],
            options={'ordering':['-created_at']},
        ),
    ]
