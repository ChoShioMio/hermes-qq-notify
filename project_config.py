"""Portable path resolution; no credentials, networking or configuration writes."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def hermes_home(environ: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    values = os.environ if environ is None else environ
    if values.get('HERMES_HOME'):
        return Path(values['HERMES_HOME']).expanduser()
    if values.get('LOCALAPPDATA'):
        return Path(values['LOCALAPPDATA']) / 'hermes'
    return (home if home is not None else Path.home()) / '.hermes'
