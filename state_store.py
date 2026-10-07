"""增量备份状态存储: 记录每个仓库上次同步时的 lastActivityAt."""
import json

import config


def _atomgit_state_location(use_s3: bool) -> str:
    if use_s3:
        location = config.S3_STATE_KEY_ATOMGIT
        other_locations = (config.S3_STATE_KEY, config.S3_STATE_KEY_GITEE)
    else:
        import os

        location = config.LOCAL_STATE_FILE_ATOMGIT
        other_locations = (
            config.LOCAL_STATE_FILE, config.LOCAL_STATE_FILE_GITEE,
        )
        other_locations = tuple(os.path.abspath(path) for path in other_locations)
    comparable = location if use_s3 else os.path.abspath(location)
    # 手动配置也必须保持状态隔离, 否则首次 AtomGit 备份可能误用其他平台记录.
    if not location or comparable in other_locations:
        raise ValueError("AtomGit 状态位置必须非空且与其他备份平台独立")
    return location


class _S3Store:
    def __init__(self, use_gitee: bool = False, use_atomgit: bool = False):
        import boto3
        from botocore.config import Config

        kwargs = {
            "service_name": "s3",
            "endpoint_url": config.S3_ENDPOINT,
            "aws_access_key_id": config.S3_ACCESS_KEY_ID,
            "aws_secret_access_key": config.S3_SECRET_ACCESS_KEY,
            "region_name": config.S3_REGION or None,
            "config": Config(s3={"addressing_style": "path"}),
        }
        if config.S3_SESSION_TOKEN:
            kwargs["aws_session_token"] = config.S3_SESSION_TOKEN

        if use_atomgit:
            self._key = _atomgit_state_location(use_s3=True)
        elif use_gitee:
            self._key = config.S3_STATE_KEY_GITEE
        else:
            self._key = config.S3_STATE_KEY
        self._bucket = config.S3_BUCKET
        self._client = boto3.client(**kwargs)

    def load(self) -> dict:
        from botocore.exceptions import ClientError

        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=self._key)
            data = json.loads(resp["Body"].read().decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "NoSuchBucket", "404", "NotFound"):
                return {}
            raise

    def save(self, state: dict) -> None:
        body = json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8")
        self._client.put_object(
            Bucket=self._bucket,
            Key=self._key,
            Body=body,
            ContentType="application/json",
        )

    def describe(self) -> str:
        return f"S3 对象存储 {self._bucket}/{self._key}"


class _LocalStore:
    def __init__(self, use_gitee: bool = False, use_atomgit: bool = False):
        if use_atomgit:
            self._path = _atomgit_state_location(use_s3=False)
        elif use_gitee:
            self._path = config.LOCAL_STATE_FILE_GITEE
        else:
            self._path = config.LOCAL_STATE_FILE

    def load(self) -> dict:
        import os

        if not os.path.exists(self._path):
            return {}
        with open(self._path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
            return data if isinstance(data, dict) else {}

    def save(self, state: dict) -> None:
        with open(self._path, "w", encoding="utf-8") as fp:
            json.dump(state, fp, ensure_ascii=False, indent=2)

    def describe(self) -> str:
        return f"本地文件 {self._path}"


def get_store(use_gitee: bool = False, use_atomgit: bool = False):
    if config.S3_ENABLED:
        return _S3Store(use_gitee=use_gitee, use_atomgit=use_atomgit)
    return _LocalStore(use_gitee=use_gitee, use_atomgit=use_atomgit)
