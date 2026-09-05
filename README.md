# 崩坏：星穹铁道剧情与设定知识库

一个本地优先、以官方文本为证据边界的剧情与设定问答原型。回答中的每项主张都必须绑定可展开的官方来源；证据不足时系统拒绝补充模型记忆中的事实。

这个项目源于个人阅读剧情、梳理设定和创作《崩坏：星穹铁道》同人作品时的娱乐需求：希望随时查清人物、事件、地点与阵营之间的关系，也希望每个答案都能回到原文，而不是依赖模糊记忆或模型自由发挥。它既是一个自用的写作资料助手，也是一次对“有据可查的游戏知识问答”的技术实验。

## 当前能力

- 采集并解析官方 Wiki、官方文章、PV 与动画资料；
- 使用全文、字符向量和实体信号进行混合检索；
- 输出逐条主张、稳定证据 ID、原文、上下文和官方链接；
- 展示经过审核并绑定证据的一跳知识关联；
- 提供本地 FastAPI 接口和无需构建的 Web 页面。

## 本地启动

需要 Python 3.9 或更高版本。在项目根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
.venv/bin/python -m app.cli initialize
.venv/bin/python -m app.cli serve
```

然后访问 <http://127.0.0.1:8000/>。服务默认只监听回环地址；当前版本没有身份验证，请勿用 `--host 0.0.0.0` 暴露到局域网或公网。

初始化使用已经采集到本地的数据，不会联网。联网同步必须显式调用管理接口：

```bash
curl -X POST http://127.0.0.1:8000/api/admin/sync \
  -H 'content-type: application/json' \
  -d '{"fetch": true}'
```

## 常用命令

```bash
# CLI 问答
.venv/bin/python -m app.cli ask "小三月的纯真有没有失去？"

# 混合检索
.venv/bin/python -m app.cli search "阿格莱雅"

# 查看已审核关系
.venv/bin/python -m app.cli relations "阿格莱雅"

# 运行完整测试
.venv/bin/python -m unittest discover -s tests -v

# 生成当前数据的云容量报告（不联网）
.venv/bin/python -m app.cli capacity-report
```

详细设计和阶段结果见 [开发计划](docs/knowledge-qa-plan.md)、[M5 实施报告](docs/m5-local-product.md)、[M6A 中国大陆云容量报告](docs/m6a-cloud-capacity-validation.md)、[M7 后续路线图](docs/post-m7-roadmap.md)与 [M9 实体感知、有据问答](docs/m9-entity-aware-grounded-qa.md)。云端登录和无敏感信息的交接方式见 [阿里云与数据库访问指南](docs/cloud-access-guide.md)。

## 免责声明

本项目是由玩家个人制作的非官方、非商业性质项目，仅用于个人学习、技术研究、资料整理及同人创作辅助，与米哈游、HoYoverse 及其关联公司不存在隶属、合作、赞助或认可关系，也不代表任何官方立场。

《崩坏：星穹铁道》及其名称、角色、世界观、文本、图像、音视频、商标和其他相关素材的权利归其各自权利人所有。本项目对官方资料的采集、缓存、索引、引用或链接，不表示项目作者取得了相关内容的所有权或超出适用规则与法律范围的使用授权。

请勿将本项目或其输出冒充官方内容，也不要将其用于商业用途。项目中的问答结果可能不完整、过时或存在错误，不应替代官方资料；使用、部署或再分发本项目时，请自行确认并遵守相关平台条款、知识产权规则及所在地适用法律。如权利人认为项目中的内容侵犯其合法权益，可提出说明，相关内容将得到及时核查与处理。

以上声明用于说明项目性质与使用边界，不构成法律意见，也不能替代权利人的许可。
