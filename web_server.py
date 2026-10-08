"""Web HTTP 服务器 - 提供配置状态查看接口。"""
import os
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import threading


class StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """处理 GET 请求"""
        if self.path == '/status' or self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            # 获取配置信息
            s3_endpoint = os.getenv("S3_ENDPOINT", "")
            s3_bucket = os.getenv("S3_BUCKET", "")
            s3_region = os.getenv("S3_REGION", "us-east-1")
            backup_cron = os.getenv("BACKUP_CRON", "")

            # 提取 S3 根域名
            s3_domain = ""
            if s3_endpoint:
                parsed = urlparse(s3_endpoint)
                s3_domain = parsed.netloc or parsed.path

            # 默认 cron 表达式
            if not backup_cron:
                backup_cron = "0 12 * * *"  # 每天12点

            # 检查平台配置
            gitlab_configured = bool(
                os.getenv("GITLAB_TOKEN") and
                os.getenv("GITLAB_NAMESPACE_PATH") and
                os.getenv("GITLAB_NAMESPACE_ID")
            )
            gitee_configured = bool(os.getenv("GITEE_TOKEN"))
            atomgit_configured = bool(os.getenv("ATOMGIT_TOKEN", "").strip())
            github_configured = bool(os.getenv("GITHUB_BACKUP_TOKEN", "").strip())

            status = {
                "s3_domain": s3_domain,
                "s3_bucket": s3_bucket,
                "s3_region": s3_region,
                "backup_cron": backup_cron,
                "batch_size": int(os.getenv("BATCH_SIZE", "10")),
                "concurrency": int(os.getenv("CONCURRENCY", "3")),
                "platforms": {
                    "gitlab": "configured" if gitlab_configured else "not configured",
                    "gitee": "configured" if gitee_configured else "not configured",
                    "atomgit": "configured" if atomgit_configured else "not configured",
                    "github": "configured" if github_configured else "not configured"
                },
                "status": "running"
            }

            self.wfile.write(json.dumps(status, ensure_ascii=False, indent=2).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not Found')

    def log_message(self, format, *args):
        """自定义日志格式"""
        print(f"[HTTP] {self.address_string()} - {format % args}")


def start_web_server(port=8080):
    """启动 Web 服务器"""
    server = HTTPServer(('0.0.0.0', port), StatusHandler)
    print(f"[HTTP] Web 服务器启动在端口 {port}")
    print(f"[HTTP] 访问 http://localhost:{port}/status 查看配置状态")
    server.serve_forever()


def start_web_server_thread(port=8080):
    """在后台线程启动 Web 服务器"""
    thread = threading.Thread(target=start_web_server, args=(port,), daemon=True)
    thread.start()
    return thread
