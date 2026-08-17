from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0007_reviewsnapshot_schema_version_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='groupreview',
            name='snapshot_id',
            field=models.IntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='groupreview',
            name='snapshot_checksum',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='groupreview',
            name='snapshot_week_start',
            field=models.DateField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='groupreview',
            name='snapshot_schema_version',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='groupreview',
            name='snapshot_config_version',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='groupreview',
            name='snapshot_data',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='groupreview',
            name='submission_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='groupreview',
            name='resubmitted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='subsystemreview',
            name='snapshot_id',
            field=models.IntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='subsystemreview',
            name='snapshot_checksum',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='subsystemreview',
            name='snapshot_week_start',
            field=models.DateField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='subsystemreview',
            name='snapshot_schema_version',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='subsystemreview',
            name='snapshot_config_version',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='subsystemreview',
            name='snapshot_data',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='subsystemreview',
            name='submission_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='subsystemreview',
            name='resubmitted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
