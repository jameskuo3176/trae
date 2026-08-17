import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0004_repair_backup_user_column')]

    operations = [
        migrations.CreateModel(
            name='RecordAnnotation',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('text', models.TextField(blank=True, default='')),
                ('author_id', models.IntegerField()),
                ('editor_id', models.IntegerField()),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(default=django.utils.timezone.now)),
                (
                    'qor_record',
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='annotation',
                        to='core.qorrecord',
                    ),
                ),
            ],
            options={'db_table': 'record_annotations'},
        ),
        migrations.CreateModel(
            name='RecordAnnotationImage',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('filename', models.CharField(max_length=180)),
                ('content_type', models.CharField(max_length=32)),
                ('byte_size', models.PositiveIntegerField()),
                ('checksum', models.CharField(max_length=64)),
                ('content', models.BinaryField()),
                ('uploaded_by', models.IntegerField()),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                (
                    'annotation',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='images',
                        to='core.recordannotation',
                    ),
                ),
            ],
            options={
                'db_table': 'record_annotation_images',
                'ordering': ('id',),
            },
        ),
    ]
