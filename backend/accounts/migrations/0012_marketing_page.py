from django.db import migrations, models
import django.db.models.deletion


def seed_pages(apps, schema_editor):
    MarketingPage = apps.get_model('accounts', 'MarketingPage')
    MarketingPage.objects.get_or_create(slug='home', defaults={'name': 'Homepage', 'content': {}})
    MarketingPage.objects.get_or_create(slug='security', defaults={'name': 'Security & Trust', 'content': {}})


class Migration(migrations.Migration):
    dependencies = [('accounts', '0011_company_logo')]

    operations = [
        migrations.CreateModel(
            name='MarketingPage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.SlugField(max_length=80, unique=True)),
                ('name', models.CharField(max_length=160)),
                ('content', models.JSONField(blank=True, default=dict)),
                ('is_published', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='marketing_pages_updated', to='accounts.user')),
            ],
            options={'ordering': ['name']},
        ),
        migrations.RunPython(seed_pages, migrations.RunPython.noop),
    ]
