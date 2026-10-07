FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 白名单复制运行代码, 配置和凭据只在容器启动时从对象存储读取.
COPY unified_backup.py config.py codeup_client.py gitlab_client.py gitee_client.py \
     atomgit_client.py git_sync.py state_store.py s3_config_loader.py \
     scheduler.py web_server.py ./

RUN mkdir -p /tmp/backup_work
ENV PYTHONUNBUFFERED=1 \
    WORK_DIR=/tmp/backup_work
EXPOSE 8080
CMD ["python3", "unified_backup.py"]
