"""Set the protected RDS DSN to explicit non-SSL mode after user approval."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


path = Path.home() / ".config" / "hksr" / "rds.dsn"
value = path.read_text(encoding="utf-8").strip()
parsed = urlsplit(value)
query = dict(parse_qsl(parsed.query, keep_blank_values=True))
query["sslmode"] = "disable"
updated = urlunsplit((
    parsed.scheme,
    parsed.netloc,
    parsed.path,
    urlencode(query),
    parsed.fragment,
))
path.write_text(updated + "\n", encoding="utf-8")
os.chmod(path, 0o600)
print("Configured the protected DSN for approved same-VPC non-SSL access.")
