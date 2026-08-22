# -*- coding: utf-8 -*-
"""SQLite 数据库访问：索引库 + 查询结果缓存。"""
import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS sentences(
  id INTEGER PRIMARY KEY,
  year INTEGER NOT NULL,
  exam_type TEXT NOT NULL,
  text TEXT NOT NULL,
  source TEXT,
  article TEXT
);
CREATE TABLE IF NOT EXISTS words(
  id INTEGER PRIMARY KEY,
  lemma TEXT NOT NULL,
  form TEXT NOT NULL,
  sentence_id INTEGER NOT NULL,
  start INTEGER NOT NULL DEFAULT 0,
  end INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_words_lemma ON words(lemma);
CREATE INDEX IF NOT EXISTS idx_words_form ON words(form);
CREATE INDEX IF NOT EXISTS idx_words_sid ON words(sentence_id);
CREATE TABLE IF NOT EXISTS word_freq(
  lemma TEXT PRIMARY KEY,
  total INTEGER NOT NULL,
  doc_count INTEGER NOT NULL,
  first_year INTEGER,
  last_year INTEGER
);
CREATE TABLE IF NOT EXISTS query_cache(
  word TEXT PRIMARY KEY,
  result_json TEXT NOT NULL,
  corpus_version TEXT,
  prompt_version TEXT,
  model TEXT,
  usage TEXT,
  cost_yuan REAL,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS meta(
  key TEXT PRIMARY KEY,
  value TEXT
);
"""


def get_conn(db_path=None):
    db_path = db_path or config.DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    # 旧库迁移：query_cache 补 prompt_version 列
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(query_cache)")}
    if "prompt_version" not in cols:
        conn.execute("ALTER TABLE query_cache ADD COLUMN prompt_version TEXT")
        conn.commit()
    # 旧库迁移：words 表补 start/end 位置列（旧库补列后全为 0，重建索引后生效）
    wcols = {r["name"] for r in conn.execute("PRAGMA table_info(words)")}
    if "start" not in wcols:
        conn.execute("ALTER TABLE words ADD COLUMN start INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    if "end" not in wcols:
        conn.execute("ALTER TABLE words ADD COLUMN end INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    return conn


def get_meta(conn, key: str):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn, key: str, value: str):
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value))
    conn.commit()
