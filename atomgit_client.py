"""AtomGit API 客户端: 创建并校验个人私有备份仓库."""
import urllib.parse

import requests

import config

_TIMEOUT = 30
_GIT_HOSTS = {"atomgit.com", "gitcode.com", "hub.gitcode.com"}


class AtomGitClient:
    def __init__(self):
        self.token = config.ATOMGIT_TOKEN
        self.api_base = config.ATOMGIT_API_BASE
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        self._push_urls: dict[str, str] = {}

        response = self.session.get(f"{self.api_base}/user", timeout=_TIMEOUT)
        response.raise_for_status()
        self.username = response.json().get("login")
        if not isinstance(self.username, str) or not self.username.strip():
            raise RuntimeError("AtomGit 当前用户响应缺少 login, 无法定位个人空间")

    def _repo_url(self, repo_path: str) -> str:
        owner = urllib.parse.quote(self.username, safe="")
        path = urllib.parse.quote(repo_path, safe="")
        return f"{self.api_base}/repos/{owner}/{path}"

    def _remember_private_repo(self, repo_path: str, repository: dict) -> None:
        # 同名公开仓库不能接收私有源代码, 请求和返回都需要检查可见性.
        visibility = repository.get("visibility")
        private_flag = repository.get("private")
        public_flag = repository.get("public")
        is_private = private_flag in (True, 1) or visibility == "private"
        is_public = public_flag in (True, 1) or visibility == "public"
        conflicting_private = "private" in repository and private_flag not in (True, 1)
        unknown_public = "public" in repository and public_flag not in (False, 0)
        if (
            not is_private or is_public or conflicting_private or unknown_public
            or visibility not in (None, "private")
        ):
            raise RuntimeError(f"AtomGit 仓库 {repo_path} 为公开仓库或可见性不明, 拒绝推送")
        if repository.get("path") != repo_path:
            raise RuntimeError(f"AtomGit 返回的仓库路径与 {repo_path} 不一致, 拒绝推送")

        push_url = repository.get("http_url_to_repo", "")
        parsed = urllib.parse.urlparse(push_url)
        # 仅向官方 Git 主机发送凭据, 不信任响应中的任意推送地址.
        if (
            parsed.scheme != "https"
            or parsed.hostname not in _GIT_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError("AtomGit 返回的 http_url_to_repo 无效或指向非官方主机")
        expected_path = f"/{self.username}/{repo_path}.git"
        if urllib.parse.unquote(parsed.path) != expected_path:
            raise RuntimeError("AtomGit 返回的推送地址与个人仓库路径不一致, 拒绝推送")
        self._push_urls[repo_path] = push_url

    def repo_exists(self, repo_path: str) -> bool:
        response = self.session.get(self._repo_url(repo_path), timeout=_TIMEOUT)
        if response.status_code == 404:
            self._push_urls.pop(repo_path, None)
            return False
        response.raise_for_status()
        self._remember_private_repo(repo_path, response.json())
        return True

    def create_repo(self, name: str, path: str, description: str = "") -> dict:
        body = {
            "name": name,
            "path": path,
            "description": description or "Backup from Aliyun Codeup",
            "private": True,
            "auto_init": False,
        }
        response = self.session.post(
            f"{self.api_base}/user/repos", json=body, timeout=_TIMEOUT
        )
        response.raise_for_status()
        repository = response.json()
        # 创建接口的成功响应和可见性字段存在文档差异, 再读取详情确认后才推送.
        if not self.repo_exists(path):
            raise RuntimeError(f"AtomGit 创建仓库 {path} 后仍无法读取详情")
        return repository

    def push_url(self, repo_path: str) -> str:
        if repo_path not in self._push_urls:
            if not self.repo_exists(repo_path):
                raise RuntimeError(f"AtomGit 仓库 {repo_path} 不存在")
        return self._push_urls[repo_path]
