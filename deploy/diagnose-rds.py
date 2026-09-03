"""Run secret-free DNS, TCP, and PostgreSQL connection diagnostics."""

from __future__ import annotations

import socket
from pathlib import Path
from urllib.parse import urlsplit

import psycopg


dsn_path = Path.home() / ".config" / "hksr" / "rds.dsn"
dsn = dsn_path.read_text(encoding="utf-8").strip()
parsed = urlsplit(dsn)
host = parsed.hostname
port = parsed.port or 5432

if not host:
    raise SystemExit("dsn_structure=invalid")

try:
    socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    print("dns_resolved=true")
except OSError:
    print("dns_resolved=false")
    raise SystemExit(1)

try:
    with socket.create_connection((host, port), timeout=10):
        print("tcp_connected=true")
except OSError:
    print("tcp_connected=false")
    raise SystemExit(1)

try:
    with psycopg.connect(dsn, connect_timeout=15):
        print("postgresql_authenticated=true")
except psycopg.Error as error:
    message = str(error).lower()
    if "password authentication failed" in message or "authentication failed" in message:
        category = "credentials_rejected"
    elif "does not exist" in message and "database" in message:
        category = "database_missing"
    elif "no pg_hba.conf entry" in message or "host-based authentication" in message:
        category = "whitelist_or_ssl_policy"
    elif "server does not support ssl" in message:
        category = "server_ssl_disabled"
    elif "certificate" in message or "certificate verify failed" in message:
        category = "certificate_policy"
    elif "ssl" in message or "tls" in message:
        category = "ssl_policy"
    elif "timeout" in message or "timed out" in message:
        category = "connection_timeout"
    else:
        category = "unclassified"
    print("postgresql_authenticated=false")
    print("postgresql_error_class=%s" % type(error).__name__)
    print("postgresql_sqlstate=%s" % (error.sqlstate or "unavailable"))
    print("postgresql_error_category=%s" % category)
    raise SystemExit(1)
