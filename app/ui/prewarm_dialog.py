# -*- coding: utf-8 -*-
"""批量预热对话框（入口在设置里）：按真题词频或自定义词表批量预翻译并缓存。
预热前用官方 tokenizer 离线预估花费；可设预算上限，实际花费达到即自动停止。"""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar,
                               QPushButton, QVBoxLayout)

from .. import config
from ..db import get_conn
from ..prewarm import (estimate_words, get_freq_words, prewarm, read_word_file)


class PrewarmWorker(QThread):
    progress = Signal(int, int, str, str)
    estimate = Signal(dict)
    finished = Signal(dict)

    def __init__(self, words: list[str], budget: float = 0.0, parent=None):
        super().__init__(parent)
        self.words = words
        self.budget = budget
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        cfg = config.load_config()
        est = estimate_words(self.words, cfg)
        if est:
            self.estimate.emit(est)
        stats = prewarm(self.words, cfg,
                        progress_cb=lambda d, t, w, s: self.progress.emit(d, t, w, s),
                        cancel_cb=lambda: self._cancel,
                        budget=self.budget)
        self.finished.emit(stats)


class PrewarmDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("预热高频词")
        self.setMinimumSize(560, 420)
        self._worker = None
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("范围："))
        self.scope = QComboBox()
        self.scope.addItem("真题最高频 100 个实词", 100)
        self.scope.addItem("真题最高频 300 个实词", 300)
        self.scope.addItem("真题最高频 500 个实词", 500)
        self.scope.addItem("真题最高频 1000 个实词", 1000)
        top.addWidget(self.scope)
        self.btn_file = QPushButton("用词表文件…")
        self.btn_file.clicked.connect(self._pick_file)
        top.addWidget(self.btn_file)
        layout.addLayout(top)

        zone, mult = config.billing_zone(cfg=config.load_config())
        self.zone_label = QLabel(f"当前计费时段：{zone}（价格 ×{mult:g}）")
        self.zone_label.setWordWrap(True)
        layout.addWidget(self.zone_label)

        budget_row = QHBoxLayout()
        budget_row.addWidget(QLabel("预算上限（元，0=不限制）："))
        self.budget = QDoubleSpinBox()
        self.budget.setRange(0, 1000)
        self.budget.setDecimals(2)
        self.budget.setSingleStep(0.5)
        self.budget.setValue(0.0)
        budget_row.addWidget(self.budget)
        budget_row.addStretch(1)
        layout.addLayout(budget_row)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

        btns = QHBoxLayout()
        self.btn_start = QPushButton("开始")
        self.btn_start.clicked.connect(self._start)
        btns.addWidget(self.btn_start)
        self.btn_cancel = QPushButton("中止")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel)
        btns.addWidget(self.btn_cancel)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        btns.addWidget(close)
        layout.addLayout(btns)

        self._file_words = []

    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择词表文件", "", "文本文件 (*.txt);;所有文件 (*)")
        if path:
            self._file_words = read_word_file(path)
            self.log.appendPlainText(f"已从文件读取 {len(self._file_words)} 个词。")

    def _start(self):
        if self._worker and self._worker.isRunning():
            return
        if self._file_words:
            words = self._file_words
        else:
            conn = get_conn()
            words = get_freq_words(conn, self.scope.currentData())
            conn.close()
        self._worker = PrewarmWorker(words, budget=self.budget.value())
        self._worker.progress.connect(self._on_progress)
        self._worker.estimate.connect(self._on_estimate)
        self._worker.finished.connect(self._on_finished)
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_file.setEnabled(False)
        self.progress.setMaximum(len(words))
        self.log.appendPlainText(f"开始预热 {len(words)} 个词…（已缓存的会自动跳过）")
        self._worker.start()

    def _cancel(self):
        if self._worker:
            self._worker.cancel()
            self.log.appendPlainText("正在中止…（当前词完成后停止）")

    def _on_progress(self, done, total, word, status):
        self.progress.setValue(done)
        self.log.appendPlainText(f"[{done}/{total}] {word}: {status}")
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _on_estimate(self, est: dict):
        self.log.appendPlainText(
            f"预计：每词输入约 {est['per_word_input_tokens']} token，"
            f"每词约 {est['per_word_est']:.4f} 元，"
            f"{est['words']} 词合计约 {est['est_total']:.2f} 元（{est['zone']}）"
            + ("，达到预算自动停止" if self.budget.value() > 0 else ""))

    def _on_finished(self, stats: dict):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_file.setEnabled(True)
        self.log.appendPlainText(
            f"\n完成：处理 {stats['done']} 个，新增缓存 {stats['api_calls']} 个，"
            f"跳过已有缓存 {stats['cached_skip']} 个，失败 {stats['failed']} 个，"
            f"实际花费约 {stats['cost_yuan']:.2f} 元，耗时 {stats['seconds']} 秒。")
        if stats.get("budget_hit"):
            self.log.appendPlainText("（达到预算上限，提前停止，剩余词可下次继续）")
        if stats.get("aborted"):
            self.log.appendPlainText("（已中止，剩余词未处理，可下次继续）")
