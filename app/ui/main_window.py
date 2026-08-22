# -*- coding: utf-8 -*-
"""主窗口：查词 + 结果展示 + 设置入口。"""
import time

from PySide6.QtCore import QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QCompleter, QDialog, QHBoxLayout,
                               QLineEdit, QMainWindow, QMenu, QPushButton,
                               QSystemTrayIcon, QTextBrowser, QVBoxLayout,
                               QWidget)

from .. import config
from .. import dict as dict_mod
from ..query import normalize_word, query_word
from .history_dialog import HistoryDialog, load_cached_result
from .render import render_result_html
from .settings_dialog import SettingsDialog


class QueryWorker(QThread):
    preview = Signal(int, dict)  # (seq, 本地预览：词条卡片+真题句子原文，秒回)
    done = Signal(int, dict)     # (seq, 最终结果：含 AI 归类翻译)

    def __init__(self, seq: int, word: str, parent=None):
        super().__init__(parent)
        self.seq = seq
        self.word = word
        self.cancelled = False  # 主线程发起新查询后置 True：本查询结果将被丢弃

    def run(self):
        # 阶段 1：本地预览（不调 AI，秒回）。缓存命中/出错/查无此词直接出最终结果。
        try:
            r0 = query_word(self.word, stage="preview")
        except Exception as e:  # 兜底：任何异常都给用户可见提示
            r0 = {"word": self.word, "error": f"查询出错：{e}"}
        if self.cancelled:
            return  # 已被更新的查询取代，结果直接丢弃
        if r0.get("error") or r0.get("cached") or r0.get("preview") is not True:
            self.done.emit(self.seq, r0)
            return
        self.preview.emit(self.seq, r0)
        # 阶段 2：AI 归类翻译（新词耗时在此）
        if self.cancelled:
            return  # AI 还没开始就被取代：跳过调用，省这一次费用
        try:
            r = query_word(self.word, stage="full")
        except Exception as e:
            r = {"word": self.word, "error": f"查询出错：{e}"}
        self.done.emit(self.seq, r)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("考研真题语境查单词")
        self.resize(860, 720)
        self._query_workers = []  # 查询 worker 引用列表（防 QThread 被 GC 崩溃）
        self._query_seq = 0       # 查询序号：界面只接受最新一次查询的结果
        self._result = None          # 最近一次查询结果，供展开/收起时重渲染
        self._expanded = set()       # 已展开的折叠组号（#sents-N / #fold-*）
        self._t0 = None              # 查词开始时刻，用于计时
        self._really_quit = False    # 托盘「退出」置 True：关窗不再拦截
        self._tray_tip_shown = False  # 首次缩托盘的提示只弹一次
        self._tray = None
        icon = QIcon(str(config.resource_path("assets/app_icon.ico")))
        if not icon.isNull():
            self.setWindowIcon(icon)
        # 系统托盘：点 ✕ 最小化到托盘后台常驻，托盘菜单「退出」才真正退出
        if QSystemTrayIcon.isSystemTrayAvailable():
            tray = QSystemTrayIcon(icon, self)
            tray.setToolTip("考研真题语境查单词")
            menu = QMenu()
            menu.addAction("打开主界面", self.show_and_raise)
            menu.addSeparator()
            menu.addAction("退出", self._quit_app)
            tray.setContextMenu(menu)
            tray.activated.connect(self._on_tray_activated)
            tray.show()
            self._tray = tray

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # ---- 顶部输入行 ----
        top = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入单词，回车查询")
        self.input.returnPressed.connect(self._search)
        # 输入自动补全：输入部分字母，下方弹出词典候选词（大小写不敏感、前缀匹配）
        completer = QCompleter(dict_mod.all_words(), self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchStartsWith)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.input.setCompleter(completer)
        top.addWidget(self.input, 1)
        self.btn_search = QPushButton("查词")
        self.btn_search.clicked.connect(self._search)
        top.addWidget(self.btn_search)
        self.btn_history = QPushButton("历史")
        self.btn_history.clicked.connect(self._open_history)
        top.addWidget(self.btn_history)
        self.btn_settings = QPushButton("设置")
        self.btn_settings.clicked.connect(self._open_settings)
        top.addWidget(self.btn_settings)
        layout.addLayout(top)

        # ---- 结果区 ----
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.anchorClicked.connect(self._on_anchor_clicked)
        layout.addWidget(self.browser, 1)

        self.statusBar().showMessage("就绪")

    def _search(self):
        word = normalize_word(self.input.text())
        if not word:
            self.browser.setHtml(
                "<p style='color:#b91c1c'>请输入单个英文单词（可含连字符，如 well-being）。</p>")
            return
        # 上一个查询还在跑（如 AI 分析中）时允许直接查下一个：
        # 旧查询结果按序号丢弃、不覆盖新词；旧 worker 若还没开始调 AI 则跳过省一次费用。
        self._query_seq += 1
        seq = self._query_seq
        for w in self._query_workers:
            w.cancelled = True
        self._t0 = time.perf_counter()
        self.statusBar().showMessage(f"正在查 {word} …")
        self.browser.setHtml("<p>查询中…</p>")
        worker = QueryWorker(seq, word)
        worker.preview.connect(self._on_preview)
        worker.done.connect(self._on_result)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        self._query_workers.append(worker)
        worker.start()

    def _cleanup_worker(self, worker: QueryWorker):
        if worker in self._query_workers:
            self._query_workers.remove(worker)

    def _on_preview(self, seq: int, r: dict):
        """本地预览先显示（词条卡片 + 真题句子原文），AI 分析完成后 _on_result 覆盖。"""
        if seq != self._query_seq:
            return  # 已被更新的查询取代，旧预览丢弃
        self._result = r
        self._expanded.clear()
        self.browser.setHtml(render_result_html(r))
        self.statusBar().showMessage(
            f"本地词典已显示 · 正在分析 {r.get('total_found', 0)} 句真题（AI）…")

    def _on_result(self, seq: int, r: dict):
        if seq != self._query_seq:
            return  # 已被更新的查询取代，旧结果丢弃
        self._result = r
        self._expanded.clear()  # 新查询重置所有折叠组
        self.browser.setHtml(render_result_html(r))
        dt = time.perf_counter() - (self._t0 or time.perf_counter())
        if r.get("error"):
            self.statusBar().showMessage(
                f"查询未完成：{r['error'][:60]} · 耗时 {dt:.1f}s")
        elif r.get("cached"):
            self.statusBar().showMessage(
                f"命中缓存 · 零花费 · 共 {r.get('total_found', 0)} 句"
                f" · 耗时 {dt:.1f}s")
        else:
            self.statusBar().showMessage(
                f"查询完成 · 共 {r.get('total_found', 0)} 句 · 分析 "
                f"{r.get('analyzed_count', 0)} 句 · 花费约 {r.get('cost_yuan', 0):.4f} 元"
                f" · 已缓存 · 耗时 {dt:.1f}s")

    def _on_anchor_clicked(self, url: QUrl):
        """处理结果页里的链接点击：#sents-N（点义项展开/收起真题句）、
        #fold-*（文章内句折叠）为展开/收起，其余忽略
        （http 链接由 setOpenExternalLinks 走外部浏览器）。"""
        frag = url.fragment()
        valid = (frag.startswith("fold-") or frag.startswith("sents-"))
        if not valid or self._result is None:
            return
        if frag in self._expanded:
            self._expanded.discard(frag)
        else:
            self._expanded.add(frag)
        # 重新渲染并尽量保持滚动位置
        sb = self.browser.verticalScrollBar()
        pos = sb.value()
        self.browser.setHtml(
            render_result_html(self._result, expanded=frozenset(self._expanded)))
        QTimer.singleShot(0, lambda: sb.setValue(min(pos, sb.maximum())))

    def _open_history(self):
        """历史查词列表：双击回看缓存结果（离线零费用，不调 AI）。
        回看不影响正在进行的查询（不触碰查询 worker / 序号）。"""
        dlg = HistoryDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        word = dlg.pick_word()
        if not word:
            return
        r = load_cached_result(word)
        if r is None:
            self.statusBar().showMessage(
                f"历史记录 {word} 的缓存不可用，请重新查询")
            return
        self._result = r
        self._expanded.clear()
        self.browser.setHtml(render_result_html(r))
        self.statusBar().showMessage(
            f"历史记录 · 缓存回看 · {word} · 共 {r.get('total_found', 0)} 句")

    def show_and_raise(self):
        """从托盘或第二实例唤醒：显示并置顶主窗口。"""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        """左键单击托盘图标 → 打开主界面（双击会先触发一次单击）。"""
        if reason == QSystemTrayIcon.Trigger:
            self.show_and_raise()

    def closeEvent(self, event):
        """点 ✕：最小化到托盘继续后台跑（首次弹气泡提示）；
        托盘「退出」置了 _really_quit，或系统不支持托盘时，才真正关闭退出。"""
        if self._really_quit or self._tray is None:
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self._tray_tip_shown:
            self._tray_tip_shown = True
            self._tray.showMessage(
                "考研真题语境查单词",
                "已最小化到系统托盘，双击图标可重新打开。",
                QSystemTrayIcon.Information, 3000)

    def _quit_app(self):
        """托盘「退出」：先取消/等待查询线程，再真正退出程序。"""
        self._really_quit = True
        self.shutdown_workers()
        QApplication.instance().quit()

    def shutdown_workers(self):
        """退出前清理查询线程：标记取消并等待结束（每个最多 2 秒）。
        已发出的 AI 请求无法中断，费用照常、结果丢弃（与并发查词行为一致）。"""
        for w in self._query_workers:
            w.cancelled = True
        for w in list(self._query_workers):
            if w.isRunning():
                w.wait(2000)

    def _open_settings(self):
        SettingsDialog(self).exec()
