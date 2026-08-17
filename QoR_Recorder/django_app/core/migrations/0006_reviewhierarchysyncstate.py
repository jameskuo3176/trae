from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0005_record_annotations'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReviewHierarchySyncState',
            fields=[
                ('singleton', models.PositiveSmallIntegerField(
                    default=1, editable=False, primary_key=True, serialize=False,
                )),
                ('config_path', models.TextField(blank=True, default='')),
                ('config_version', models.CharField(blank=True, default='', max_length=64)),
                ('config_checksum', models.CharField(blank=True, default='', max_length=64)),
                ('applied_at', models.DateTimeField(blank=True, null=True)),
                ('summary', models.JSONField(blank=True, default=dict)),
            ],
            options={'db_table': 'review_hierarchy_sync_state'},
        ),
    ]
