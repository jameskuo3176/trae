from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0002_global_modules'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReviewGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True, default='')),
                ('config_version', models.CharField(blank=True, default='', max_length=64)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='owned_review_groups', to=settings.AUTH_USER_MODEL)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='review_groups', to='core.project')),
            ],
            options={'db_table': 'review_groups'},
        ),
        migrations.CreateModel(
            name='WeeklyRunSelection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('week_start', models.DateField(db_index=True)),
                ('record_id', models.CharField(max_length=64)),
                ('explicit', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('module', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='weekly_run_selections', to='core.globalmodule')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='weekly_run_selections', to='core.project')),
                ('selected_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='weekly_run_selections', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'weekly_run_selections'},
        ),
        migrations.CreateModel(
            name='ReviewGroupModule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='module_links', to='core.reviewgroup')),
                ('project_module', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='review_group_link', to='core.projectmodule')),
            ],
            options={'db_table': 'review_group_modules'},
        ),
        migrations.AddConstraint(
            model_name='reviewgroup',
            constraint=models.UniqueConstraint(fields=('project', 'name'), name='uq_project_review_group'),
        ),
        migrations.AddConstraint(
            model_name='weeklyrunselection',
            constraint=models.UniqueConstraint(fields=('project', 'module', 'week_start'), name='uq_project_module_weekly_run'),
        ),
    ]
