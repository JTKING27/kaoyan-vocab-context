# -*- coding: utf-8 -*-
"""设置对话框：API Key / 模型 / 接口地址 / 省钱上限 / 预热入口。"""
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
                               QLabel)

from .. import config
from .prewarm_dialog import PrewarmDialog


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(460)
        cfg = config.load_config()

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.api_key = QLineEdit(cfg["api_key"])
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("sk-...")
        form.addRow("API Key（DeepSeek）", self.api_key)

        self.base_url = QLineEdit(cfg["base_url"])
        form.addRow("接口地址", self.base_url)

        self.model = QLineEdit(cfg["model"])
        form.addRow("模型名", self.model)

        self.max_sentences = QSpinBox()
        self.max_sentences.setRange(5, 80)
        self.max_sentences.setValue(int(cfg["max_sentences"]))
        form.addRow("每个词最多送 AI 翻译句数", self.max_sentences)

        self.max_shown_extra = QSpinBox()
        self.max_shown_extra.setRange(0, 2000)
        self.max_shown_extra.setValue(int(cfg["max_shown_extra"]))
        form.addRow("额外展示句数上限", self.max_shown_extra)

        # AI 推理档位：义项归类/逐句翻译用 minimal 最快最省；
        # 近义义项区分不准时可调高（low/medium/high），成本略增
        self.reasoning_effort = QComboBox()
        self.reasoning_effort.addItems(["minimal", "low", "medium", "high"])
        idx = self.reasoning_effort.findText(
            str(cfg.get("reasoning_effort", "minimal")))
        self.reasoning_effort.setCurrentIndex(max(idx, 0))
        form.addRow("AI 推理档位", self.reasoning_effort)

        # 计费单价（元/百万 token，估算花费用；可在 DeepSeek 控制台用量页核对官方价）
        def price_box(v):
            b = QDoubleSpinBox()
            b.setRange(0.001, 100.0)
            b.setDecimals(4)
            b.setSingleStep(0.1)
            b.setValue(float(v))
            return b

        self.price_input = price_box(cfg.get("price_input", 1.0))
        form.addRow("输入单价（缓存未命中）", self.price_input)
        self.price_cached = price_box(cfg.get("price_input_cached", 0.02))
        form.addRow("输入单价（缓存命中）", self.price_cached)
        self.price_output = price_box(cfg.get("price_output", 2.0))
        form.addRow("输出单价", self.price_output)
        self.peak_mult = price_box(cfg.get("peak_mult", 2))
        self.peak_mult.setSingleStep(1)
        self.peak_mult.setDecimals(1)
        form.addRow("高峰时段价格倍数（×1=不区分）", self.peak_mult)
        tip2 = QLabel("单价单位为「元/百万 token」，可在 platform.deepseek.com "
                      "用量统计页核对官方价后填写，程序据此估算每次花费。")
        tip2.setWordWrap(True)
        tip2.setStyleSheet("color:#6b7280; font-size:12px;")
        layout.addWidget(tip2)

        layout.addLayout(form)
        tip = QLabel("Key 在 platform.deepseek.com 注册充值后获取。")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        row = QHBoxLayout()
        self.btn_prewarm = QPushButton("预热高频词…")
        self.btn_prewarm.clicked.connect(self._open_prewarm)
        row.addWidget(self.btn_prewarm)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _open_prewarm(self):
        PrewarmDialog(self).exec()

    def _save(self):
        cur = config.load_config()  # 保留未在界面展示的配置键（如 temperature）
        cfg = {
            "api_key": self.api_key.text().strip(),
            "base_url": self.base_url.text().strip() or config.DEFAULT_CONFIG["base_url"],
            "model": self.model.text().strip() or config.DEFAULT_CONFIG["model"],
            "max_sentences": self.max_sentences.value(),
            "max_shown_extra": self.max_shown_extra.value(),
            "price_input": self.price_input.value(),
            "price_input_cached": self.price_cached.value(),
            "price_output": self.price_output.value(),
            "peak_mult": self.peak_mult.value(),
            "temperature": cur.get("temperature", 0.2),
            "reasoning_effort": self.reasoning_effort.currentText(),
        }
        config.save_config(cfg)
        self.accept()
