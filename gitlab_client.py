"""GitLab.com API 客户端：查仓库是否存在、创建空仓库。"""
import urllib.parse

import requests

import config

_TIMEOUT = 30


class GitLabClient:
    def __init__(
        self,
        token: str = None,
        api_base: str = None,
        namespace_path: str = None,
        namespace_id: int = None,
    ):
        self.token = token or config.GITLAB_TOKEN
        self.api_base = (api_base or config.GITLAB_API_BASE).rstrip("/")
        self.namespace_path = namespace_path or config.GITLAB_NAMESPACE_PATH
        self.namespace_id = namespace_id or config.GITLAB_NAMESPACE_ID
        self.session = requests.Session()
        self.session.headers.update({"PRIVATE-TOKEN": self.token})

    def repo_exists(self, repo_path: str) -> bool:
        encoded = urllib.parse.quote(
            f"{self.namespace_path}/{repo_path}", safe=""
        )
        resp = self.session.get(
            f"{self.api_base}/projects/{encoded}", timeout=_TIMEOUT
        )
        if resp.status_code == 200:
            return True
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return False

    def create_repo(self, name: str, path: str, description: str = "") -> dict:
        body = {
            "name": name,
            "path": path,
            "namespace_id": self.namespace_id,
            "visibility": config.BACKUP_VISIBILITY,
            "description": description or "Backup from Aliyun Codeup",
            "initialize_with_readme": False,
        }
        resp = self.session.post(
            f"{self.api_base}/projects/", json=body, timeout=_TIMEOUT
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"创建 GitLab 仓库失败: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def push_url(self, repo_path: str) -> str:
        base = self.api_base.split("/api/")[0]
        host = urllib.parse.urlparse(base).netloc
        return (
            f"https://{host}/"
            f"{self.namespace_path}/{repo_path}.git"
        )
