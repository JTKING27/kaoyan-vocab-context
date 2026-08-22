# -*- coding: utf-8 -*-
"""单实例：QLockFile 保证互斥（可靠）+ QLocalServer 做唤醒通道。

- 互斥：第一实例在 data/app.lock 上加独占文件锁；第二实例加锁失败 =
  已有实例在运行，直接唤醒它并退出。进程崩溃后 QLockFile 能识别
  残留锁（PID 已死则自动接管），不会出现"锁死后程序再也起不来"。
- 唤醒：第一实例监听固定名称的 QLocalServer；第二实例作为客户端连一下，
  第一实例收到连接就把主窗口提到前台。命名管道随进程退出自动消失。

注：不用 listen 失败判定已有实例——Qt 6.11 / Windows 下同名管道
允许多个服务端共存，listen 不会互斥。
"""
from PySide6.QtCore import QLockFile
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from . import config

INSTANCE_NAME = "ChazhentiWords_Instance"
LOCK_PATH = config.DATA_DIR / "app.lock"


def acquire(on_wake):
    """尝试成为唯一实例。

    成功：返回 (lock, server)（调用方需保持引用直到程序退出；
         server 为唤醒通道，可能为 None 表示通道未建立）。第二实例连接时
         回调 on_wake()（把主窗口提到前台）。
    失败（已有实例）：向已有实例发连接唤醒它，返回 None，调用方应直接退出。
    """
    lock = QLockFile(str(LOCK_PATH))
    lock.setStaleLockTime(0)  # 立即检测崩溃残留：进程已死则自动接管
    if not lock.tryLock(0):
        # 已有实例：连唤醒通道通知它把窗口提到前台，然后本实例退出
        sock = QLocalSocket()
        sock.connectToServer(INSTANCE_NAME)
        sock.waitForConnected(500)
        sock.close()
        return None

    server = QLocalServer()
    if server.listen(INSTANCE_NAME):
        def _wake():
            conn = server.nextPendingConnection()
            if conn is not None:
                conn.close()
                conn.deleteLater()
            on_wake()
        server.newConnection.connect(_wake)
        return lock, server
    # 唤醒通道没建立（极罕见）：单实例依然成立（锁在），只是无法被唤醒
    return lock, None
