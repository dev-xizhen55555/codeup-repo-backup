# Codeup repository backup

Docker 专用的 Codeup 仓库备份工具, 支持顺序备份到 GitLab, Gitee 和 AtomGit. 支持定时调度, 分批并发, 增量状态和 S3 兼容对象存储配置.

此仓库仅包含运行代码, 配置模板和测试. 镜像构建不读取 Codeup 仓库, 不连接对象存储, 不需要业务 Token. 私有源码和运行配置不应提交到此公开仓库.

## GitHub Actions 与 GHCR

Pull Request 执行定向测试和 Docker 构建, 不登录或推送镜像. 合入 `main` 后执行相同验证并发布 GHCR 镜像. Actions 使用仓库自带的 `GITHUB_TOKEN`, 无需保存个人访问令牌或业务凭据. 第三方 Actions 固定 commit SHA, 发布 job 仅获得 `contents: read` 和 `packages: write`.

镜像地址:

```text
ghcr.io/dev-xizhen55555/codeup-repo-backup:v2.0
ghcr.io/dev-xizhen55555/codeup-repo-backup:latest
```

每次可信 `main` 构建还发布完整提交 SHA 标签, 便于精确回滚. `v2.0` 和 `latest` 是当前版本线的浮动标签. 默认构建 `linux/amd64`. 首次发布后需要在 GitHub 包设置中将容器包可见性设为 Public, 仓库公开不代表新容器包自动公开.

## Docker Compose 部署

创建本地 `.env` 文件, 仅供 Compose 注入启动参数. 不要提交它:

```dotenv
S3_ENDPOINT=https://your-object-storage-endpoint
S3_BUCKET=your-backup-bucket
S3_ACCESS_KEY_ID=your-access-key-id
S3_SECRET_ACCESS_KEY=your-secret-key
S3_REGION=your-region
ENV_FILE_KEY=codeupbackup.env
BACKUP_CRON=0 2 * * *
BATCH_SIZE=10
CONCURRENCY=2
```

对象存储访问密钥也是敏感凭据. 生产环境优先使用平台 Secret 注入, 避免放在命令历史或公开配置中. 对象存储需允许读取配置, 读写备份状态. Bucket 与配置对象不可公开.

在对象存储中创建 `codeupbackup.env`, 可参考 [.env.example](.env.example):

```dotenv
CODEUP_TOKEN=your-codeup-token
CODEUP_ORG_ID=your-organization-id

ATOMGIT_TOKEN=your-atomgit-token
ATOMGIT_API_BASE=https://api.atomgit.com/api/v5
S3_STATE_KEY_ATOMGIT=codeup-backup/state-atomgit.json

FORCE_FULL=false
CONCURRENCY=2
BATCH_SIZE=10
```

GitLab, Gitee, AtomGit 至少配置一个目标. 不配置的目标会跳过. AtomGit 备份在 Token 所属用户个人空间创建私有空仓库, 不初始化 README. PAT 需要 API 读取用户, 查询及创建仓库, 以及 Git 推送权限, 具体作用域名称以平台当前授权界面为准.

```bash
docker compose pull
docker compose up -d
docker compose logs -f backup
```

修改对象存储配置后执行 `docker compose restart backup`. 配置在进程启动时加载, 不会热更新. 程序按 `BACKUP_CRON` 执行, 启动时不立即备份. 默认每天 12:00, 时区 `Asia/Shanghai`.

默认只将状态端口绑定到本机:

```bash
curl http://127.0.0.1:8080/status
```

状态接口不带认证, 会显示对象存储端点, Bucket 和调度信息. 不要直接暴露到公网. `configured` 仅表示配置存在, 不代表凭据或推送成功.

## 备份范围与安全边界

`git clone --mirror` 与 `git push --mirror` 同步 Git 引用和提交历史. 推送可能强制覆盖或删除目标多余引用, 目标必须是专用备份仓库. 不自动删除目标仓库, 不备份 Issues, 附件或 Git LFS 实际对象; LFS 指针不等于对象备份.

AtomGit 使用独立增量状态, 同时记录 API 地址和登录账号. 首次启用或切换账号会全量备份. AtomGit 状态键不能与其他平台重复. 对同名公开, 可见性不明或响应冲突的 AtomGit 仓库拒绝推送, 不自动改变可见性.

GitLab 默认使用 `BACKUP_VISIBILITY=private` 创建目标, 可见性可配置; Gitee 创建私有目标. 对这两个平台的既有同名仓库, 使用前自行确认私有性. 不要将私人源码推到公共目标. 已配置的 AtomGit 鉴权失败会使任务返回失败. GitLab 和 Gitee 保留平台初始化阶段鉴权失败跳过的原有行为, 单仓库操作失败仍记为任务失败.

Git 凭据由 askpass 提供, 不放入目标 URL 或 Git 进程参数. 运行日志仍可能包含仓库路径和服务信息, 不要公开日志或将其作为公开 Actions artifact.

## 开发验证

```bash
python -m pip install -r requirements.txt
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
docker build -t codeup-backup:local .
```

测试使用合成配置与临时本地仓库, 不读取真实 `.env`, 不调用线上备份服务. Dockerfile 与 `.dockerignore` 使用运行文件白名单, 不将配置, 日志, Git 历史, 测试或文档打入镜像.

AtomGit 官方文档: [OpenAPI 使用入门](https://docs.atomgit.com/docs/apis/).
