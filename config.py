"""集中读取备份所需的所有凭据与配置."""
import os
import sys

# Docker 启动必须提供 S3 配置来源, 不读取本地 .env.
_missing_s3_settings = [
    key for key in ("S3_ENDPOINT", "S3_BUCKET") if not os.getenv(key, "").strip()
]
if _missing_s3_settings:
    print(
        f"[配置错误] Docker 启动必须设置环境变量: {', '.join(_missing_s3_settings)}",
        file=sys.stderr,
    )
    sys.exit(1)

from s3_config_loader import load_env_from_s3

load_env_from_s3()


def _require(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        print(f"[配置错误] 环境变量 {key} 未设置, 请检查 S3 配置文件和环境变量", file=sys.stderr)
        sys.exit(1)
    return value


# ===== Codeup =====
CODEUP_TOKEN = _require("CODEUP_TOKEN")
CODEUP_ORG_ID = _require("CODEUP_ORG_ID")
CODEUP_DOMAIN = os.getenv("CODEUP_DOMAIN", "openapi-rdc.aliyuncs.com").strip()

# ===== GitLab =====
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN", "").strip()
GITLAB_NAMESPACE_PATH = os.getenv("GITLAB_NAMESPACE_PATH", "").strip()
GITLAB_NAMESPACE_ID = int(os.getenv("GITLAB_NAMESPACE_ID", "0"))
GITLAB_API_BASE = os.getenv("GITLAB_API_BASE", "https://gitlab.com/api/v4").strip().rstrip("/")

# ===== Gitee =====
GITEE_TOKEN = os.getenv("GITEE_TOKEN", "").strip()

# ===== AtomGit =====
ATOMGIT_TOKEN = os.getenv("ATOMGIT_TOKEN", "").strip()
ATOMGIT_API_BASE = os.getenv("ATOMGIT_API_BASE", "https://api.atomgit.com/api/v5").strip().rstrip("/")

# ===== 备份行为 =====
BACKUP_VISIBILITY = os.getenv("BACKUP_VISIBILITY", "private").strip()
WORK_DIR = os.getenv("WORK_DIR", "./.backup_work").strip()
CONCURRENCY = int(os.getenv("CONCURRENCY", "2"))  # 每批内的并发 worker 数
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "10"))  # 每批处理的仓库数量
FORCE_FULL = os.getenv("FORCE_FULL", "false").strip().lower() in ("1", "true", "yes")

# ===== 增量状态存储 (S3 兼容对象存储) =====
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "").strip()
S3_BUCKET = os.getenv("S3_BUCKET", "").strip()
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID", os.getenv("S3_ACCESS_KEY", "")).strip()
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY", os.getenv("S3_SECRET_KEY", "")).strip()
S3_SESSION_TOKEN = os.getenv("S3_SESSION_TOKEN", "").strip()
S3_REGION = os.getenv("S3_REGION", "").strip()
S3_STATE_KEY = os.getenv("S3_STATE_KEY", "codeup-backup/state.json").strip()
S3_STATE_KEY_GITEE = os.getenv("S3_STATE_KEY_GITEE", "codeup-backup/state-gitee.json").strip()
S3_STATE_KEY_ATOMGIT = os.getenv("S3_STATE_KEY_ATOMGIT", "codeup-backup/state-atomgit.json").strip()
LOCAL_STATE_FILE = os.getenv("LOCAL_STATE_FILE", "./.backup_state.json").strip()
LOCAL_STATE_FILE_GITEE = os.getenv("LOCAL_STATE_FILE_GITEE", "./.backup_state_gitee.json").strip()
LOCAL_STATE_FILE_ATOMGIT = os.getenv("LOCAL_STATE_FILE_ATOMGIT", "./.backup_state_atomgit.json").strip()
S3_ENABLED = bool(S3_ENDPOINT and S3_BUCKET and S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY)
