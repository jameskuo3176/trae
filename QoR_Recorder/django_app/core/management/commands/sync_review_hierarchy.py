from django.core.management.base import BaseCommand, CommandError

from django_app.services.review_hierarchy import (
    DEFAULT_CONFIG_PATH,
    HierarchyConfigError,
    build_sync_plan,
    load_hierarchy,
    sync_hierarchy,
    validate_hierarchy,
)


class Command(BaseCommand):
    help = 'Validate or synchronize Project/Group/Module review ownership from YAML.'

    def add_arguments(self, parser):
        parser.add_argument('--config', default=str(DEFAULT_CONFIG_PATH))
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--check', action='store_true', help='Validate and show DB diff; write nothing.')
        mode.add_argument('--apply', action='store_true', help='Apply validated configuration.')

    def handle(self, *args, **options):
        try:
            data, config_version = load_hierarchy(options['config'])
            errors, resolved = validate_hierarchy(data)
        except HierarchyConfigError as exc:
            raise CommandError(str(exc)) from exc
        if errors:
            raise CommandError('\n'.join(errors))
        if options['check']:
            plan = build_sync_plan(data, config_version, resolved)
            self.stdout.write(self.style.SUCCESS(
                f'Hierarchy is valid (version {config_version[:12]}). '
                f'Dry check: {plan["total_changes"]} DB change(s); zero writes.'
            ))
            self.stdout.write(self._summary(plan))
            return
        try:
            plan = sync_hierarchy(data, config_version, options['config'])
        except HierarchyConfigError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f'Applied hierarchy version {config_version[:12]}: '
            f'{plan["total_changes"]} DB change(s).'
        ))
        self.stdout.write(self._summary(plan))

    @staticmethod
    def _summary(plan):
        desired = plan['desired']
        changes = ', '.join(
            f'{name}={count}' for name, count in plan['changes'].items() if count
        ) or 'none'
        return (
            f'Desired projects={desired["projects"]}, groups={desired["groups"]}, '
            f'modules={desired["modules"]}; changes: {changes}'
        )
