# M6B 阿里云数据库实测

> 状态：数据库上云迁移已完成；PostgreSQL 兼容性、真实语料幂等导入、ECS 私有应用和最终数据库审计均已通过
>
> 云资源：阿里云华东2（上海）RDS PostgreSQL 18 Serverless 基础系列

## 1. 安全边界

- 不创建 RDS 公网地址；DMS 用于首次检查，批量测试从同 VPC 临时运行环境执行。
- 连接串只通过运行时环境变量 `HKSR_POSTGRES_DSN` 注入，不写入命令历史、配置文件、报告或 Git。
- 默认命令只读；迁移、安装插件、写入和清理都要求 `--allow-mutation`。
- 合成片段位于 `hksr_validation`，带 `synthetic = true` 和精确 run ID，不能进入 `hksr.official_evidence`。
- 自动清理仅删除显式指定的 `m6b-*` run，不释放 RDS，也不删除正式 schema。

## 2. 当前采购观察

已由用户在控制台确认：PostgreSQL 18、基础系列、0.5–4 RCU、20 GiB 高性能云盘、上海可用区 F、私有 VPC、自动启停和释放保护开启。脱敏记录位于 `data/m6b/procurement-observation.json`。

## 3. PostgreSQL 兼容性结果

已通过 DMS 确认 PostgreSQL 18 数据库可连接，并完成以下只读检查：

```sql
SELECT current_setting('server_version') AS server_version,
       current_setting('server_version_num') AS server_version_num,
       current_setting('ssl') AS ssl,
       current_setting('shared_preload_libraries') AS shared_preload_libraries;

SELECT a.name, a.default_version, e.extversion AS installed_version
FROM pg_available_extensions AS a
LEFT JOIN pg_extension AS e ON e.extname = a.name
WHERE a.name IN ('vector', 'pg_jieba', 'zhparser', 'pg_bigm')
ORDER BY a.name;
```

`vector` 0.8.1.2、`pg_bigm` 1.2、`pg_jieba` 1.2.0 和 `zhparser` 1.0 均已创建并通过功能探针。`pg_jieba` 对专名“阿格莱雅”出现拆词，因此只记录为可用候选，不据此替换当前字符 n-gram 基线。脱敏结果位于 `data/m6b/dms-extension-observation.json`。

## 4. 中文插件预加载

`pg_jieba`、`zhparser` 和 `pg_bigm` 在阿里云插件文档中属于需要加入 `shared_preload_libraries` 的全文检索插件。只有在只读检查确认实例确实可用后，才在“参数设置”中记录原值、加入准备测试的插件、应用参数并完成一次受控重启。`vector` 不需要预加载。

若插件创建失败，先升级到控制台提供的最新内核小版本；不要通过反复重建实例绕过错误。回滚时恢复原来的 `shared_preload_libraries` 值并重启。

## 5. ECS 开发、测试与部署环境

上海同 VPC ECS 已安装 Python 3.11、Git 和 rsync，项目部署在 `/home/ecs-user/hksr_database`。云端完整测试共 61 项并已全部通过。应用由 `ecs-user` 的 systemd 用户服务管理，只监听 `127.0.0.1:8000`；用户驻留已启用，主进程被终止后自动重启和健康检查均通过。使用方法见 `deploy/README.md`。

当前 API 继续使用随项目同步的 SQLite 读取路径；RDS 保存已经迁移的官方语料并作为后续增量迁移目标。本阶段已通过 ECS 上的 `cloud-audit` 验证私网 RDS 读取，不开放 RDS 或应用公网端口。

RDS 连接串通过 `deploy/configure-rds-dsn.sh` 静默写入 ECS 用户私有的 `~/.config/hksr/rds.dsn`，权限为 `600`，不会进入 Git、聊天或 Shell 历史。随后运行 `deploy/finalize-cloud-migration.sh` 完成迁移、重复导入和最终审计。

实测实例未启用 SSL，强制 `sslmode=require` 会被服务器拒绝。阿里云官方文档注明 RDS PostgreSQL Serverless 暂不支持开启 SSL。用户于 2026-09-03 明确接受 ECS 到 RDS 的同 VPC 私网非 SSL 连接；连接设置为 `sslmode=disable`，RDS 和应用均不开放公网地址。若后续更换为支持 SSL 的实例，应恢复强制 TLS 并重新验证。

## 6. 私网数据库运行命令

在同 VPC 运行环境中安装可选依赖，并从安全运行时临时注入连接串：

```bash
python -m pip install -e '.[cloud]'
export HKSR_POSTGRES_DSN='postgresql://...'
python -m app.cli cloud-discover --output data/m6b/runs/environment.json
python -m app.cli cloud-extensions
python -m app.cli cloud-extensions --allow-mutation --output data/m6b/runs/extensions.json
python -m app.cli cloud-migrate --allow-mutation
python -m app.cli cloud-import-sqlite --batch-id m6b-real-initial-20260903 --allow-mutation --output data/m6b/runs/real-import-first.json
python -m app.cli cloud-import-sqlite --batch-id m6b-real-initial-20260903 --allow-mutation --output data/m6b/runs/real-import-second.json
python -m app.cli cloud-audit --output data/m6b/runs/final-database-audit.json
```

不要把真实 `export` 命令复制到共享日志。上述连接串只是格式占位符。最终云端迁移再次执行 migrations 和重复导入，5 个来源、15 个文档、41 个片段、35 个实体、45 个别名、243 个实体片段关联、316 条关系、625 条关系证据和 41 条官方证据数量全部一致；没有产生重复，也没有导入合成片段。

10 万片段 fixture 和 benchmark 命令仍保留为后续显式容量测试工具，不属于 M6B 验收门槛，也不得在本阶段默认执行。

## 7. 恢复范围与清理验收

当前范围与清理状态：

- 上海 OSS Bucket 已购买/创建，留待后续采集存储使用；
- 用户于 2026-09-03 明确决定不执行 OSS 历史版本和 RDS 备份恢复演练，两项均不属于本阶段门槛；
- ECS 明确保留为开发、测试和部署主机，不作为临时资源释放；
- `cloud-audit` 已确认 `hksr_validation.chunks` 为零，RDS 保持最大 4 RCU 和自动暂停配置；
- 最终保留资源为私有 RDS PostgreSQL Serverless、同 VPC ECS 和后续采集使用的 OSS Bucket，没有待释放的恢复实例或临时计算资源。

## 8. 验收报告

控制台结果只写入 `data/m6b/operator-evidence.json`，不得记录实例 ID、Bucket 名称、地址、账号或密钥。最终执行：

```bash
python -m app.cli cloud-acceptance-report \
  --database-audit data/m6b/runs/final-database-audit.json
python -m unittest discover -s tests -v
openspec validate m6b-cloud-database-validation --strict
```

命令生成 `data/m6b/acceptance-report.json` 与 `docs/m6b-acceptance-report.md`，自动测量和人工确认分别存放。恢复演练明确列为延后项目，不参与本阶段 `ready_to_archive` 计算。

## 9. 架构与成本结论

- 保留 PostgreSQL 18 Serverless、pgvector 与字符 n-gram 基线；中文全文检索插件暂不成为唯一检索路径。
- RDS 维持 0.5–4 RCU、20 GiB 和自动暂停；实际账单另行观察，不把公开目录价当成发票价格。
- 同 VPC ECS 从临时导入机调整为后续开发、测试和部署主机，因此不作为待释放的临时资源。
- M6B 不开放公网应用；公网部署、认证、HTTPS、监控和 ICP 备案属于后续独立变更。
- 当前上云范围只包括已经采集的官方语料；米游社全量采集与后续增量导入在数据库迁移验收完成后继续。
