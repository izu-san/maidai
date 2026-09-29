"""Windows-local private storage boundaries for Rino runtime state."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def ensure_private_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path, 0o700)
        return path
    username = os.environ.get("USERNAME")
    if not username:
        raise RuntimeError("Cannot determine Windows user for Rino private storage.")
    result = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{username}:(OI)(CI)F", "SYSTEM:(OI)(CI)F"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Could not restrict Rino private storage ACL.")
    return path
