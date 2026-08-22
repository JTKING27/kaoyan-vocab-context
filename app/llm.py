# -*- coding: utf-8 -*-
"""DeepSeek（OpenAI 兼容）调用：固定系统前缀（利于 DeepSeek 上下文缓存命中省钱），
网络错误/限流/解析失败重试 2 次，返回 token 用量供计费估算。"""
import logging
import time

import requests

from . import config

logger = logging.getLogger(__name__)

# 提示词版本：修改提示词后必须递增，旧缓存自动作废（meta 里比对）。
# v7-mid：输出 schema 重构——meanings 只留 {id, meaning}，句子用 meaning_id
# 回指义项，count/分组由代码端从 sentences[].meaning_id 聚合。
PROMPT_VERSION = "v7-mid"

# 系统提示保持稳定不变：批量预热时 DeepSeek 会自动命中前缀缓存，大幅省输入费用。
SYSTEM_PROMPT = (
    "你是考研英语真题词汇分析助手。任务：判断目标单词在每个真题句子中的含义"
    "属于给定词典义项列表中的哪一个，并给出每个句子的中文翻译。\n"
    "输出严格的 JSON（不要任何其他文字），格式：\n"
    '{"affix": "ex- 向外 + cept 拿取 + -ion 名词后缀", '
    '"meanings": [{"id": 1, "meaning": "n. 例外；除外"}], '
    '"sentences": [{"id": 1, "meaning_id": 1, '
    '"translation": "这条规则几乎没有【例外】。"}]}\n'
    "规则（必须严格遵守）：\n"
    "1. meanings 是本题实际用到的词典义项，meaning 字段必须逐字照抄"
    "「词典义项列表」原文，不得自创、改写或添加，按列表原顺序从 1 重新编号；"
    "若输入注明「该词未收录在词典中」，则按该词在真题语境中的常见释义自拟，"
    "格式「词性缩写. 中文释义」，不得编造冷僻含义；\n"
    "2. sentences 必须覆盖输入的每一个句子编号，每个编号出现且仅出现一次；"
    "meaning_id 必须指向 meanings 中某个 id，每个句子归入唯一一个最贴近的义项；"
    "认真读句，不要把所有句子都塞进一个义项；\n"
    "3. 若该词在句中发生转类（实际词性与词典标注不符），仍选语义最近的义项，"
    "并在 note 中说明实际用法（如「此处作动词」）；\n"
    "4. phrase 是该词在本句中起作用的搭配词组（如 search agent、"
    "address a problem），逐字照抄句子原文、保持大小写；"
    "该词单独表义、不构成搭配时省略 phrase 字段；\n"
    "5. note 仅当词典义项不足以直接表达句中含义（固定搭配、特定语境、转类）"
    "时给出简短中文说明，否则省略；\n"
    "6. translation 是该句自然通顺的中文翻译，其中该词（或搭配）对应的中文部分"
    "必须用【】括起来，只括该词部分，每句至少一处【】；\n"
    "7. affix 是该词的词根词缀拆解，格式「词素 中文含义 + 词素 中文含义…」"
    "（如 ex- 向外 + cept 拿取 + -ion 名词后缀），只列出有把握的词素；"
    "无法可靠拆解时必须省略 affix 字段（不要编造）；若输入中注明"
    "「已有本地拆解，无需输出 affix」，则一律省略 affix 字段；\n"
    "8. 输出前自检：每个输入编号出现且仅一次；每个 meaning_id 有效；"
    "每个 meaning 与词典列表逐字一致；\n"
    "9. 只输出 JSON 本体，不要任何解释性文字。"
)


class LLMError(Exception):
    """网络/服务错误（可重试）。"""


class LLMBadRequest(Exception):
    """请求被拒绝（4xx，不重试）。"""


def call_llm(system: str, user: str, cfg: dict, timeout: int = 120,
             session: requests.Session | None = None):
    """调用大模型，返回 (content, usage_dict)。usage 含 prompt_tokens /
    completion_tokens / prompt_cache_hit_tokens（DeepSeek 返回）。
    session 传入可复用连接：批量预热/并发批次共享同一 Session，
    省掉每次 TCP 握手（连接超时 10 秒，读取超时仍用 timeout）。"""
    if not cfg.get("api_key"):
        raise LLMBadRequest("未配置 API Key，请在设置中填写。")
    url = cfg.get("base_url", config.DEFAULT_CONFIG["base_url"]).rstrip("/") \
        + "/chat/completions"
    payload = {
        "model": cfg.get("model", config.DEFAULT_CONFIG["model"]),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": float(cfg.get("temperature", 0.2)),
        "response_format": {"type": "json_object"},
        # DeepSeek v4 是推理模型，默认会大量"思考"导致查词很慢；
        # minimal 档对义项归类/翻译任务足够，被忽略时也无害。
        # 近义义项区分不准时可在设置里调高（low/medium/high），成本略增。
        "reasoning_effort": cfg.get("reasoning_effort", "minimal"),
    }
    headers = {
        "Authorization": "Bearer " + cfg["api_key"],
        "Content-Type": "application/json",
    }
    http = session or requests
    last_err = None
    for attempt in range(3):  # 共 1 + 2 次重试：网络错误 / 429 / 408 / 解析失败
        wait = 1.5 * (attempt + 1)
        try:
            resp = http.post(url, json=payload, headers=headers,
                             timeout=(10, timeout))
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"].get("content")
                if not (content or "").strip():
                    # 200 但内容为空：视为可重试错误
                    last_err = LLMError("响应 content 为空")
                else:
                    return content, data.get("usage") or {}
            elif resp.status_code in (408, 429):
                # 限流：优先按响应头 Retry-After 等待；Retry-After 可能是
                # HTTP 日期格式（少见），float 失败时退回退避时间
                ra = resp.headers.get("Retry-After", "")
                try:
                    wait = max(float(ra or 0), wait)
                except ValueError:
                    pass
                last_err = LLMError(
                    f"API 返回 {resp.status_code}：{resp.text[:200]}")
            elif 400 <= resp.status_code < 500:
                raise LLMBadRequest(
                    f"API 返回 {resp.status_code}：{resp.text[:300]}")
            else:
                last_err = LLMError(
                    f"API 返回 {resp.status_code}：{resp.text[:200]}")
        except (KeyError, IndexError, ValueError) as e:
            # 注意顺序：requests 的 JSONDecodeError 同时继承 RequestException
            # 和 ValueError，放前面才能归类为「响应解析失败」而非网络错误
            last_err = LLMError(f"响应解析失败：{e}")
        except requests.RequestException as e:
            last_err = LLMError(f"网络错误：{e}")
        if attempt < 2:  # 最后一轮失败不再空等，直接退出重试
            logger.warning("调用 LLM 第 %d 次失败（%s），%.1f 秒后重试",
                           attempt + 1, last_err, wait)
            time.sleep(wait)
    logger.error("调用 LLM 重试 2 次后仍失败：%s", last_err)
    raise last_err


def build_user_prompt(word: str, sentences: list[str],
                      dict_defs: list[str] | None = None,
                      affix_required: bool = True,
                      etymology: str = "") -> str:
    lines = [f"目标单词：{word}"]
    if etymology:
        lines.append(f"词源注记（拆词根词缀时可参考，不得编造）：{etymology}")
    if dict_defs:
        lines.append("词典义项列表（义项必须从此列表中选择，逐字照抄）：")
        lines += [f"{i + 1}. {d}" for i, d in enumerate(dict_defs)]
    else:
        lines.append("（该词未收录在词典中）词典义项列表：无。"
                     "义项请按该词在真题语境中的常见释义给出，"
                     "格式「词性缩写. 中文释义」，不得编造冷僻含义。")
    if not affix_required:
        lines.append("已有本地拆解，无需输出 affix 字段。")
    lines.append("真题句子：")
    lines += [f"{i + 1}. {t}" for i, t in enumerate(sentences)]
    return "\n".join(lines)
