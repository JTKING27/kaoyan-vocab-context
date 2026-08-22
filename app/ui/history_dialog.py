# -*- coding: utf-8 -*-
"""历史查词列表对话框：列出查过的词（按时间倒序），双击回看缓存结果。

纯离线回看：直接读 query_cache 的 result_json 原样展示，不调 AI、零费用；
缓存不可用时提示重新查询，不影响正常查词。
"""
import json
import sqlite3

from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget,
                               QPushButton, QVBoxLayout)

from ..db import get_conn


def list_history() -> list[tuple[str, str]]:
    """查过的词（原形键）与查词时间，按时间从近到远。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT word, created_at FROM query_cache "
            "ORDER BY created_at DESC").fetchall()
    finally:
        conn.close()
    return [(r["word"], r["created_at"] or "") for r in rows]


def load_cached_result(word: str) -> dict | None:
    """读某词查询缓存的完整结果（历史回看用，离线零费用）。
    缓存缺失/损坏/解析失败返回 None。"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT result_json FROM query_cache WHERE word=?",
            (word,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row:
        return None
    try:
        data = json.loads(row["result_json"])
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _fmt(ts: str) -> str:
    """'2026-08-22T09:09:56' -> '2026-08-22 09:09'。"""
    return ts.replace("T", " ")[:16] if ts else ""


class HistoryDialog(QDialog):
    """历史查词列表。exec() 返回 Accepted 后可用 pick_word() 取选中的词。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("历史查词")
        self.setMinimumSize(420, 440)
        self._items: list[tuple[str, str]] = []
        self._pick: str | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "查过的词（按时间从近到远），双击或选中后点「查看」回看："))
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _it: self._view())
        layout.addWidget(self.list, 1)

        row = QHBoxLayout()
        self.btn_view = QPushButton("查看")
        self.btn_view.clicked.connect(self._view)
        row.addWidget(self.btn_view)
        row.addStretch(1)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.reject)
        row.addWidget(self.btn_close)
        layout.addLayout(row)

        self._load()

    def _load(self):
        self._items = list_history()
        if not self._items:
            self.list.addItem("（还没有查过词，先查一个吧）")
            self.list.setEnabled(False)
            self.btn_view.setEnabled(False)
            return
        for word, ts in self._items:
            self.list.addItem(f"{word}    {_fmt(ts)}")

    def _view(self):
        idx = self.list.currentRow()
        if idx < 0 or idx >= len(self._items):
            return
        self._pick = self._items[idx][0]
        self.accept()

    def pick_word(self) -> str | None:
        return self._pick
