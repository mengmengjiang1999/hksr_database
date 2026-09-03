"""Normalize invalid literal percent signs in the protected RDS DSN file."""

from __future__ import annotations

import os
import re
from pathlib import Path


path = Path.home() / ".config" / "hksr" / "rds.dsn"
value = path.read_text(encoding="utf-8").rstrip("\r\n")
normalized = re.sub(r"%(?![0-9A-Fa-f]{2})", "%25", value)

if normalized != value:
    path.write_text(normalized + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    print("Normalized URL encoding in the protected RDS DSN file.")
else:
    print("The protected RDS DSN file already uses valid percent encoding.")
