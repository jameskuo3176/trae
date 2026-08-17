from django.db import migrations


def repair_weekly_selection_source(apps, schema_editor):
    """Repair databases where 0007 was recorded without adding the column."""
    if schema_editor.connection.alias != 'default':
        return

    model = apps.get_model('core', 'WeeklyRunSelection')
    table = model._meta.db_table
    tables = set(schema_editor.connection.introspection.table_names())
    if table not in tables:
        return

    with schema_editor.connection.cursor() as cursor:
        columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor, table,
            )
        }
    field = model._meta.get_field('source')
    if field.column not in columns:
        schema_editor.add_field(model, field)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0008_review_snapshot_binding'),
    ]

    operations = [
        migrations.RunPython(
            repair_weekly_selection_source,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
