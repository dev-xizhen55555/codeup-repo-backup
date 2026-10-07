"""Gitee API 客户端。"""
import requests

import config


class GiteeClient:
    def __init__(self):
        self.token = config.GITEE_TOKEN
        self.username = None
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"token {self.token}"})
        self._init_user()

    def _init_user(self):
        """获取当前用户信息"""
        resp = self.session.get("https://gitee.com/api/v5/user", timeout=30)
        resp.raise_for_status()
        user = resp.json()
        self.username = user.get("login")

    def list_repositories(self) -> list[dict]:
        """获取用户所有仓库"""
        repos: list[dict] = []
        page = 1

        while True:
            params = {"page": page, "per_page": 100, "type": "all"}
            resp = self.session.get(
                "https://gitee.com/api/v5/user/repos", params=params, timeout=30
            )
            resp.raise_for_status()
            data = resp.json()

            if not data:
                break

            repos.extend(data)

            total = int(resp.headers.get("total_count", 0))
            if page * 100 >= total:
                break

            page += 1

        return repos

    def repo_exists(self, repo_name: str) -> bool:
        """检查仓库是否存在"""
        url = f"https://gitee.com/api/v5/repos/{self.username}/{repo_name}"
        resp = self.session.get(url, timeout=30)
        return resp.status_code == 200

    def create_repo(self, name: str, description: str = "", private: bool = True) -> dict:
        """创建仓库"""
        body = {
            "name": name,
            "description": description,
            "private": private,
            "auto_init": False,
        }
        resp = self.session.post(
            "https://gitee.com/api/v5/user/repos", json=body, timeout=30
        )
        resp.raise_for_status()
        return resp.json()

    def push_url(self, repo_name: str) -> str:
        """构建Git push URL"""
        return f"https://gitee.com/{self.username}/{repo_name}.git"
