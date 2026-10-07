"""Codeup（阿里云云效）API 客户端：分页拉取所有仓库。"""
import requests

import config

_PER_PAGE = 100
_TIMEOUT = 30


class CodeupClient:
    def __init__(self, token: str = None, org_id: str = None, domain: str = None):
        self.token = token or config.CODEUP_TOKEN
        self.org_id = org_id or config.CODEUP_ORG_ID
        self.domain = domain or config.CODEUP_DOMAIN
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "x-yunxiao-token": self.token,
        })

    def list_repositories(self) -> list[dict]:
        repos: list[dict] = []
        page = 1
        url = (
            f"https://{self.domain}/oapi/v1/codeup/organizations/"
            f"{self.org_id}/repositories"
        )

        while True:
            resp = self.session.get(
                url,
                params={"page": page, "perPage": _PER_PAGE},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            if not isinstance(data, list):
                raise RuntimeError(f"Codeup 返回非预期格式: {data}")

            repos.extend(data)

            total = int(resp.headers.get("x-total", 0))
            if page * _PER_PAGE >= total or not data:
                break
            page += 1

        return repos

    def list_all_repositories(self) -> list[dict]:
        return self.list_repositories()
