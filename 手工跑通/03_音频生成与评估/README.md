# 03 音频生成与评估

## 目标

把音频导演稿跑成可听成品，并在同一个任务里完成短测、全篇生成、自动预检、人工复听和小修决策。

生成和评估不拆开：因为当前还在手工跑通阶段，真正的问题往往出现在“生成参数 -> 听感 -> 小修 -> 重生成”的闭环里。拆成两个任务会让问题记录和修复动作断开。

## 输入

- `稿子/日期_话题_minimax导演稿_v1.md`
- `tts/出音频.py`
- `tts/.env`
- 本目录的 `MiniMax_播客音频生成研究与指导书_v0.1.md`
- 本目录的 `音频自然度与情绪评估工具调研_v0.1.md`

## 步骤

1. 确认 `MINIMAX_API_KEY`、爸爸/孩子 `voice_id`、`MINIMAX_MODEL` 和 endpoint。
2. 先生成 6-8 个高风险 turn 的短测，检查声音区分、停顿、错读、控制词是否外露。
3. 短测过线后生成全篇音频。
4. 保留 `.minimax-request.txt` 和 `.minimax-request.json`，追溯实际发给 TTS 的文本和参数。
5. 用 ASR 对齐原稿，抓错读、漏读、专名问题。
6. 用本地情绪/自然度工具给 turn 排风险优先级。
7. 成人抽听高风险 turn、开头、结尾和少量随机 turn。
8. 小修只改音频导演层；最多 2-3 轮，仍不过线就退回 `02_音频导演稿/`。

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
- 必要时生成 `稿子/日期_话题_minimax导演稿_v2.md`

## 通过标准

- 爸爸/孩子声音能稳定区分。
- 拼接停顿不突兀。
- 控制词没有被读出来。
- 专名、数字、中英混读没有明显错读。
- 情绪峰值和导演意图大体一致。
- 成人复听认为“像聊天”，不是新闻播报或朗读作文。
- 孩子反馈进入 `孩子反应日志.md`。

## 沉淀位置

- 稳定参数写回 `tts/README.md` 或 `tts/出音频.py`。
- 供应商能力判断保留在本目录指导书。
- 可自动化的检查写回未来评估脚本。
- 主观评分标准保留在本目录，稳定后再并入正式流程。
