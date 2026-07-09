# 03 音频生成与评估

## 目标

把音频导演稿跑成可听成品，并在同一个任务里完成短测、全篇生成、request 核对、人工复听和小修决策。ASR 对齐、情绪/自然度自动预检是当前增强项；没有实际跑时必须在结果里说明，不能假装已经完成。

生成和评估不拆开：因为当前还在手工跑通阶段，真正的问题往往出现在“生成参数 -> 听感 -> 小修 -> 重生成”的闭环里。拆成两个任务会让问题记录和修复动作断开。

## 输入

- `稿子/日期_话题_minimax导演稿_v1.md`
- `tts/出音频.py`
- `tts/.env`
- 本目录的 `MiniMax_播客音频生成研究与指导书_v0.2.md`
- 本目录的 `音频自然度与情绪评估工具调研_v0.1.md`（正式评估指导书）

## 步骤

1. 确认 `MINIMAX_API_KEY`、爸爸/孩子 `voice_id`、`MINIMAX_MODEL` 和 endpoint。
2. 生成前检查导演稿的发音风险清单；把必须指定读音的多音字、专名、外文名、数字读法放进 `tts/出音频.py` 的 MiniMax `pronunciation_dict.tone` 或临时环境变量 `MINIMAX_PRONUNCIATION_TONE`。
3. 先生成 6-8 个高风险 turn 的短测，检查声音区分、停顿、错读、控制词是否外露。
4. 短测过线后生成全篇音频。
5. 保留 `.minimax-request.txt` 和 `.minimax-request.json`，追溯实际发给 TTS 的文本、参数和 `pronunciation_dict`。
6. 必做 request 核对：检查 `.minimax-request.txt` 和 `.minimax-request.json`，确认实际送入 TTS 的文本、`voice_modify`、控制词、`pronunciation_dict` 与预期一致；多音字/专名不能只写在文档里。
7. 必做基础文件核对：确认 mp3 存在、大小合理、时长落在目标范围，line parts 已生成。
8. 增强项：用 ASR 对齐原稿，抓错读、漏读、专名问题；按 `音频自然度与情绪评估工具调研_v0.1.md` 做情绪/语气识别、自然度 MOS 或可用替代指标，输出高风险 turn 排序。
9. 根据 request 核对、人工复听和可用的自动预检结果生成小修建议：错读/漏读、专名多音字、拼接突兀、情绪不一致、自然度低分别标原因；建议只能指向音频导演层、发音词典、停顿、标签或局部重生成。
10. 成人抽听高风险 turn、开头、结尾和少量随机 turn；自动分数只负责路由复听，不单独决定通过。
11. 小修最多 2-3 轮，仍不过线就退回 `02_音频导演稿/`。

## 命令

```powershell
$env:HEYTODAY_TTS_BACKEND="minimax"
D:/project-script/VoxCPM/.venv/Scripts/python.exe tts/出音频.py 稿子/日期_话题_minimax导演稿_v1.md
```

## 产物

- `音频/日期_话题_minimax导演稿_v1.minimax.mp3`
- `音频/日期_话题_minimax导演稿_v1.minimax.minimax-request.txt`
- `音频/日期_话题_minimax导演稿_v1.minimax.minimax-request.json`
- `音频/日期_话题_minimax导演稿_v1.minimax.line_parts/`
- `音频/xxx.emotion_raw.jsonl`
- `音频/xxx.review_round1.csv`
- `音频/xxx.fix_plan_round1.json`
- `音频/xxx.eval_summary.md`（可选；汇总 request 核对、自动预检、成人复听和小修结论）
- 必要时生成 `稿子/日期_话题_minimax导演稿_v2.md`

## 通过标准

- 爸爸/孩子声音能稳定区分。
- 拼接停顿不突兀。
- 控制词没有被读出来。
- 专名、数字、中英混读、多音字没有明显错读；request JSON 中必须能看到本期必要的 `pronunciation_dict.tone`。
- 情绪峰值和导演意图大体一致。
- request 文本/JSON 已核对；若 ASR/自动预检未跑，结果里已明确说明。
- 成人复听已覆盖高风险 turn、开头、结尾和随机 turn。
- 成人复听认为“像聊天”，不是新闻播报或朗读作文。
- 孩子反馈进入 `孩子反应日志.md`。

## 沉淀位置

- 稳定参数写回 `tts/README.md` 或 `tts/出音频.py`。
- 供应商能力判断保留在本目录指导书。
- 可自动化的检查写回未来评估脚本。
- 自动评估指标和人工复听表的稳定经验，回写 `音频自然度与情绪评估工具调研_v0.1.md` 或后续升版。
