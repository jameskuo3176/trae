"""Windows handler for gvim://open?path=...&line=....

This script never invokes a shell. Register it with register_gvim_protocol.ps1.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from urllib.parse import parse_qs, unquote, urlparse


def main(uri):
    parsed = urlparse(uri)
    if parsed.scheme.lower() != 'gvim' or parsed.netloc.lower() != 'open':
        raise SystemExit('invalid gvim URI')
    query = parse_qs(parsed.query, keep_blank_values=False)
    path = unquote((query.get('path') or [''])[0])
    if not path or '\x00' in path or '\r' in path or '\n' in path:
        raise SystemExit('invalid source path')
    line_raw = (query.get('line') or ['1'])[0]
    try:
        line = max(1, int(line_raw))
    except ValueError as exc:
        raise SystemExit('invalid line number') from exc
    executable = shutil.which('gvim') or shutil.which('gvim.exe')
    if not executable:
        raise SystemExit('gvim is not available on PATH')
    subprocess.Popen(
        [executable, f'+{line}', '--', path],
        shell=False,
        close_fds=True,
    )


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: gvim_protocol_handler.py <gvim-uri>')
    main(sys.argv[1])
