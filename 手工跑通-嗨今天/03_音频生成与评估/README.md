# 03 音频生成与评估

## 目标

把音频导演稿跑成可听成品，并在同一个任务里完成短测、全篇生成、request 核对、SenseVoice 句级预检、人工复听和小修决策。SenseVoice 的 ASR 与情绪识别已纳入当前手工主线；自然度 MOS 仍未接入，继续由固定成人复听表判断，并在结果中如实标注。

生成和评估不拆开：因为当前还在手工跑通阶段，真正的问题往往出现在“生成参数 -> 听感 -> 小修 -> 重生成”的闭环里。拆成两个任务会让问题记录和修复动作断开。

## 输入

- `稿子/日期_话题_minimax导演稿_v1.md`
- `tts/出音频.py`
- `tts/评估音频.py`
- `tts/.env`
- 本目录的 `MiniMax_播客音频生成研究与指导书_v0.2.md`
- 本目录的 `音频自然度与情绪评估工具调研_v0.2.md`（正式评估指导书）

## 步骤

1. 确认 `MINIMAX_API_KEY`、爸爸/孩子 `voice_id`、`MINIMAX_MODEL` 和 endpoint。
2. 生成前检查导演稿的发音风险清单；把必须指定读音的多音字、专名、外文名、数字读法放进 `tts/出音频.py` 的 MiniMax `pronunciation_dict.tone` 或临时环境变量 `MINIMAX_PRONUNCIATION_TONE`。
3. 先生成 6-8 个高风险 turn 的短测，检查声音区分、停顿、错读、控制词是否外露。
4. 短测过线后生成全篇音频。
5. 保留 `.minimax-request.txt` 和 `.minimax-request.json`，追溯实际发给 TTS 的文本、参数和 `pronunciation_dict`。
6. 必做 request 核对：检查 `.minimax-request.txt` 和 `.minimax-request.json`，确认实际送入 TTS 的文本、`voice_modify`、控制词、`pronunciation_dict` 与预期一致；多音字/专名不能只写在文档里。
7. 必做基础文件核对：确认 mp3 存在、大小合理、时长落在目标范围，line parts 已生成。
8. **必做 SenseVoice 预检**：对每个 `line_parts` 运行 `tts/评估音频.py`。它按 `音频自然度与情绪评估工具调研_v0.2.md` 的 P0 思路，输出 ASR 回读、CER、声学情绪标签、原始模型输出和高风险 turn 排序。
9. 先看 `review_round*.csv` 与 `fix_plan_round*.json`：`CER > 0.10`、缺少 line part、单句推理失败、或有明确 MiniMax `emotion` 意图但被识别为不相近情绪的 turn，必须进入成人复听。中文数字被规范化为阿拉伯数字不算错读；SenseVoice 单模型的情绪结果只做提醒，不自动强修。
10. 根据 request 核对、SenseVoice 结果和人工复听生成小修建议：错读/漏读、专名多音字、拼接突兀、情绪不一致、自然度低分别标原因；建议只能指向音频导演层、发音词典、停顿、标签或局部重生成。
11. 成人抽听所有高风险 turn、开头、结尾和至少 2 个随机 turn；按评估指导书的“听得清 / 像真人 / 像对话 / 情绪合适 / 角色稳定 / 可给孩子听”六项记录。自然度 MOS 尚未运行，不能用自动分数代替这一步。
12. 小修最多 2-3 轮，仍不过线就退回 `02_音频导演稿/`。

## 命令

```powershell
$env:HEYTODAY_TTS_BACKEND="minimax"
D:/project-script/VoxCPM/.venv/Scripts/python.exe tts/出音频.py 稿子/日期_话题_minimax导演稿_v1.md

# 紧接生成后、成人复听前运行；参数必须是本期实际的 request JSON
$env:PYTHONUTF8="1"
D:/project-script/VoxCPM/.venv/Scripts/python.exe tts/评估音频.py 音频/日期_话题_minimax导演稿_v1.minimax.minimax-request.json
```

## 产物

- `音频/日期_话题_minimax导演稿_v1.minimax.mp3`
- `音频/日期_话题_minimax导演稿_v1.minimax.minimax-request.txt`
- `音频/日期_话题_minimax导演稿_v1.minimax.minimax-request.json`
- `音频/日期_话题_minimax导演稿_v1.minimax.line_parts/`
- `音频/xxx.emotion_raw.jsonl`（SenseVoice 原始 ASR / 情绪 / 事件输出）
- `音频/xxx.review_round1.csv`（按风险排序的成人复听队列）
- `音频/xxx.fix_plan_round1.json`（只含局部、可回滚的小修建议）
- `音频/xxx.eval_summary.md`（可选；汇总 request 核对、自动预检、成人复听和小修结论）
- 必要时生成 `稿子/日期_话题_minimax导演稿_v2.md`

## 通过标准

- 爸爸/孩子声音能稳定区分。
- 拼接停顿不突兀。
- 控制词没有被读出来。
- 专名、数字、中英混读、多音字没有明显错读；request JSON 中必须能看到本期必要的 `pronunciation_dict.tone`。
- 情绪峰值和导演意图大体一致。
- request 文本/JSON 已核对；SenseVoice 的 `emotion_raw.jsonl`、`review_round*.csv`、`fix_plan_round*.json` 已生成。若自然度 MOS 未跑，结果里已明确说明。
- 所有 SenseVoice 高风险 turn 均已人工复听并写明结论；模型的情绪标签或 CER 不单独决定通过。
- 成人复听已覆盖高风险 turn、开头、结尾和随机 turn。
- 成人复听认为“像聊天”，不是新闻播报或朗读作文。
- 孩子反馈进入 `孩子反应日志.md`。

## 沉淀位置

- 稳定参数写回 `tts/README.md` 或 `tts/出音频.py`。
- 供应商能力判断保留在本目录指导书。
- 当前已落地的 SenseVoice 检查写回 `tts/评估音频.py`；自然度 MOS 接入后再扩展该命令。
- 自动评估指标和人工复听表的稳定经验，回写 `音频自然度与情绪评估工具调研_v0.2.md` 或后续升版。
