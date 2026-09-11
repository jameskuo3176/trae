"""Safe, browser-supplied path handling for CSV uploads.

The paths handled here are metadata from ``webkitRelativePath``.  They are
never resolved against, or read from, the server filesystem.
"""
import re
from pathlib import PurePosixPath


DEFAULT_FILENAME_SUFFIXES = ('_qor_report', '_qor', 'qor')


class UploadPathError(ValueError):
    """Raised when browser-supplied upload path metadata is unsafe."""


def parse_filename_suffixes(raw_value):
    """Return safe, longest-first filename suffixes."""
    if raw_value is None:
        return DEFAULT_FILENAME_SUFFIXES
    values = []
    for raw_suffix in str(raw_value).split(','):
        suffix = raw_suffix.strip()
        if not suffix:
            continue
        if len(suffix) > 80 or '/' in suffix or '\\' in suffix or '\x00' in suffix:
            raise UploadPathError('filename_suffixes 包含无效后缀')
        values.append(suffix)
    if not values:
        raise UploadPathError('filename_suffixes 不能为空')
    return tuple(sorted(dict.fromkeys(values), key=len, reverse=True))


def normalize_relative_upload_path(raw_path):
    """Normalize a relative browser upload path without touching disk."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise UploadPathError('文件相对路径不能为空')
    value = raw_path.strip().replace('\\', '/')
    if '\x00' in value:
        raise UploadPathError('文件相对路径包含非法字符')
    if value.startswith('/') or value.startswith('//') or re.match(r'^[A-Za-z]:', value):
        raise UploadPathError('文件路径必须是浏览器提供的相对路径')

    raw_parts = value.split('/')
    if any(part in ('', '.', '..') for part in raw_parts):
        raise UploadPathError('文件相对路径包含不安全的路径段')

    path = PurePosixPath(*raw_parts)
    if path.suffix.lower() != '.csv':
        raise UploadPathError('仅支持 CSV 文件')
    return path.as_posix()


def infer_module_from_path(relative_path, source='dirname', filename_suffixes=None):
    """Infer a module from a validated browser relative path."""
    normalized = normalize_relative_upload_path(relative_path)
    path = PurePosixPath(normalized)

    if source == 'dirname':
        # webkitRelativePath includes the selected root directory.  Requiring
        # root/module/file prevents a CSV placed at the root from mapping to
        # the selected directory name.
        if len(path.parts) < 3:
            raise UploadPathError('目录模式要求 CSV 位于 base/module_name/ 文件夹下')
        inferred = path.parent.name.strip()
    elif source == 'filename':
        inferred = path.stem.strip()
        suffixes = filename_suffixes or DEFAULT_FILENAME_SUFFIXES
        lowered = inferred.casefold()
        for suffix in sorted(suffixes, key=len, reverse=True):
            if lowered.endswith(suffix.casefold()):
                inferred = inferred[:-len(suffix)].rstrip('._- ')
                break
    else:
        raise UploadPathError('module_name_source 必须是 dirname、filename 或 csv')

    if not inferred or inferred in ('.', '..') or '/' in inferred or '\\' in inferred:
        raise UploadPathError('无法从文件路径安全推断模块名')
    return inferred
