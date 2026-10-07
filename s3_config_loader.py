"""从 S3/OSS 加载配置文件到环境变量。"""
import os
import tempfile
import boto3
from botocore.exceptions import ClientError


def load_env_from_s3() -> None:
    """从 S3 下载配置文件并加载到环境变量。

    需要的环境变量：
    - S3_ENDPOINT: S3/OSS 端点
    - S3_BUCKET: 存储桶名称
    - S3_ACCESS_KEY_ID: 访问密钥 ID
    - S3_SECRET_ACCESS_KEY: 访问密钥
    - S3_REGION: 区域（可选，默认 us-east-1）
    - ENV_FILE_KEY: 配置文件在 OSS 中的 key（可选，默认 codeupbackup.env）
    """
    endpoint = os.getenv("S3_ENDPOINT")
    bucket = os.getenv("S3_BUCKET")
    access_key = os.getenv("S3_ACCESS_KEY_ID")
    secret_key = os.getenv("S3_SECRET_ACCESS_KEY")
    region = os.getenv("S3_REGION", "us-east-1")
    env_file_key = os.getenv("ENV_FILE_KEY", "codeupbackup.env")

    if not all([endpoint, bucket, access_key, secret_key]):
        raise RuntimeError(
            "缺少 S3 配置环境变量: S3_ENDPOINT, S3_BUCKET, "
            "S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY"
        )

    tmp_path = None
    try:
        s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

        # 下载到临时文件
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".env") as tmp:
            tmp_path = tmp.name

        s3_client.download_file(bucket, env_file_key, tmp_path)
        print(f"已从 OSS 下载配置: s3://{bucket}/{env_file_key}")

        # 加载环境变量
        env_count = 0
        with open(tmp_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    # 移除引号
                    value = value.strip().strip('"').strip("'")
                    os.environ[key.strip()] = value
                    env_count += 1

        print(f"已加载 {env_count} 个环境变量")

    except ClientError as e:
        raise RuntimeError(f"从 OSS 下载配置失败: {e}")
    except Exception as e:
        raise RuntimeError(f"加载配置失败: {e}")
    finally:
        # 即使配置下载或解析失败, 也不遗留明文凭据临时文件.
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
