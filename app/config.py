# -*- coding: utf-8 -*-
"""全局配置：路径、默认值、配置文件读写、DeepSeek 峰谷计价时段判断。"""
import json
import sys
from datetime import datetime
from pathlib import Path

if getattr(sys, "frozen", False):
    # 打包成 exe 后：语料与数据都放在 exe 同目录，便于用户直接替换更新
    ROOT = Path(sys.executable).parent
else:
    ROOT = Path(__file__).resolve().parent.parent


def resource_path(name: str) -> Path:
    """资源文件路径：开发时在项目根，打包后从 PyInstaller 解包目录取。"""
    if getattr(sys, "frozen", False):
        import os
        return Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))) / name
    return ROOT / name
DATA_DIR = ROOT / "data"
CORPUS_JSONL = ROOT / "corpus" / "kaoyan_sentences.jsonl"
DB_PATH = DATA_DIR / "kaoyan.db"
CONFIG_PATH = DATA_DIR / "config.json"

DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-v4-flash",
    "max_sentences": 36,      # 每个词最多送 AI 逐句翻译的句数（省钱/提速上限）
    "max_shown_extra": 200,   # 超出部分最多额外展示的句子数
    # 计费单价（元/百万 token）与高峰倍数：DeepSeek 官方价（deepseek-v4-flash），
    # 空闲时段 输入缓存命中 0.05 / 缓存未命中 1.5 / 输出 4.5；高峰 = 空闲 ×2。
    # 高峰时段为北京时间 9:00-12:00、14:00-18:00。价格变动可在此修改。
    "price_input": 1.5,          # 输入（缓存未命中，空闲价）
    "price_input_cached": 0.05,  # 输入（缓存命中，空闲价）
    "price_output": 4.5,         # 输出（空闲价）
    "peak_mult": 2,              # 高峰时段价格倍数（空闲 ×2 = 高峰价）
    # LLM 采样参数（可在设置里调档；义项归类/翻译任务用低随机性）
    "temperature": 0.2,          # 采样温度
    "reasoning_effort": "minimal",  # 推理档位：minimal / low / medium / high
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for k in DEFAULT_CONFIG:
                if k in data:
                    cfg[k] = data[k]
        except Exception:
            pass
    return cfg


def save_config(cfg: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def billing_zone(now: datetime | None = None, cfg: dict | None = None) -> tuple[str, float]:
    """返回 (时段名, 价格倍数)。DeepSeek 官方：高峰时段为北京时间
    9:00-12:00、14:00-18:00，价格 = 空闲 × peak_mult（默认 2）；其余空闲 ×1。
    若设置里把 peak_mult 设为 1（或 1 以下），则不再区分峰谷。"""
    peak = float((cfg or load_config()).get("peak_mult", 2) or 1)
    now = now or datetime.now()
    if peak > 1.001 and ((9 <= now.hour < 12) or (14 <= now.hour < 18)):
        return f"高峰（价格 ×{peak:g}）", peak
    return "空闲", 1.0


def estimate_cost(prompt_tokens: int, completion_tokens: int,
                  cache_hit_tokens: int = 0, mult: float = 1.0,
                  cfg: dict | None = None) -> float:
    """按配置单价估算一次调用的花费（元）。token 用量来自 API 返回（准确），
    单价/高峰倍数来自设置（可按 DeepSeek 官方价核对填写）。"""
    cfg = cfg or load_config()
    p_in = float(cfg.get("price_input", 1.0))
    p_cached = float(cfg.get("price_input_cached", 0.02))
    p_out = float(cfg.get("price_output", 2.0))
    non_cached = max(prompt_tokens - cache_hit_tokens, 0)
    cost = (non_cached * p_in + cache_hit_tokens * p_cached
            + completion_tokens * p_out) / 1_000_000
    return cost * mult
