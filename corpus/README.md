# 语料说明

`kaoyan_sentences.jsonl` 是本应用唯一语料源（由 `scripts/extract_corpus.py` 从以下公开来源提取，
仅供个人学习使用，请勿用于商业用途）。

| 来源 | 覆盖 | 内容 | 获取方式 |
|---|---|---|---|
| words-statistics（GitHub: YSMull/words-statistics） | 1980–2012 考研英语统考 | 全题型英文文本（GBK txt） | git clone |
| language-learner-texts（GitHub: guopenghui/language-learner-texts） | 1998–2022 英语一 | 阅读 Text1-5 + 翻译题正文（md） | git clone |
| 考生回忆版真题（整理自公开的考研英语回忆版真题仓库） | 英语一 2010–2026、英语二 2010–2025 | 完型 + 阅读 + 新题型（md） | 从公开仓库收集后放入 `corpus/_raw/user_md/` |
| pfoocc 201_204_kaoyan（GitHub: pfoocc/201_204_kaoyan） | 英语一 2005–2023、英语二 2010–2023 | 完型 + 阅读正文（LaTeX） | git clone |

## 词典数据来源

- `_raw/open_dictionary_v2/distribution.jsonl`：**open-dictionary v2.0**（GitHub: ahpxex/open-dictionary，release 下载，366MB 解压后，不入 git）。数据工件以 **CC BY-SA 4.0** 发布，系 English Wiktionary（维基词典贡献者，CC BY-SA 4.0 / GFDL）经 Wiktextract 提取后的衍生作品，本项目做词频筛选与结构重组。由 `scripts/build_odict.py` 裁剪生成 `assets/dict.csv`（义项约束 AI）与 `assets/word_cards.json`（词条卡片）。再分发须保留署名并以相同许可共享。
- `_raw/ecdict.csv`：ECDICT（GitHub: skywind3000/ECDICT）完整词典，兜底义项。
- `_raw/kaoyan_hongbaoshu_2025.json`：考研红宝书 2025 词库（仅用于词表范围参考，不作为 AI 义项约束来源）。

## 更新语料的方法

1. 把新来源放入 `corpus/_raw/` 或在 `scripts/extract_corpus.py` 中新增提取函数；
2. 运行 `python scripts/extract_corpus.py` 重新生成 `kaoyan_sentences.jsonl`；
3. 运行 `python -m app.corpus_builder` 重建索引；
4. 语料版本自动变化，旧查询缓存自动失效。

## 已知缺口

- 英语一/二 2010 后的翻译题、写作题文本（现有来源不含）；
- 1980–1997 年的题目指令句混入少量噪声行（占比较小，不影响查词匹配）。
