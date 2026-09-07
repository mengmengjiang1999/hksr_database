#!/usr/bin/env python3
"""Provision or verify the private RDS application read role."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cloud.runtime_role import (
    DEFAULT_ROLE,
    provision_runtime_role,
    verify_runtime_privileges,
    write_report,
)


def main() -> int:
    home = Path.home()
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-dsn", type=Path, default=home / ".config/hksr/rds.dsn")
    parser.add_argument("--runtime-dsn", type=Path, default=home / ".config/hksr/rds-runtime.dsn")
    parser.add_argument("--role", default=DEFAULT_ROLE)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()

    if arguments.apply:
        provision_runtime_role(
            arguments.admin_dsn.read_text(encoding="utf-8").strip(),
            arguments.runtime_dsn,
            role=arguments.role,
        )
    if not arguments.runtime_dsn.is_file():
        parser.error("runtime DSN is missing; rerun with --apply")
    report = verify_runtime_privileges(
        arguments.runtime_dsn.read_text(encoding="utf-8").strip()
    )
    if arguments.report:
        write_report(arguments.report, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
