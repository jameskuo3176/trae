from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def _table_columns(schema_editor, table):
    with schema_editor.connection.cursor() as cursor:
        return {row[1] for row in cursor.execute(f'PRAGMA table_info({table})')}


def _rename_column_if_needed(schema_editor, table, old_name, new_name):
    cols = _table_columns(schema_editor, table)
    if old_name in cols and new_name not in cols:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                f'ALTER TABLE {table} RENAME COLUMN {old_name} TO {new_name}'
            )


def align_flask_compatible_columns(apps, schema_editor):
    """Backfill NULLs and align FK column names for Flask-era SQLite schemas.

    Fresh installs from 0001 create locked_by_id/hidden_by_id; models require
    physical columns locked_by/hidden_by. Existing Flask DBs already use the
    short names, so renames are skipped when already present.
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "UPDATE projects SET lock_reason = '' WHERE lock_reason IS NULL"
        )
    _rename_column_if_needed(schema_editor, 'projects', 'locked_by_id', 'locked_by')
    _rename_column_if_needed(schema_editor, 'projects', 'hidden_by_id', 'hidden_by')
    if 'data_locks' in schema_editor.connection.introspection.table_names():
        _rename_column_if_needed(schema_editor, 'data_locks', 'locked_by_id', 'locked_by')


def noop_reverse(apps, schema_editor):
    return None


class Migration(migrations.Migration):
    dependencies = [('core', '0001_initial')]

    operations = [
        # Avoid SQLite table remakes for FK db_column alignment; they break on
        # Flask-era projects rows. Update state and rename columns explicitly.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='project',
                    name='locked_by',
                    field=models.ForeignKey(
                        blank=True,
                        db_column='locked_by',
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='locked_projects',
                        to='core.user',
                    ),
                ),
                migrations.AlterField(
                    model_name='project',
                    name='hidden_by',
                    field=models.ForeignKey(
                        blank=True,
                        db_column='hidden_by',
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='hidden_projects',
                        to='core.user',
                    ),
                ),
                migrations.AlterField(
                    model_name='datalock',
                    name='locked_by',
                    field=models.ForeignKey(
                        db_column='locked_by',
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='locks',
                        to='core.user',
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(align_flask_compatible_columns, noop_reverse),
            ],
        ),
        migrations.CreateModel(
            name='GlobalModule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('normalized_name', models.CharField(db_index=True, max_length=200, unique=True)),
                ('description', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={'db_table': 'global_modules', 'ordering': ('normalized_name',)},
        ),
        migrations.CreateModel(
            name='ProjectModule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('owner_id', models.IntegerField(blank=True, db_index=True, null=True)),
                ('collaborators', models.TextField(default='[]')),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('module', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='project_links', to='core.globalmodule')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='module_links', to='core.project')),
            ],
            options={'db_table': 'project_modules'},
        ),
        migrations.CreateModel(
            name='LegacyModuleMapping',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('legacy_module_id', models.BigIntegerField()),
                ('legacy_name', models.CharField(max_length=200)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('module', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='legacy_mappings', to='core.globalmodule')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='legacy_module_mappings', to='core.project')),
            ],
            options={'db_table': 'legacy_module_mappings'},
        ),
        migrations.AddConstraint(
            model_name='projectmodule',
            constraint=models.UniqueConstraint(fields=('project', 'module'), name='uq_project_global_module'),
        ),
        migrations.AddConstraint(
            model_name='legacymodulemapping',
            constraint=models.UniqueConstraint(fields=('project', 'legacy_module_id'), name='uq_project_legacy_module'),
        ),
    ]
