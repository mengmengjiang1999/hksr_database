# M10 RDS 读取、核对与回滚

应用只接受 `sqlite` 或 `postgres` 两种显式后端。ECS 上由权限为 `0600` 的
`~/.config/hksr/read-backend` 保存当前值；只有选择 `postgres` 时，启动脚本才读取既有的
`~/.config/hksr/rds-runtime.dsn`。高权限迁移连接仍保存在 `rds.dsn`，应用启动脚本不得读取它。
日志、命令输出和验收报告不得打印任一文件内容。

## 验收顺序

1. 保持 `read-backend` 为 `sqlite`，并确认 `hksr-m7.timer` 为 disabled。
2. 使用写入角色执行 `cloud-migrate --allow-mutation` 与一次 `m10-real-*` 全量同步。
3. 分别执行 `m10-manifest`、`m10-evaluate` 和 `m10-shadow`；生成能力保持关闭。
4. 权限矩阵必须证明应用角色能读取所需对象，但不能写证据、导入状态、Schema、角色或无关 Schema。
5. 仅在清单、质量、双读和权限检查全部通过后，将配置改为 `postgres` 并重启服务。

运行角色由 `deploy/configure-rds-runtime-role.py --apply` 创建或轮换。脚本只输出角色属性、
允许/拒绝矩阵和 SQLSTATE，不输出密码或连接串；运行 DSN 以 `0600` 原子写入
`~/.config/hksr/rds-runtime.dsn`。

双读是离线验收：同一套固定问题分别读取 SQLite 与 RDS，再比较稳定证据 ID、实体、回答状态、
引用、来源导航、目录和关系。线上请求不会同时查询两套数据库。

## 应用回滚

把 `~/.config/hksr/read-backend` 改回 `sqlite`，重启 `hksr.service`，再运行健康、目录、搜索、
来源详情、实体关系和问答冒烟测试。该操作不删除 RDS 数据、不回退数据库结构、不改 OSS、
不启用模型，也不启用采集定时器。验收期间必须保留已接受的 SQLite 快照。

## 新增数据库对象的后续清理 DDL

以下语句只用于未来单独审核的永久清理，不属于应用故障回滚，也不得在正常切换时执行：

```sql
DROP TABLE IF EXISTS hksr.retrieval_metadata_chunks;
DROP TABLE IF EXISTS hksr.identity_names;
DROP TABLE IF EXISTS hksr.playable_forms;
DROP TABLE IF EXISTS hksr.narrative_people;
DROP TABLE IF EXISTS hksr.retrieval_metadata;
DROP TABLE IF EXISTS hksr.chunk_vectors;
DROP TABLE IF EXISTS hksr.source_dispositions;
DROP INDEX IF EXISTS hksr.sources_sqlite_id_idx;
DROP INDEX IF EXISTS hksr.documents_sqlite_id_idx;
DROP INDEX IF EXISTS hksr.chunks_sqlite_id_idx;
DROP INDEX IF EXISTS hksr.entities_sqlite_id_idx;
DROP INDEX IF EXISTS hksr.relations_sqlite_id_idx;
ALTER TABLE hksr.sources DROP COLUMN IF EXISTS sqlite_id;
ALTER TABLE hksr.documents DROP COLUMN IF EXISTS sqlite_id;
ALTER TABLE hksr.chunks DROP COLUMN IF EXISTS sqlite_id;
ALTER TABLE hksr.entities DROP COLUMN IF EXISTS sqlite_id;
ALTER TABLE hksr.relations DROP COLUMN IF EXISTS sqlite_id;
```
