"""GitHub 个人私有备份仓库客户端, 不接收任意 API 或 Git 主机."""
import re
import urllib.parse

import requests

import config

_TIMEOUT = 30


class GitHubClient:
    def __init__(self):
        self.token = config.GITHUB_BACKUP_TOKEN
        self.api_base = "https://api.github.com"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        self._push_urls: dict[str, str] = {}
        response = self.session.get(f"{self.api_base}/user", timeout=_TIMEOUT, allow_redirects=False)
        self._check_response(response)
        user = response.json()
        self.username = user.get("login")
        self.user_id = user.get("id")
        if not isinstance(self.username, str) or not self.username.strip() or type(self.user_id) is not int:
            raise RuntimeError("GitHub 当前用户响应缺少有效 login 或 id")

    @staticmethod
    def _check_response(response) -> None:
        # 重命名和转移会触发重定向, 不能把源代码推到未经校验的新位置.
        if not 200 <= response.status_code < 300:
            response.raise_for_status()
            raise RuntimeError(f"GitHub API 返回非成功状态: {response.status_code}")

    @staticmethod
    def _validate_path(path: str) -> None:
        # GitHub 会替换不支持的字符, 提前拒绝以避免两个源仓库映射到同一目标.
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", path) or path in (".", ".."):
            raise ValueError("Codeup 仓库 path 不是有效的 GitHub 仓库名, 拒绝自动改名")

    def _repo_url(self, path: str) -> str:
        self._validate_path(path)
        owner = urllib.parse.quote(self.username, safe="")
        return f"{self.api_base}/repos/{owner}/{urllib.parse.quote(path, safe='')}"

    def _validate_private_repo(self, path: str, repository: dict) -> str:
        owner = repository.get("owner") or {}
        expected_full_name = f"{self.username}/{path}"
        if (
            repository.get("private") is not True
            or repository.get("visibility") not in (None, "private")
            or repository.get("archived") is not False
            or repository.get("disabled") is True
        ):
            raise RuntimeError(f"GitHub 仓库 {path} 非私有, 已归档或不可用, 拒绝推送")
        if (
            owner.get("id") != self.user_id
            or owner.get("login", "").lower() != self.username.lower()
            or repository.get("full_name", "").lower() != expected_full_name.lower()
            or repository.get("name", "").lower() != path.lower()
        ):
            raise RuntimeError(f"GitHub 仓库 {path} 的归属或路径不匹配, 拒绝推送")
        push_url = repository.get("clone_url", "")
        parsed = urllib.parse.urlparse(push_url)
        if (
            parsed.scheme != "https" or parsed.hostname != "github.com"
            or parsed.port not in (None, 443)
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment
            or urllib.parse.unquote(parsed.path).lower() != f"/{expected_full_name}.git".lower()
        ):
            raise RuntimeError("GitHub 返回的 clone_url 无效或与目标仓库不匹配")
        return push_url

    def repo_exists(self, path: str) -> bool:
        self._push_urls.pop(path, None)
        response = self.session.get(self._repo_url(path), timeout=_TIMEOUT, allow_redirects=False)
        if response.status_code == 404:
            self._push_urls.pop(path, None)
            return False
        self._check_response(response)
        push_url = self._validate_private_repo(path, response.json())
        permissions = self.session.get(
            f"{self._repo_url(path)}/actions/permissions", timeout=_TIMEOUT, allow_redirects=False
        )
        self._check_response(permissions)
        # 备份 workflow 文件不能执行源项目的 CI, 既有仓库设置不由同步器擅自修改.
        if permissions.json().get("enabled") is not False:
            self._push_urls.pop(path, None)
            raise RuntimeError(f"GitHub 仓库 {path} 仍启用 Actions, 请先禁用后再备份")
        self._push_urls[path] = push_url
        return True

    def create_repo(self, name: str, path: str, description: str = "") -> dict:
        self._validate_path(path)
        # 目标名称使用源 path, 显示名称可能包含空格等无法稳定映射的字符.
        response = self.session.post(
            f"{self.api_base}/user/repos",
            json={"name": path, "description": description or "Backup from Aliyun Codeup",
                  "private": True, "auto_init": False},
            timeout=_TIMEOUT,
            allow_redirects=False,
        )
        self._check_response(response)
        repository = response.json()
        self._validate_private_repo(path, repository)
        permissions = self.session.put(
            f"{self._repo_url(path)}/actions/permissions", json={"enabled": False},
            timeout=_TIMEOUT, allow_redirects=False,
        )
        self._check_response(permissions)
        if not self.repo_exists(path):
            raise RuntimeError(f"GitHub 创建仓库 {path} 后仍无法读取详情")
        return repository

    def push_url(self, path: str) -> str:
        if path not in self._push_urls and not self.repo_exists(path):
            raise RuntimeError(f"GitHub 仓库 {path} 不存在或无权访问")
        return self._push_urls[path]
