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

## M7 米游社云采集

真实发现、正文获取和 OSS 上传的正常运行位置是保留的 ECS 工作目录
`/home/ecs-user/hksr_database`。命令本身是普通命令，不需要 activation flag、主机
标记、实例元数据检查或机器身份检查。本地工作站只运行 fixture/mock 测试，不按
运维流程启动真实采集。

ECS 私有配置文件 `~/.config/hksr/m7.env` 权限必须为 `600`，只设置运行参数：

```bash
HKSR_M7_ACCOUNT_UID=288909600
HKSR_M7_OSS_BUCKET=<private-bucket-name>
HKSR_M7_OSS_ENDPOINT=<private-vpc-oss-endpoint>
HKSR_M7_RAM_ROLE=<attached-ecs-role-name>
# Optional explicit override. Zero disables the daily total for the initial inventory.
HKSR_M7_DAILY_BUDGET=0
```

不要设置 `ALIBABA_CLOUD_ACCESS_KEY_ID`、`ALIBABA_CLOUD_ACCESS_KEY_SECRET`、
`OSS_ACCESS_KEY_ID` 或 `OSS_ACCESS_KEY_SECRET`。上传器拒绝静态 AccessKey，只接受
ECS 实例 RAM 角色取得的临时凭据。RAM 角色权限应限制为指定私有 bucket 的
`m7/` 前缀。

首次 M7A 必须人工逐步运行并逐份审查报告：

```bash
cd /home/ecs-user/hksr_database
.venv/bin/python -m app.cli --database data/database/hksr.sqlite3 m7-discover \
  --uid 288909600 --output data/m7/runs/m7a-discovery.json
.venv/bin/python -m app.cli --database data/database/hksr.sqlite3 m7-fetch \
  --output data/m7/runs/m7a-fetch.json
.venv/bin/python -m app.cli --database data/database/hksr.sqlite3 parse
.venv/bin/python -m app.cli --database data/database/hksr.sqlite3 initialize
.venv/bin/python -m app.cli --database data/database/hksr.sqlite3 cloud-import-sqlite \
  --batch-id m7-real-pilot-20260903 --allow-mutation \
  --output data/m7/runs/m7a-rds-first.json
.venv/bin/python -m app.cli --database data/database/hksr.sqlite3 cloud-import-sqlite \
  --batch-id m7-real-pilot-20260903 --allow-mutation \
  --output data/m7/runs/m7a-rds-second.json
```

默认每次发现最多 2 页（每页 20 项）、正文最多 10 篇、请求间隔 15–30 秒、
共享 UTC 日预算默认 60 次、单请求最多 3 次尝试，连续 3 次远端失败即熔断。提高单次
上限必须显式使用 `--allow-cap-override`，且实际 cap 会写入报告。用户于 2026-09-03
先批准 300 次 UTC 日预算，随后明确取消初始 M7B 的每日总量限制，同时要求保持
15–30 秒请求间隔不变。该覆盖值通过 ECS 私有配置 `HKSR_M7_DAILY_BUDGET=0` 注入，
并由 M7B 脚本显式传给发现和正文命令；`0` 表示继续记录请求数但不按日期截停。
未配置时仍使用安全默认值 60。

内容优先级方面，米游社 Wiki 是主要官方资料来源；官方账号历史文章只作为补充来源。
账号文章仍须通过官方身份校验和内容分类，运营公告、无官方文本视频及待审核内容不会
因为扩大请求预算而自动进入证据库。
正文接口在 HTTP 成功时若返回非零业务 `retcode`，来源会记为
`excluded_unavailable` / `skipped` 并直接跳过；报告只统计返回码，不保存错误正文，
后续批次不会反复请求该条目。网络、OSS 或熔断错误仍按真实失败停止批次。

若工作站创建的 SQLite FTS5 索引使用了 ECS SQLite 不支持的 `trigram` tokenizer，
应用初始化会只重建派生全文索引为 `unicode61`，不会删除来源、正文、游标或 OSS 清单。
首次云端兼容修复前应复制一份 SQLite 数据库备份，并在修复后执行
`PRAGMA integrity_check`。
每批完成后运行 `m7-report`，先审查分类、空正文、视频文本、失败、重试和 OSS 哈希，
再开始下一批。是否完成只看上游 terminal cursor，不按估算文章数判断。

systemd 单元只安装，不启用定时器：

```bash
chmod +x deploy/run-m7-incremental.sh
install -m 0644 deploy/hksr-m7.service ~/.config/systemd/user/hksr-m7.service
install -m 0644 deploy/hksr-m7.timer ~/.config/systemd/user/hksr-m7.timer
systemctl --user daemon-reload
systemctl --user disable --now hksr-m7.timer
systemctl --user is-enabled hksr-m7.timer
```

预期最后一条输出为 `disabled`。只有初始清单到达 terminal、至少三次人工无变化检查
通过，并且用户另行明确批准后，才允许启用 `hksr-m7.timer`。
