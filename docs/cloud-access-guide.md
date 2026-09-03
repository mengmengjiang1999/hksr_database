# 阿里云与数据库访问指南

> 用途：供后续开发窗口快速找到正确的云端入口和操作方式。
>
> 本文只记录非敏感信息。不得在本文、Git、聊天、日志或命令输出中保存密码、完整 DSN、AccessKey、Cookie、实例 ID、Bucket 名称或数据库地址。

## 1. 当前云端环境

- 地域：阿里云华东 2（上海）；
- ECS：后续开发、测试、真实采集和部署主机；
- ECS 项目目录：`/home/ecs-user/hksr_database`；
- RDS：PostgreSQL 18 Serverless，与 ECS 位于同一 VPC；
- OSS：私有 Bucket，用于保存后续采集的原始响应；
- 应用服务：ECS 上的 `ecs-user` systemd 用户服务 `hksr`；
- 应用监听：仅 `127.0.0.1:8000`，没有公开应用端口；
- RDS：不创建公网地址，现有 Serverless 实例使用已经批准的同 VPC 非 SSL 连接。

## 2. 阿里云控制台

控制台入口：

- [阿里云控制台首页](https://home.console.aliyun.com/)
- [ECS 控制台](https://ecs.console.aliyun.com/)
- [RDS 控制台](https://rdsnext.console.aliyun.com/)
- [OSS 控制台](https://oss.console.aliyun.com/overview)
- [DMS 数据管理](https://dms.aliyun.com/)

进入产品控制台后先选择“华东 2（上海）”，再根据资源类型找到本项目已经保留的 ECS、RDS PostgreSQL Serverless 和私有 OSS Bucket。不要把页面中的实例 ID、数据库地址、账号、密码或 Bucket 名称复制到聊天或项目文件。

浏览器控制台中的登录、选择资源、授权和配置操作由用户本人完成。其他开发窗口应提供链接和操作步骤，不主动接管浏览器；需要页面信息时，只请求用户反馈非敏感状态。

## 3. 登录 ECS

本机 SSH 配置已经使用别名 `hksr-m6b`。在本地终端执行：

```bash
ssh hksr-m6b
```

登录后进入项目：

```bash
cd /home/ecs-user/hksr_database
pwd
git status --short
```

也可以直接进入远端项目目录并打开登录 Shell：

```bash
ssh -t hksr-m6b 'cd /home/ecs-user/hksr_database && exec bash -l'
```

SSH 私钥和主机地址只保存在用户自己的 SSH 配置中，不写入项目。如果别名失效，应让用户检查本机 `~/.ssh/config`、私钥权限和 ECS 状态；不要猜测或在聊天中索取私钥内容。

## 4. 查看 ECS 应用

登录 ECS 后可执行以下只读检查：

```bash
systemctl --user status hksr --no-pager
journalctl --user -u hksr --since today --no-pager
curl --fail http://127.0.0.1:8000/api/health
```

只有任务明确要求部署或重启时，才执行：

```bash
systemctl --user restart hksr
```

从本地临时访问私有 Web 应用时，在一个本地终端保持以下隧道运行：

```bash
ssh -N -L 8000:127.0.0.1:8000 hksr-m6b
```

然后在本机打开 <http://127.0.0.1:8000/>。结束查看后用 `Ctrl-C` 关闭隧道。

## 5. RDS 凭据位置

完整 RDS DSN 只保存在 ECS 用户私有文件：

```text
~/.config/hksr/rds.dsn
```

它的权限应为 `600`。只检查文件是否存在和权限，不显示内容：

```bash
test -s ~/.config/hksr/rds.dsn
stat -c '%a %n' ~/.config/hksr/rds.dsn
```

预期第二条命令显示权限 `600`。禁止执行或展示：

```text
cat ~/.config/hksr/rds.dsn
echo "$HKSR_POSTGRES_DSN"
env
set -x
```

不要把完整 DSN 直接放在命令参数中，因为它可能出现在 Shell 历史或进程列表中。

## 6. 安全检查 RDS 连接

在 ECS 项目目录运行现有的无密钥输出诊断：

```bash
cd /home/ecs-user/hksr_database
.venv/bin/python deploy/diagnose-rds.py
```

成功时应看到以下布尔状态，但不会看到地址或密码：

```text
dns_resolved=true
tcp_connected=true
postgresql_authenticated=true
```

查看数据库汇总数据时，让当前 Shell 临时读取私密文件并在完成后清除变量：

```bash
set +x
IFS= read -r HKSR_POSTGRES_DSN < ~/.config/hksr/rds.dsn
export HKSR_POSTGRES_DSN
.venv/bin/python -m app.cli cloud-audit
unset HKSR_POSTGRES_DSN
```

`cloud-audit` 是只读操作。数据库迁移、导入、清理及任何带 `--allow-mutation` 的命令都属于写操作，只有当前任务明确要求时才能执行。

如果确实需要交互式 SQL，优先由用户在 DMS 控制台中登录，或另行建立不会把凭据放入进程参数的受控工具；不要为了方便打印或复制 DSN。

## 7. 重新配置 RDS DSN

只有凭据轮换、数据库地址变化或私密文件丢失时才需要重新配置。由用户取得完整 DSN 后，在 ECS 项目目录运行：

```bash
./deploy/configure-rds-dsn.sh
```

脚本会静默读取输入并写入权限为 `600` 的私密文件。输入结果不得回显、截图或写入聊天。当前 RDS Serverless 不支持 SSL，既有配置已经按用户批准规范化为同 VPC 非 SSL；除非实例能力发生变化，不要自行修改传输模式。

## 8. OSS 和 M7 私密配置

M7 运行参数保存在 ECS：

```text
~/.config/hksr/m7.env
```

该文件同样必须为 `600`，不得读取到聊天或日志中。OSS 访问使用 ECS 实例 RAM 角色的临时凭据，不配置或保存静态 AccessKey。真实采集只在 ECS 的项目目录运行，具体命令和批量限制见 [ECS 部署说明](../deploy/README.md)。

## 9. 交接检查清单

其他窗口开始云端工作时按以下顺序检查：

1. 阅读本文和 `deploy/README.md`；
2. 在本地与 ECS 分别运行 `git status --short`，避免覆盖其他窗口的未提交修改；
3. 使用 `ssh hksr-m6b` 登录，不记录真实主机地址；
4. 确认远端目录为 `/home/ecs-user/hksr_database`；
5. 用 systemd 状态和健康接口检查应用；
6. 需要数据库时先运行 `deploy/diagnose-rds.py`；
7. 默认只做只读检查，写入、部署、重启和真实采集必须与当前任务范围一致；
8. 输出报告前检查其中没有凭据、私网地址、资源 ID 或原始私密响应。

如果某项凭据缺失或登录失败，只报告失败类别和非敏感状态，交由用户在控制台或私密配置中处理。
