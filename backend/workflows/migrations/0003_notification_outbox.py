from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0027_legal_pages'),
        ('workflows', '0002_alter_hrnotification_options_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='NotificationPreference',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email_enabled', models.BooleanField(default=False)),
                ('leave_events', models.BooleanField(default=True)),
                ('payroll_events', models.BooleanField(default=True)),
                ('hr_events', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='notification_preferences', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='NotificationDelivery',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254)),
                ('subject', models.CharField(max_length=255)),
                ('body', models.TextField()),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('processing', 'Processing'), ('sent', 'Sent'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('attempts', models.PositiveIntegerField(default=0)),
                ('next_attempt_at', models.DateTimeField(default=timezone.now)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('last_error', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('notification', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='deliveries', to='workflows.hrnotification')),
                ('recipient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notification_deliveries', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['created_at']},
        ),
        migrations.AddConstraint(
            model_name='notificationdelivery',
            constraint=models.UniqueConstraint(fields=('notification', 'recipient'), name='unique_notification_delivery_recipient'),
        ),
        migrations.AddIndex(
            model_name='notificationdelivery',
            index=models.Index(fields=['status', 'next_attempt_at'], name='workflows_n_status_dc4eec_idx'),
        ),
    ]
