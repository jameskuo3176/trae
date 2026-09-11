from django.db import migrations


def _table_columns(schema_editor, table):
    with schema_editor.connection.cursor() as cursor:
        description = schema_editor.connection.introspection.get_table_description(
            cursor, table
        )
    return {column.name for column in description}


def _rename_column_if_needed(schema_editor, table, old_name, new_name):
    tables = schema_editor.connection.introspection.table_names()
    if table not in tables:
        return

    columns = _table_columns(schema_editor, table)
    if old_name in columns and new_name not in columns:
        quote = schema_editor.quote_name
        schema_editor.execute(
            f'ALTER TABLE {quote(table)} '
            f'RENAME COLUMN {quote(old_name)} TO {quote(new_name)}'
        )


def repair_foreign_key_column_names(apps, schema_editor):
    """Repair databases where the original 0002 SQLite-only SQL was skipped."""
    _rename_column_if_needed(
        schema_editor, 'projects', 'locked_by_id', 'locked_by'
    )
    _rename_column_if_needed(
        schema_editor, 'projects', 'hidden_by_id', 'hidden_by'
    )
    _rename_column_if_needed(
        schema_editor, 'data_locks', 'locked_by_id', 'locked_by'
    )


class Migration(migrations.Migration):
    dependencies = [('core', '0010_recordriskassessment')]

    operations = [
        migrations.RunPython(repair_foreign_key_column_names, migrations.RunPython.noop),
    ]
