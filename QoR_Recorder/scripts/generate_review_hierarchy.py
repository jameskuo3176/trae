#!/usr/bin/env python3
"""Generate one project's review_hierarchy.yaml fragment from owner/module lines.

Each line assigns modules to a group. The left-hand name is both the group key
and the group's owner / each module's release_owner.

Input (one group per line)::

    OWNER_NAME1 = module1 module2 ...
    OWNER_NAME2 = module4 module5

``OWNER_`` is an optional prefix. ``OWNER_alice = cpu dsp`` and
``alice = cpu dsp`` both create group ``alice`` with owner ``alice``.

Usage::

    python scripts/generate_review_hierarchy.py --project blazar --input owners.txt
    python scripts/generate_review_hierarchy.py --project blazar --text "alice = cpu dsp
    bob = mem"
    python scripts/generate_review_hierarchy.py --project blazar < owners.txt
    python scripts/generate_review_hierarchy.py --project blazar --input owners.txt -o fragment.yaml

Paste the output into the web "project YAML" dialog. Default wrap is a
``projects:`` mapping with exactly one project (also accepted: bare
``owner`` / ``groups`` mapping via ``--wrap bare``).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

OWNER_PREFIX_RE = re.compile(r'^OWNER_', re.IGNORECASE)


class HierarchyGenerateError(ValueError):
    """Invalid owner/module text or CLI arguments."""


def sanitize_group_key(name: str) -> str:
    """Turn a left-hand owner token into a YAML group key."""
    stripped = OWNER_PREFIX_RE.sub('', name.strip(), count=1).strip()
    key = re.sub(r'\s+', '_', stripped)
    if not key:
        raise HierarchyGenerateError(f'empty group name after sanitizing {name!r}')
    return key


def owner_username(name: str) -> str:
    """Username for group owner and module release_owner."""
    user = OWNER_PREFIX_RE.sub('', name.strip(), count=1).strip()
    if not user:
        raise HierarchyGenerateError(f'empty owner name after stripping OWNER_ from {name!r}')
    return user


def parse_owner_module_text(text: str) -> list[tuple[str, str, list[str]]]:
    """Parse ``owner = module ...`` lines.

    Returns a list of ``(group_key, owner, modules)`` in file order.
    Duplicate modules across groups raise HierarchyGenerateError.
    """
    if not isinstance(text, str) or not text.strip():
        raise HierarchyGenerateError('owner/module text is empty')

    groups: list[tuple[str, str, list[str]]] = []
    seen_groups: dict[str, str] = {}
    module_owners: dict[str, str] = {}

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            raise HierarchyGenerateError(
                f'line {line_no}: expected "OWNER_name = module1 module2", got {raw_line!r}'
            )
        left, right = line.split('=', 1)
        left = left.strip()
        if not left:
            raise HierarchyGenerateError(f'line {line_no}: missing owner/group name before "="')
        modules = [token for token in right.split() if token]
        if not modules:
            raise HierarchyGenerateError(
                f'line {line_no}: {left!r} has no modules after "="'
            )

        group_key = sanitize_group_key(left)
        owner = owner_username(left)
        if group_key in seen_groups:
            raise HierarchyGenerateError(
                f'line {line_no}: group {group_key!r} is defined more than once'
            )
        seen_groups[group_key] = owner

        for module in modules:
            previous = module_owners.get(module)
            if previous is not None:
                raise HierarchyGenerateError(
                    f'line {line_no}: module {module!r} is assigned to both '
                    f'groups {previous!r} and {group_key!r}'
                )
            module_owners[module] = group_key

        groups.append((group_key, owner, modules))

    if not groups:
        raise HierarchyGenerateError('no owner/module lines found')
    return groups


def build_project_cfg(
    groups: list[tuple[str, str, list[str]]],
    *,
    project_owner: str | None = None,
) -> dict:
    """Build the project mapping: owner + groups + modules/release_owner."""
    if not groups:
        raise HierarchyGenerateError('no groups to emit')
    owner = (project_owner or '').strip() or groups[0][1]
    if not owner:
        raise HierarchyGenerateError('project owner must be a non-empty username')

    group_map: dict[str, dict] = {}
    for group_key, group_owner, modules in groups:
        group_map[group_key] = {
            'owner': group_owner,
            'modules': {
                module: {'release_owner': group_owner}
                for module in modules
            },
        }
    return {
        'owner': owner,
        'groups': group_map,
    }


def wrap_hierarchy(project_name: str, project_cfg: dict, wrap: str) -> dict:
    if wrap == 'bare':
        return project_cfg
    if wrap == 'projects':
        return {'projects': {project_name: project_cfg}}
    raise HierarchyGenerateError(f'unknown wrap mode {wrap!r}; use projects or bare')


def dump_hierarchy_yaml(data: dict) -> str:
    dumped = yaml.safe_dump(
        data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        indent=2,
    )
    return dumped if dumped.endswith('\n') else dumped + '\n'


def generate_review_hierarchy_yaml(
    text: str,
    project_name: str,
    *,
    project_owner: str | None = None,
    wrap: str = 'projects',
) -> str:
    name = (project_name or '').strip()
    if not name:
        raise HierarchyGenerateError('project name is required')
    groups = parse_owner_module_text(text)
    project_cfg = build_project_cfg(groups, project_owner=project_owner)
    return dump_hierarchy_yaml(wrap_hierarchy(name, project_cfg, wrap))


def _read_input(args: argparse.Namespace) -> str:
    sources = [bool(args.input), args.text is not None]
    if sum(sources) > 1:
        raise HierarchyGenerateError('use only one of --input, --text, or stdin')
    if args.input:
        path = Path(args.input)
        try:
            return path.read_text(encoding='utf-8')
        except OSError as exc:
            raise HierarchyGenerateError(f'cannot read {path}: {exc}') from exc
    if args.text is not None:
        return args.text
    if sys.stdin.isatty():
        raise HierarchyGenerateError(
            'no input: pass --input FILE, --text STRING, or pipe owner lines on stdin'
        )
    return sys.stdin.read()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            'Generate a one-project review_hierarchy YAML fragment from '
            '"OWNER_name = module1 module2" lines.'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python scripts/generate_review_hierarchy.py --project blazar --input owners.txt
  python scripts/generate_review_hierarchy.py --project blazar --text "OWNER_alice = cpu dsp
  OWNER_bob = mem"
  python scripts/generate_review_hierarchy.py --project blazar --wrap bare < owners.txt

owners.txt:
  OWNER_alice = cpu dsp
  bob = mem cache
""",
    )
    parser.add_argument('--project', required=True, help='Project name (YAML key)')
    parser.add_argument(
        '--project-owner',
        default='',
        help='Project-level owner username (default: first group owner)',
    )
    parser.add_argument('--input', '-i', help='Owner/module text file')
    parser.add_argument('--text', help='Owner/module text (alternative to --input/stdin)')
    parser.add_argument(
        '--output',
        '-o',
        help='Write YAML to FILE (default: stdout)',
    )
    parser.add_argument(
        '--wrap',
        choices=('projects', 'bare'),
        default='projects',
        help=(
            'projects: wrap as projects: {name: ...} (default, paste-dialog friendly); '
            'bare: emit only owner/groups'
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        text = _read_input(args)
        yaml_text = generate_review_hierarchy_yaml(
            text,
            args.project,
            project_owner=args.project_owner or None,
            wrap=args.wrap,
        )
    except HierarchyGenerateError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    if args.output:
        path = Path(args.output)
        try:
            path.write_text(yaml_text, encoding='utf-8')
        except OSError as exc:
            print(f'error: cannot write {path}: {exc}', file=sys.stderr)
            return 1
    else:
        sys.stdout.write(yaml_text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
