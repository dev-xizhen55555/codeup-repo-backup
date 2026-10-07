"""Docker 统一备份入口: 依次备份到 GitLab, Gitee 和 AtomGit."""
import sys
from datetime import datetime

import config
from codeup_client import CodeupClient
from gitlab_client import GitLabClient
from gitee_client import GiteeClient
from atomgit_client import AtomGitClient
import git_sync
import state_store


def _log(msg: str, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", file=stream, flush=True)


def backup_to_platform(platform_name: str, client, state_key: str, repos: list[dict]) -> tuple[int, int, int]:
    """备份到指定平台

    Returns:
        (成功数, 失败数, 跳过数)
    """
    _log(f"\n{'='*60}")
    _log(f"开始备份到 {platform_name}")
    _log(f"{'='*60}")

    store = state_store.get_store(
        use_gitee=(platform_name == "Gitee"),
        use_atomgit=(state_key == "atomgit"),
    )

    atomgit_target = None
    if state_key == "atomgit":
        atomgit_target = {"api_base": client.api_base, "login": client.username}

    # 加载状态
    if config.FORCE_FULL:
        state = {}
        _log(f"FORCE_FULL 已开启，全量同步")
    else:
        try:
            state = store.load()
            if atomgit_target is not None:
                # 切换账号或 API 地址后, 旧目标的成功记录不能用于新目标.
                if state.get("target") == atomgit_target and isinstance(state.get("repositories"), dict):
                    state = state["repositories"]
                else:
                    state = {}
                    _log("AtomGit 目标身份变化或尚无状态, 本次全量同步")
            _log(f"增量状态来自 {store.describe()} (已记录 {len(state)} 个仓库)")
        except Exception as exc:
            state = {}
            _log(f"增量状态加载失败，本次全量同步: {exc}", err=True)

    # 筛选需要同步的仓库
    pending = []
    unchanged = []
    for repo in repos:
        repo_path = repo.get("path") or repo.get("name", "")
        last_activity = repo.get("lastActivityAt", "")
        if (
            not config.FORCE_FULL
            and last_activity
            and state.get(repo_path) == last_activity
        ):
            unchanged.append(repo_path)
            continue
        pending.append(repo)

    if unchanged:
        _log(f"跳过 {len(unchanged)} 个未变化仓库")

    pending_total = len(pending)
    if pending_total == 0:
        _log(f"没有需要同步到 {platform_name} 的仓库")
        return (0, 0, 0)

    activity_map = {
        (r.get("path") or r.get("name", "")): r.get("lastActivityAt", "")
        for r in pending
    }

    # 分批处理
    from concurrent.futures import ThreadPoolExecutor

    batch_size = config.BATCH_SIZE
    batches = [pending[i:i + batch_size] for i in range(0, pending_total, batch_size)]
    total_batches = len(batches)

    _log(f"配置: {pending_total} 个仓库, {total_batches} 批, 每批 {batch_size} 个, {config.CONCURRENCY} 并发")

    all_succeeded = []
    all_failed = []
    all_skipped = []

    for batch_num, batch in enumerate(batches, 1):
        _log(f"\n处理第 {batch_num}/{total_batches} 批 ({len(batch)} 个仓库)")

        succeeded = []
        failed = []
        skipped = []

        with ThreadPoolExecutor(max_workers=config.CONCURRENCY) as pool:
            futures = []
            for idx, repo in enumerate(batch, 1):
                name = repo.get("name", "")
                repo_path = repo.get("path") or name
                http_url = repo.get("httpUrlToRepo", "")
                description = repo.get("description", "") or ""

                if not http_url:
                    skipped.append(repo_path)
                    continue

                future = pool.submit(
                    _sync_one_repo,
                    client,
                    platform_name,
                    repo_path,
                    name,
                    http_url,
                    description,
                    idx,
                    len(batch)
                )
                futures.append((future, repo_path))

            for future, repo_path in futures:
                status, detail = future.result()
                if status == "成功":
                    succeeded.append(repo_path)
                    if activity_map.get(repo_path):
                        state[repo_path] = activity_map[repo_path]
                elif status == "失败":
                    failed.append((repo_path, detail))
                else:
                    skipped.append(repo_path)

        all_succeeded.extend(succeeded)
        all_failed.extend(failed)
        all_skipped.extend(skipped)

        # 每批保存状态
        if succeeded:
            try:
                saved_state = state
                if atomgit_target is not None:
                    saved_state = {"target": atomgit_target, "repositories": state}
                store.save(saved_state)
                _log(f"第 {batch_num} 批状态已保存")
            except Exception as exc:
                _log(f"状态保存失败: {exc}", err=True)

    _log(f"\n{platform_name} 备份完成: 成功 {len(all_succeeded)}, 失败 {len(all_failed)}, 跳过 {len(all_skipped)}")

    if all_failed:
        _log(f"\n{platform_name} 失败明细:")
        for path, err in all_failed:
            _log(f"  - {path}: {err}")

    return (len(all_succeeded), len(all_failed), len(all_skipped))


def _sync_one_repo(client, platform_name: str, repo_path: str, name: str, http_url: str, description: str, idx: int, total: int) -> tuple[str, str]:
    """同步单个仓库"""
    import time

    prefix = f"[{idx}/{total}] {repo_path}"

    try:
        # Gitee 需要限流
        if platform_name == "Gitee":
            time.sleep(0.3)

        # 检查仓库是否存在
        exists = client.repo_exists(repo_path)

        if exists:
            _log(f"{prefix} → {platform_name} 已存在，镜像覆盖")
        else:
            _log(f"{prefix} → {platform_name} 不存在，创建仓库")
            if platform_name in ("GitLab", "AtomGit"):
                client.create_repo(name=name, path=repo_path, description=description)
            else:
                client.create_repo(name=repo_path, description=description, private=True)

        push_url = client.push_url(repo_path)
        git_sync.mirror_repo(
            http_url, push_url, repo_path,
            target_username=client.username if platform_name != "GitLab" else "oauth2",
            target_password=client.token,
        )
        _log(f"{prefix} → 同步成功")
        return ("成功", "")

    except Exception as exc:
        _log(f"{prefix} → 失败: {exc}", err=True)
        return ("失败", str(exc))


def backup() -> int:
    """执行完整备份流程"""
    _log("="*60)
    _log("Codeup 统一备份任务开始")
    _log("="*60)

    # 获取 Codeup 仓库列表
    codeup = CodeupClient()
    _log("正在从 Codeup 拉取仓库列表 ...")
    repos = codeup.list_repositories()
    total = len(repos)
    _log(f"共获取 {total} 个 Codeup 仓库")

    # 检查平台配置
    gitlab_configured = bool(
        config.GITLAB_TOKEN and
        config.GITLAB_NAMESPACE_PATH and
        config.GITLAB_NAMESPACE_ID
    )
    gitee_configured = bool(config.GITEE_TOKEN)

    atomgit_configured = bool(config.ATOMGIT_TOKEN)

    if not any((gitlab_configured, gitee_configured, atomgit_configured)):
        _log("错误: GitLab, Gitee 和 AtomGit 都未配置, 无法执行备份", err=True)
        return 1

    total_success = 0
    total_failed = 0
    has_error = False

    platforms = [
        ("GitLab", "gitlab", gitlab_configured, GitLabClient),
        ("Gitee", "gitee", gitee_configured, GiteeClient),
        ("AtomGit", "atomgit", atomgit_configured, AtomGitClient),
    ]
    for platform_name, state_key, configured, client_class in platforms:
        if not configured:
            _log(f"\n{platform_name} 未配置, 跳过")
            continue
        try:
            client = client_class()
            success, failed, skipped = backup_to_platform(platform_name, client, state_key, repos)
            total_success += success
            total_failed += failed
            if failed > 0:
                has_error = True
        except Exception as exc:
            error_str = str(exc).lower()
            auth_error = any(word in error_str for word in ("401", "unauthorized", "authentication"))
            # 保留旧平台鉴权失败跳过的行为, 新配置的 AtomGit 失败必须让任务报错.
            if auth_error and platform_name != "AtomGit":
                _log(f"{platform_name} 鉴权失败(401), 跳过: {exc}", err=True)
            else:
                _log(f"{platform_name} 备份失败: {exc}", err=True)
                has_error = True

    # 最终报告
    _log("\n" + "="*60)
    _log("所有备份任务完成")
    _log("="*60)
    _log(f"总计: 成功 {total_success}, 失败 {total_failed}")

    return 1 if has_error else 0


if __name__ == "__main__":
    # 启动 Web 服务器
    from web_server import start_web_server_thread
    start_web_server_thread(port=8080)

    # 启动定时调度
    from scheduler import run_scheduler
    run_scheduler(backup, "unified-backup")
