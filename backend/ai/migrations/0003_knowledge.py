from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('ai','0002_aidraft')]
    operations = [
        migrations.CreateModel(
            name='KnowledgeDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('description', models.CharField(blank=True, max_length=500)),
                ('source_type', models.CharField(choices=[('policy','HR policy'),('handbook','Employee handbook'),('contract_template','Contract template'),('guide','HR guide'),('other','Other')], default='other', max_length=30)),
                ('content', models.TextField()),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ai_knowledge_documents', to='accounts.company')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='created_ai_knowledge_documents', to='accounts.user')),
            ],
            options={'ordering':['-updated_at','-id']},
        ),
        migrations.CreateModel(
            name='KnowledgeChunk',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content', models.TextField()),
                ('chunk_index', models.PositiveIntegerField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('document', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chunks', to='ai.knowledgedocument')),
            ],
            options={'ordering':['document_id','chunk_index'], 'unique_together':{('document','chunk_index')}},
        ),
        migrations.AddIndex(model_name='knowledgedocument', index=models.Index(fields=['company','is_active','-updated_at'], name='ai_knowled_company_8a7a3f_idx')),
    ]
