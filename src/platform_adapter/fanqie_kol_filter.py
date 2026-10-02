# -*- coding: utf-8 -*-
"""
src/platform_adapter/fanqie_kol_filter.py — 番茄达人中心内容库筛选

Harness Engineering Layer 5: 用户传入参数**每类单选**，多选报错。

KOL 中心 list 实际有 7 类筛选（task-menu 切 + 6 个 filter-row）：
  - task-menu-second: 榜单（爆款/阅读/潜力/全部内容）
  - filter-row[0]: status 连载状态（-1/1/0）
  - filter-row[1]: gender 男频/女频/通用（-1/1/0/2）
  - filter-row[2]: copyright 番茄独家/非独家（-1/2/1）
  - filter-row[3]: category 题材（30 个 mapping_id）
  - filter-row[4]: days 更新时间（-1/1/2/3/4/5）
  - filter-row[5]: word_count 字数（-1/"100,150"/"500,0" 等 min,max）

URL 参数不刷切（task-menu 切不刷 URL），必须 click 切。
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from src.shared.logger import logger


class FilterValidationError(ValueError):
    """筛选参数校验失败（多选 / 不在枚举 / 缺必填）。"""


@dataclass
class KolFilterArgs:
    """KOL 中心筛选参数。**每类最多选一个值，不传默认 "all"**。"""

    # 必填
    ranking: str = "爆款榜"          # 必填 4 选 1
    target_count: int = 40          # 必填 > 0

    # 选填（每类单选）
    status: str = "all"             # 全部 / 连载中 / 已完结
    gender: str = "all"             # 全部 / 男频 / 女频 / 通用
    copyright: str = "all"          # 全部 / 番茄独家 / 非独家
    category: dict | None = None    # None 或 {mapping_id, category_ids}
    days: str = "all"               # 全部 / 近1天 / 近5天 / 近10天 / 1个月内 / 1个月以上
    word_count: str = "all"         # 全部 / <100 / 100-150 / 150-200 / 200-300 / 300-500 / >500

    # ── 枚举（每类单选）────────────────────────────────
    _ALLOWED_RANKING = ("爆款榜", "阅读榜", "潜力榜", "全部内容")
    _ALLOWED_STATUS = ("all", "serial", "done")
    _ALLOWED_GENDER = ("all", "male", "female", "general")
    _ALLOWED_COPYRIGHT = ("all", "exclusive", "non_exclusive")
    _ALLOWED_DAYS = ("all", "1d", "5d", "10d", "30d", "30d+")
    _ALLOWED_WORD_COUNT = ("all", "<100", "100-150", "150-200", "200-300", "300-500", ">500")

    # ── 映射（业务 key → radio value）──────────────────
    _RANKING_TO_RADIO_VALUE = {
        "爆款榜": 1, "阅读榜": 2, "潜力榜": 3, "全部内容": 4,
    }
    _STATUS_TO_RADIO_VALUE = {
        "all": "-1", "serial": "1", "done": "0",
    }
    _GENDER_TO_RADIO_VALUE = {
        "all": "-1", "male": "1", "female": "0", "general": "2",
    }
    _COPYRIGHT_TO_RADIO_VALUE = {
        "all": "-1", "exclusive": "2", "non_exclusive": "1",
    }
    _DAYS_TO_RADIO_VALUE = {
        "all": "-1", "1d": "1", "5d": "2", "10d": "3", "30d": "4", "30d+": "5",
    }
    _WORD_COUNT_TO_RADIO_VALUE = {
        "all": "-1", "<100": "0,100", "100-150": "100,150", "150-200": "150,200",
        "200-300": "200,300", "300-500": "300,500", ">500": "500,0",
    }

    # ── row index（filter-row 在第几个）────────────────
    _ROW_INDEX = {
        "status": 0,
        "gender": 1,
        "copyright": 2,
        "category": 3,
        "days": 4,
        "word_count": 5,
    }

    def validate(self) -> None:
        """校验单选约束。失败抛 FilterValidationError。"""
        # ranking 必填 + 必单选
        if not self.ranking:
            raise FilterValidationError(
                "ranking 必填（4 选 1：爆款榜/阅读榜/潜力榜/全部内容）"
            )
        if self.ranking not in self._ALLOWED_RANKING:
            raise FilterValidationError(
                f"ranking 必须是单选, 允许: {list(self._ALLOWED_RANKING)}, got: {self.ranking!r}"
            )

        # target_count 必填 > 0
        if not isinstance(self.target_count, int) or self.target_count < 1:
            raise FilterValidationError(
                f"target_count 必填且 > 0, got: {self.target_count!r}"
            )

        # 其它 6 类：单选
        for field_name, allowed in [
            ("status", self._ALLOWED_STATUS),
            ("gender", self._ALLOWED_GENDER),
            ("copyright", self._ALLOWED_COPYRIGHT),
            ("days", self._ALLOWED_DAYS),
            ("word_count", self._ALLOWED_WORD_COUNT),
        ]:
            v = getattr(self, field_name)
            if v not in allowed:
                raise FilterValidationError(
                    f"{field_name} 必须是单选, 允许: {list(allowed)}, got: {v!r}"
                )

        # category 必须是 dict 或 None
        if self.category is not None:
            if not isinstance(self.category, dict):
                raise FilterValidationError(
                    f"category 必须是 dict 或 None, got: {type(self.category).__name__}"
                )
            if "mapping_id" not in self.category or "category_ids" not in self.category:
                raise FilterValidationError(
                    "category dict 必须含 'mapping_id' 和 'category_ids'"
                )

    def to_dict(self) -> dict:
        """转 dict（描述用，不用于 click 逻辑）。"""
        return asdict(self)

    def describe(self) -> dict:
        """人类可读的筛选描述。"""
        return {
            "ranking": self.ranking,
            "target_count": self.target_count,
            "status": self.status if self.status != "all" else "全部",
            "gender": self.gender if self.gender != "all" else "全部",
            "copyright": self.copyright if self.copyright != "all" else "全部",
            "category": self.category.get("category_ids") if self.category else "全部",
            "days": self.days if self.days != "all" else "全部",
            "word_count": self.word_count if self.word_count != "all" else "全部",
        }


# ── 应用筛选（click 6 类 filter radio）──────────────────────

def apply_filters(page, args: KolFilterArgs) -> None:
    """应用 KolFilterArgs 到当前页面（已经 open 了达人中心 list）。

    切 ranking + 6 类 filter，每类一次 click。
    """
    # 1) ranking：click task-menu-second 第 N 个
    ranking_idx = args._RANKING_TO_RADIO_VALUE[args.ranking] - 1  # 0-based
    page.locator(".task-menu-second .task-menu-second-item").nth(ranking_idx).click()
    page.wait_for_timeout(2000)

    # 2) 6 类 filter：每类 click 对应 radio input
    for field_name, value_map in [
        ("status", args._STATUS_TO_RADIO_VALUE),
        ("gender", args._GENDER_TO_RADIO_VALUE),
        ("copyright", args._COPYRIGHT_TO_RADIO_VALUE),
        ("days", args._DAYS_TO_RADIO_VALUE),
        ("word_count", args._WORD_COUNT_TO_RADIO_VALUE),
    ]:
        v = getattr(args, field_name)
        rv = value_map[v]
        if rv == "-1":
            continue  # 全部 = 不点（默认）
        row_idx = args._ROW_INDEX[field_name]
        try:
            page.locator(f".filter-row-uZ03S6").nth(row_idx).locator(
                f'input[type="radio"][value="{rv}"]'
            ).nth(0).check(force=True)
        except Exception as exc:
            logger.warning(
                f"[kol-filter] click {field_name}={rv} 失败: {exc}"
            )
        page.wait_for_timeout(500)

    # 3) category（如果有）
    if args.category is not None:
        mapping_id = args.category.get("mapping_id")
        row_idx = args._ROW_INDEX["category"]
        try:
            page.locator(f".filter-row-uZ03S6").nth(row_idx).locator(
                f'input[type="radio"][value*="{mapping_id}"]'
            ).nth(0).check(force=True)
        except Exception as exc:
            logger.warning(f"[kol-filter] click category={mapping_id} 失败: {exc}")
        page.wait_for_timeout(500)

    # 等所有 filter 生效
    page.wait_for_timeout(1500)


def _collect_book_titles(page) -> list[str]:
    """当前页所有书卡书名。"""
    js = r"""
    () => {
      const cards = Array.from(document.querySelectorAll('.book-hQ7GYr'));
      return cards.map(c => {
        const t = c.querySelector('.book-title-txt-_CIhYa');
        return t ? t.innerText.trim() : '';
      }).filter(Boolean);
    }
    """
    return page.locator("").evaluate(js) or []


def scroll_to_load_books(
    page,
    target_count: int,
    max_scroll: int = 30,
    stable_threshold: int = 3,
) -> list[str]:
    """滚到底 + 拉够 N 本 unique。

    每次滚 100vh + 等 1.5s + 数书。连续 stable_threshold 次无新书就停。
    """
    last_count = 0
    stable = 0
    for n in range(1, max_scroll + 1):
        # 滚到底
        page.locator("").evaluate(
            "() => window.scrollTo(0, document.body.scrollHeight)"
        )
        page.wait_for_timeout(1500)
        # 点"加载更多"按钮（如果有）
        page.locator("").evaluate("""
        () => {
          const btn = document.querySelector('.c-footer-load-more');
          if (btn && !btn.classList.contains('no-more')) {
            try { btn.click(); } catch (e) {}
          }
        }
        """)
        page.wait_for_timeout(800)
        titles = _collect_book_titles(page)
        curr_count = len(set(titles))
        logger.debug(
            f"[kol-filter] scroll #{n}: {curr_count} unique (target={target_count})"
        )
        if curr_count >= target_count:
            break
        if curr_count > last_count:
            last_count = curr_count
            stable = 0
        else:
            stable += 1
            if stable >= stable_threshold:
                logger.debug(
                    f"[kol-filter] no new books after {stable_threshold} scrolls, stop"
                )
                break
    # 切片到 target_count（break 时可能已经多拉了）
    all_titles = list(dict.fromkeys(_collect_book_titles(page)))
    return all_titles[:target_count]
