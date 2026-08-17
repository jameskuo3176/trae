from django.db import migrations


def repair_backup_user_column(apps, schema_editor):
    BackupRecord = apps.get_model('core', 'BackupRecord')
    table = BackupRecord._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor, table,
            )
        }
    field = BackupRecord._meta.get_field('user')
    if field.column not in columns:
        schema_editor.add_field(BackupRecord, field)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0003_review_hierarchy'),
    ]

    operations = [
        migrations.RunPython(repair_backup_user_column, migrations.RunPython.noop),
    ]
