# M6A 中国大陆云容量与架构验证报告

> 状态：容量规划完成，尚未创建云资源
>
> 数据观察时间：2026-09-02

## 1. 结论

第一轮采用以下基线：

```text
米哈游官方来源
    ↓ 采集（限速、增量、可审计）
中国大陆私有应用运行环境
    ├── 私有 OSS：原始响应、字幕、版本快照、导出和失败样本
    └── RDS PostgreSQL：来源、文本、实体、关系、证据、任务状态
                         ├── 中文全文/字符检索
                         └── pgvector 语义向量
```

M6A 没有发现引入独立向量数据库、AnalyticDB、Elasticsearch 或图数据库的容量依据。直接外推约 7,120 个片段；即使按 100,000 片段规划，1024 维 float32、HNSW、正文、关系数据和 30% 运维余量合计约 1.67 GiB。

推荐 M6B 从同一地域的私有 OSS、RDS PostgreSQL 和私有应用运行环境开始。正式采购前必须用购买页实时价格确认报价。

## 2. 第一轮官方目录范围

| 类别 | 目录数量 | 纳入口径 |
| --- | ---: | --- |
| 角色资料 | 98 | 官方 Wiki 角色频道 |
| 主线剧情 | 263 | 214 个开拓任务 + 49 个开拓续闻 |
| 阅读物 | 652 | 官方 Wiki 阅读物频道 |
| 关键官方视频 | 269 | 角色 PV、千星纪游、角色解说、版本 PV、动画短片、剧情 CG |
| 合计 | 1,282 | 同一资料跨频道时后续按官方 ID 去重 |

数量来自[官方 Wiki 目录接口](https://act-api-takumi-static.mihoyo.com/common/blackboard/sr_wiki/v1/home/content/list)，是 2026-09-02 的时间点观察，不是稳定不变的产品常量。关键视频不保存视频二进制，只保存官方链接、元数据、经验证文本和时间码。

## 3. 本地真实测量

| 指标 | 测量值 |
| --- | ---: |
| 来源 | 5 |
| 文档 | 15 |
| 片段 | 41 |
| 正文字符 | 17,426 |
| 正文 UTF-8 字节 | 48,163 |
| 原始响应 | 5 个文件 / 376,751 字节 |
| SQLite | 3,067,904 字节 |
| 当前稀疏向量 JSON | 1,378,626 字节 |

当前 n-gram 向量使用 JSON 保存，是 Demo 实现，并不代表 PostgreSQL 稠密向量容量。生产估算使用 pgvector 的二进制公式：`vector = 4 × dimensions + 8` 字节，`halfvec = 2 × dimensions + 8` 字节。[pgvector 官方说明](https://github.com/pgvector/pgvector#vector-type)

## 4. 语料外推

当前样本按来源类型均值直接外推：

| 类别 | 预计字符 | 预计片段 | 单次原始响应 |
| --- | ---: | ---: | ---: |
| 角色资料 | 960,890 | 2,254 | 约 19.52 MiB |
| 主线剧情 | 1,828,113 | 3,945 | 约 34.62 MiB |
| 阅读物 | 227,548 | 652 | 约 7.67 MiB |
| 关键视频 | 41,964 | 269 | 约 2.63 MiB |
| 合计 | 3,058,515 | 7,120 | 约 64.44 MiB |

每种类型只有一个真实正文样本，因此这些数值属于低置信度外推。容量计划对单次原始快照使用 5 倍安全系数，再保留 12 个来源版本，得到约 3.78 GiB OSS 规划量。

## 5. PostgreSQL 与向量容量情景

统一假设：1024 维、HNSW 规划为向量本体 1.5 倍、正文和关系元数据为实测片段字节的 3 倍、整体保留 30% 运维余量。

| 片段数 | float32 总规划 | halfvec 总规划 | 决策 |
| ---: | ---: | ---: | --- |
| 10,000 | 170.89 MiB | 107.42 MiB | 首轮预期档 |
| 50,000 | 854.46 MiB | 537.08 MiB | 历史版本与扩展规划档 |
| 100,000 | 1.67 GiB | 1.05 GiB | 单 PostgreSQL 验收档 |
| 1,000,000 | 16.69 GiB | 10.49 GiB | 触发架构复核，不自动拆分 |

HNSW 大小是规划系数而非云上实测值。M6B 必须使用 `pg_total_relation_size` 校准，并用精确搜索对照近似搜索召回率。pgvector 支持精确搜索、HNSW 和 IVFFlat；HNSW 通常以更多内存和构建时间换取更好的速度—召回权衡。[pgvector 索引文档](https://github.com/pgvector/pgvector#indexing)

## 6. 中国大陆云资源建议

### M6B 测试规格

- 地域：杭州或上海，OSS、RDS 和应用必须同地域；
- OSS：私有 Bucket，标准存储，开启版本控制；历史快照通过生命周期规则转低频或归档；
- RDS：PostgreSQL 17、2 vCPU / 8 GiB 规划档、50 GiB 云盘；
- 应用：2 vCPU / 4 GiB 的 ECS、容器实例或等价运行环境；
- 网络：同一 VPC，RDS 和 OSS 不开放匿名访问，数据库不使用公网连接；
- 出网：采集任务通过受控公网出口访问官方来源；
- 密钥：使用 RAM 角色或密钥管理，不写入代码和镜像。

阿里云公开规格中存在 2 核 8 GB PostgreSQL 规格，但具体系列、可用区和价格必须以购买页为准。[RDS PostgreSQL 规格列表](https://help.aliyun.com/zh/rds/apsaradb-rds-for-postgresql/primary-apsaradb-rds-for-postgresql-instance-types/)

### 插件验收

采购前和实例创建后都要检查：

```sql
SELECT * FROM pg_available_extensions
WHERE name IN ('vector', 'pg_jieba', 'zhparser', 'pg_bigm');
```

阿里云 RDS PostgreSQL 的插件目录包含 pgvector 和多种中文检索插件，但版本、规格和内核小版本会影响可用性。[RDS PostgreSQL 插件列表](https://help.aliyun.com/zh/rds/apsaradb-rds-for-postgresql/extensions-supported-by-apsaradb-rds-for-postgresql)

第一版应保留字符 n-gram 召回作为稳定基线，再用 `pg_jieba` 或其他中文分词实验与标准问题集比较，不因插件存在就直接替换现有检索。

## 7. 数据分层与恢复

### OSS

- Bucket 默认私有并开启版本控制；
- 对象键包含来源类型、官方 ID、内容哈希；
- 当前版本使用标准存储；
- 30 天后可转低频，长期历史版本再考虑归档；
- 不自动删除仍被引用证据依赖的对象；
- 版本、低频和归档会产生存储、请求、取回及最短存储周期费用。

OSS 支持版本控制和生命周期转储；历史版本的恢复、取回费用和最低存储时长需要纳入成本模型。[OSS 版本控制](https://help.aliyun.com/zh/oss/user-guide/what-is-oss)、[OSS 生命周期](https://help.aliyun.com/zh/oss/user-guide/overview-54/)

### RDS

- 测试阶段至少每日自动备份；
- 生产前开启日志备份和时间点恢复；
- 每月至少做一次独立逻辑导出；
- M6B 必须完成一次恢复演练；
- 初始建议目标：RPO 不超过 24 小时，RTO 不超过 4 小时，公网版前重新评审。

RDS PostgreSQL 支持自动备份，并可通过日志备份提供保留期内的时间点恢复；基础版等规格存在功能差异，创建时必须验收。[RDS PostgreSQL 备份文档](https://help.aliyun.com/en/rds/apsaradb-rds-for-postgresql/back-up-an-apsaradb-rds-for-postgresql-instance)

## 8. 费用边界

M6A 不把动态价格写成事实。采购询价必须逐项记录：

| 服务 | 计费项 |
| --- | --- |
| RDS | 实例系列、CPU/内存、云盘、IOPS、备份超额、跨区备份 |
| OSS | 当前与历史容量、存储类型、PUT/GET、取回、外网流量 |
| 应用运行环境 | 实例时长、系统盘、公网带宽、日志 |
| 网络 | NAT、固定公网 IP、流量、跨地域传输 |
| 模型 | Embedding 字符或 Token、重排、问答调用 |
| 运维 | 监控、日志保存、告警和备份验证 |

建议的 M6B 内部控制线不是云市场报价：测试资源最多运行 14 天，任何付费资源在创建前确认；若试验预计超过人民币 500 元或形成持续月费，则再次审批。

## 9. M6B 准入标准

只有完成以下检查才进入全量采集：

1. `vector` 和选定中文检索插件可创建；
2. 导入 100,000 片段的容量与本报告偏差不超过 50%，否则更新模型；
3. 混合检索在并发 10 下 P95 不高于 300 ms；
4. HNSW 的 Recall@10 相对精确搜索不低于 0.90；
5. 增量写入不会导致稳定证据 ID 变化；
6. 私有网络、最小权限、OSS 版本控制和审计日志通过检查；
7. 完成一次数据库恢复和一条 OSS 历史版本恢复；
8. 得到采购日的官方月度报价。

若 100,000 片段不能满足上述指标，才比较 AnalyticDB PostgreSQL 或独立向量服务。达到 1,000,000 片段只触发复核，不自动迁移。

## 10. 公网合规边界

M6A/M6B 均不创建公开站点。未来域名指向中国大陆服务器并对外提供 Web 服务时，需要在上线计划中处理 ICP 备案等事项。[阿里云 ICP 备案说明](https://help.aliyun.com/zh/icp-filing/basic-icp-service/support/for-the-record-process-faq)

游戏文本、官方文章、字幕和视频的缓存、展示、传播范围也需要独立的内容授权评估；技术上可采集不等于获得公开再分发授权。
