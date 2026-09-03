# ECS private deployment

The M6B service runs as the `ecs-user` systemd user and listens only on
`127.0.0.1:8000`. It intentionally does not open a public port.

```bash
systemctl --user status hksr
journalctl --user -u hksr --since today
systemctl --user restart hksr
```

For temporary access from a trusted workstation, create an SSH tunnel and open
`http://127.0.0.1:8000` locally:

```bash
ssh -N -L 8000:127.0.0.1:8000 hksr-m6b
```

The RDS DSN is required only by the `cloud-*` migration and audit commands. It
must be injected at runtime and must not be committed to this repository.

Configure it without placing the value in shell history, then finalize the
idempotent migration:

```bash
chmod +x deploy/*.sh
./deploy/configure-rds-dsn.sh
.venv/bin/python deploy/normalize-rds-dsn.py
# Run the next command only after explicitly accepting same-VPC non-SSL transport.
.venv/bin/python deploy/authorize-private-non-ssl.py
./deploy/finalize-cloud-migration.sh
```

The DSN is stored at `~/.config/hksr/rds.dsn` with mode `600`. Reports are
sanitized and never include the DSN.

Alibaba Cloud RDS PostgreSQL Serverless does not currently support SSL. For
this same-VPC deployment, non-SSL transport is enabled only after explicit user
approval by running `deploy/authorize-private-non-ssl.py`. The RDS endpoint and
application remain private and no public database address is requested.
