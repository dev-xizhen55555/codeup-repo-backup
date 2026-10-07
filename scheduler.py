"""定时调度器：根据 BACKUP_CRON 环境变量定时执行备份任务。"""
import os
import sys
import time
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger


def _log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


def run_scheduler(backup_func, backup_name: str = "backup"):
    """启动定时调度器。

    Args:
        backup_func: 备份函数（需返回 int，0表示成功）
        backup_name: 备份任务名称
    """
    cron_expr = os.getenv("BACKUP_CRON", "").strip()

    # 默认 cron: 每天12点
    if not cron_expr:
        cron_expr = "0 12 * * *"
        _log(f"未设置 BACKUP_CRON，使用默认值: {cron_expr}")

    _log(f"定时备份已启动，cron 表达式: {cron_expr}")
    _log(f"任务名称: {backup_name}")

    scheduler = BlockingScheduler(timezone="Asia/Shanghai")

    try:
        # 解析 cron 表达式（支持标准 5 字段格式）
        parts = cron_expr.split()
        if len(parts) != 5:
            raise ValueError(
                f"BACKUP_CRON 格式错误，需要 5 个字段 (minute hour day month day_of_week)，当前: {cron_expr}"
            )

        minute, hour, day, month, day_of_week = parts

        trigger = CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone="Asia/Shanghai",
        )

        scheduler.add_job(
            backup_func,
            trigger=trigger,
            id=backup_name,
            name=backup_name,
            max_instances=1,  # 防止并发执行
        )

        _log("调度器运行中，按 Ctrl+C 退出\n")

        scheduler.start()

    except (ValueError, KeyboardInterrupt) as e:
        if isinstance(e, KeyboardInterrupt):
            _log("收到退出信号，停止调度器")
        else:
            _log(f"Cron 表达式解析失败: {e}")
        sys.exit(1)
    except Exception as e:
        _log(f"调度器异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
