# -*- coding: utf-8 -*-
"""考研真题语境查单词 — 程序入口。

用法：
  python main.py                       启动桌面应用
  python -m app.corpus_builder         重建语料索引
  python -m app.prewarm --top 300      预热高频词
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from app import config
from app.single_instance import acquire
from app.ui.main_window import MainWindow


def apply_light_theme(app: QApplication):
    """强制浅色主题 + 全局字体加大一号（不跟随系统深色模式）。"""
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#ffffff"))
    pal.setColor(QPalette.WindowText, QColor("#1f2937"))
    pal.setColor(QPalette.Base, QColor("#ffffff"))
    pal.setColor(QPalette.AlternateBase, QColor("#f5f6f8"))
    pal.setColor(QPalette.Text, QColor("#1f2937"))
    pal.setColor(QPalette.Button, QColor("#f3f4f6"))
    pal.setColor(QPalette.ButtonText, QColor("#1f2937"))
    pal.setColor(QPalette.ToolTipBase, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipText, QColor("#1f2937"))
    pal.setColor(QPalette.Highlight, QColor("#3b82f6"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.PlaceholderText, QColor("#9ca3af"))
    app.setPalette(pal)
    app.setFont(QFont("Microsoft YaHei UI", 11))


def load_app_icon() -> QIcon:
    path = config.resource_path("assets/app_icon.ico")
    return QIcon(str(path)) if path.exists() else QIcon()


def ensure_index():
    """首次启动或语料更新后自动（重）建索引；提示词升级后自动清空旧缓存。"""
    from app.corpus_builder import corpus_version
    from app.db import get_conn, get_meta, set_meta
    from app.llm import PROMPT_VERSION

    need_build = False
    if not config.DB_PATH.exists():
        need_build = True
    else:
        try:
            conn = get_conn()
            stored = get_meta(conn, "corpus_version")
            if stored != corpus_version():
                need_build = True
            if get_meta(conn, "prompt_version") != PROMPT_VERSION:
                conn.execute("DELETE FROM query_cache")
                set_meta(conn, "prompt_version", PROMPT_VERSION)
                print("提示词已升级，旧查询缓存已清空（已查过的词下次会自动重新生成）。")
            conn.close()
        except FileNotFoundError:
            print(f"语料文件缺失：{config.CORPUS_JSONL}")
            print("请确认 exe 同目录下存在 corpus\\kaoyan_sentences.jsonl。")
            sys.exit(1)
        except Exception:
            need_build = True
    if need_build:
        print("正在建立真题索引（仅首次或语料更新后需要，请稍候）…")
        from app.corpus_builder import build
        build()
        try:
            from app.db import get_conn, set_meta
            from app.llm import PROMPT_VERSION
            conn = get_conn()
            set_meta(conn, "prompt_version", PROMPT_VERSION)
            conn.close()
        except Exception:
            pass


def main():
    ensure_index()
    app = QApplication(sys.argv)
    app.setApplicationName("考研真题语境查单词")
    apply_light_theme(app)
    app.setWindowIcon(load_app_icon())
    # 关窗缩托盘依赖 quitOnLastWindowClosed=False（仅系统支持托盘时启用）
    tray_ok = QSystemTrayIcon.isSystemTrayAvailable()
    app.setQuitOnLastWindowClosed(not tray_ok)
    win = MainWindow()
    single = acquire(win.show_and_raise)
    if single is None:
        return  # 已有实例在运行，已唤醒其窗口，本进程退出
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
