"""Git 镜像同步: 从 Codeup 镜像克隆, push --mirror 到目标平台."""
import os
import re
import shutil
import stat
import subprocess
import urllib.parse

import config

_GIT_TIMEOUT = 900
_LOW_SPEED_LIMIT = 1000
_LOW_SPEED_TIME = 60
_askpass_path = None


def _ensure_askpass() -> str:
    global _askpass_path
    if _askpass_path and os.path.exists(_askpass_path):
        return _askpass_path

    work_dir = os.path.abspath(config.WORK_DIR)
    os.makedirs(work_dir, exist_ok=True)
    path = os.path.join(work_dir, ".git-askpass.sh")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write('#!/bin/sh\nexec printf "%s\\n" "$GIT_PASSWORD"\n')
    os.chmod(path, stat.S_IRWXU)
    _askpass_path = path
    return path


def _mask(text: str) -> str:
    return re.sub(r"(//[^:/]+:)[^@]+(@)", r"\1***\2", text)


def _run_git(args: list[str], password: str, cwd: str = None) -> None:
    env = os.environ.copy()
    env["GIT_ASKPASS"] = _ensure_askpass()
    env["GIT_PASSWORD"] = password
    env["GIT_TERMINAL_PROMPT"] = "0"

    low_speed = [
        "-c", "credential.helper=",
        "-c", f"http.lowSpeedLimit={_LOW_SPEED_LIMIT}",
        "-c", f"http.lowSpeedTime={_LOW_SPEED_TIME}",
    ]
    result = subprocess.run(
        ["git", *low_speed, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
        env=env,
    )
    if result.returncode != 0:
        cmd_str = _mask("git " + " ".join(args))
        stderr = _mask(result.stderr.strip())
        if password:
            stderr = stderr.replace(password, "***").replace(urllib.parse.quote(password, safe=""), "***")
        raise RuntimeError(f"命令失败 [{cmd_str}]: {stderr}")


def _strip_credentials(url: str, username: str = "oauth2") -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    encoded_username = urllib.parse.quote(username, safe="")
    return urllib.parse.urlunparse(parsed._replace(netloc=f"{encoded_username}@{host}"))


def mirror_repo(
    codeup_http_url: str,
    target_push_url: str,
    repo_path: str,
    target_username: str = None,
    target_password: str = None,
) -> None:
    work_dir = os.path.abspath(config.WORK_DIR)
    os.makedirs(work_dir, exist_ok=True)
    mirror_dir = os.path.join(work_dir, f"{repo_path}.git")

    if os.path.exists(mirror_dir):
        shutil.rmtree(mirror_dir)

    src_url = _strip_credentials(codeup_http_url)

    # 所有目标的显式凭据交给 askpass, 避免 PAT 进入 URL 和进程参数.
    if target_password is not None:
        dst_url = _strip_credentials(target_push_url, username=target_username or "oauth2")
        dst_password = target_password
    else:
        raise ValueError("Docker 统一备份必须显式提供目标凭据")

    try:
        _run_git(["clone", "--mirror", src_url, mirror_dir], password=config.CODEUP_TOKEN)
        _run_git(["push", "--mirror", dst_url], password=dst_password, cwd=mirror_dir)
    finally:
        if os.path.exists(mirror_dir):
            shutil.rmtree(mirror_dir, ignore_errors=True)
