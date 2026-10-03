from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0008_subscription_status_choices')]
    operations = [
        migrations.AddField(model_name='subscription', name='current_period_start', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='subscription', name='current_period_end', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='subscription', name='cancel_at_period_end', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='subscription', name='cancellation_reason', field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name='subscription', name='last_payment_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='subscription', name='failed_payment_count', field=models.PositiveIntegerField(default=0)),
        migrations.CreateModel(
            name='BillingInvoice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('number', models.CharField(max_length=60, unique=True)),
                ('plan', models.CharField(max_length=20)),
                ('billing_cycle', models.CharField(max_length=10)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('currency', models.CharField(max_length=10)),
                ('status', models.CharField(choices=[('issued','Issued'),('paid','Paid'),('void','Void')], default='issued', max_length=12)),
                ('issued_at', models.DateTimeField(auto_now_add=True)),
                ('paid_at', models.DateTimeField(blank=True, null=True)),
                ('period_start', models.DateTimeField(blank=True, null=True)),
                ('period_end', models.DateTimeField(blank=True, null=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('company', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='billing_invoices', to='accounts.company')),
                ('subscription', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='billing_invoices', to='accounts.subscription')),
                ('transaction', models.OneToOneField(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name='invoice', to='accounts.paymenttransaction')),
            ],
            options={'ordering':['-issued_at'], 'indexes':[models.Index(fields=['company','-issued_at'], name='accounts_bil_company_4a0e2f_idx')]},
        ),
    ]
