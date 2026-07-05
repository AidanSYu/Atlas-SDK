"""Allow `pytest sdk/tests` from a checkout without installing the packages.

Repo-owned: the main Atlas repo carries its own variant of this file pointing
at its backend layout; `scripts/sync_sdk_repo.py` there syncs test_*.py only.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SDK = Path(__file__).resolve().parents[1]            # sdk/
_PROTOCOL = _SDK.parent / "protocol"                  # atlas_protocol lives here

for _p in (_SDK, _PROTOCOL):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
