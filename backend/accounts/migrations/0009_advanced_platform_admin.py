from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0008_subscription_status_choices')]

    operations = [
        migrations.CreateModel(
            name='FeatureFlag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.SlugField(max_length=100, unique=True)),
                ('name', models.CharField(max_length=160)),
                ('description', models.TextField(blank=True)),
                ('enabled', models.BooleanField(default=False)),
                ('rollout_percent', models.PositiveSmallIntegerField(default=100)),
                ('environment', models.CharField(choices=[('all', 'All'), ('test', 'Test'), ('live', 'Live')], default='all', max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['name']},
        ),
    ]
