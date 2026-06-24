# -*- coding: utf-8 -*-
"""
src/shared/async_runner.py — 轻量级 fire-and-forget 异步执行器

本项目主进程是同步的（Streamlit / CLI），但部分操作（LLM 分类、
LLM 错误诊断）跑在同步请求线程里会阻塞用户感知。这种场景下需要
"启动后台线程跑协程、不等结果"的模式。

API：
    fire_and_forget(my_coro, name="msg-classify")
"""

import asyncio
import logging
import threading


def fire_and_forget(coro, *, name: str = "anon") -> threading.Thread:
    """
    在新后台线程里跑协程。线程是 daemon，主进程退出时一起死。

    协程里抛任何异常都会被 logger.exception 捕获，不影响主线程。

    Returns the started Thread (mostly for tests).
    """
    def _runner():
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        except Exception:
            logging.getLogger(__name__).exception(
                "fire_and_forget[%s] failed", name
            )
        finally:
            loop.close()

    t = threading.Thread(
        target=_runner,
        name=f"ff-{name}",
        daemon=True,
    )
    t.start()
    return t
