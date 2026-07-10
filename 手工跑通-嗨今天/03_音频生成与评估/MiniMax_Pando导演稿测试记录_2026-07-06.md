# MiniMax Pando 导演稿测试记录 2026-07-06

## 目标

在 E「稳定音色轻情绪」短测被接受后，把规则迁移到真实 Pando 稿：

1. 生成完整 `minimax导演稿_v1`。
2. 先截取 6 turn 短样验证真实稿开头。
3. 暂不生成整期，等成人复听短样后再继续。

## 输入

| 文件 | 用途 |
|---|---|
| `稿子/2026-06-30_Pando一棵树的树林_minimax导演稿_v1.md` | 完整 MiniMax 导演稿 |
| `稿子/2026-06-30_Pando一棵树的树林_minimax短样_E_v1.md` | 从完整导演稿截取的 6 turn 短样 |
| `稿子/2026-06-30_Pando一棵树的树林_minimax短样_E_v2.md` | 针对“平、不够口语化”的重写短样，8 turn |
| `稿子/2026-06-30_Pando一棵树的树林_minimax短样_E_v3.md` | v2 压缩版，6 turn |

## 生成命令

```powershell
$env:HEYTODAY_TTS_BACKEND = "minimax"
D:/project-script/VoxCPM/.venv/Scripts/python.exe tts/出音频.py 稿子/2026-06-30_Pando一棵树的树林_minimax短样_E_v1.md
```

本次短样首次请求成功。

v2、v3 补测也均首次请求成功。

## 产物

| 产物 | 结果 |
|---|---|
| 音频 | `音频/2026-06-30_Pando一棵树的树林_minimax短样_E_v1.minimax.mp3` |
| request txt | `音频/2026-06-30_Pando一棵树的树林_minimax短样_E_v1.minimax.minimax-request.txt` |
| request json | `音频/2026-06-30_Pando一棵树的树林_minimax短样_E_v1.minimax.minimax-request.json` |
| line parts | `音频/2026-06-30_Pando一棵树的树林_minimax短样_E_v1.minimax.line_parts/` |

## 自动预检

| 项目 | 结果 |
|---|---|
| 时长 | 39.93s |
| 模式 | `line_concat` |
| turn 数 | 6 turn：爸爸 3 / 孩子 3 |
| endpoint | `https://api.minimaxi.com/v1/t2a_v2` |
| `voice_modify` | 无 |
| `timbre_weights` | 无 |
| pitch 变化 | 无，所有 turn `pitch=0` |
| native tags | 无 `(gasps)/(laughs)/(sighs)` |
| 中文舞台提示外露 | request txt 未发现 `（` / `）` |
| Fish speaker 标签外露 | request txt 未发现 `<|speaker:n|>` |
| 音频规格 | mp3 / 32000 Hz / mono / 128000 bps |
| 峰值音量 | mean -29.1 dB，max -6.6 dB；未见 0 dB clipping |

## 听感迭代

### v1

用户复听反馈：有点平，不够生动和口语化。

判断：问题主要在台词仍像书面稿，不在 TTS 参数。继续保留 E 的稳定音色规则，优先改台词、节奏和换人密度。

### v2

修改动作：

- 开头直接抛“四万七千多根树干，科学家说是一棵树”。
- 孩子提前出现“啊？”和反问。
- 增加“一个班叫一个同学”“手掌/手指”“树开的分身术”等口语化比方。

自动预检：

| 项目 | 结果 |
|---|---|
| 时长 | 50.08s |
| 模式 | `line_concat` |
| turn 数 | 8 turn：爸爸 4 / 孩子 4 |
| `voice_modify` | 无 |
| native tags | 无 |
| pitch 变化 | 无 |
| 峰值音量 | mean -28.1 dB，max -6.1 dB |

判断：台词方向更对，但短样超过 40 秒，不适合作为当前短测主样。

### v3

修改动作：

- 保留 v2 的口语化钩子。
- 去掉“一整个班叫一个同学”这一拍，把 8 turn 压到 6 turn。
- 保留孩子的“啊？”和“树开的分身术”。

自动预检：

| 项目 | 结果 |
|---|---|
| 音频 | `音频/2026-06-30_Pando一棵树的树林_minimax短样_E_v3.minimax.mp3` |
| 时长 | 33.45s |
| 模式 | `line_concat` |
| turn 数 | 6 turn：爸爸 3 / 孩子 3 |
| `voice_modify` | 无 |
| native tags | 无 |
| pitch 变化 | 无 |
| 中文舞台提示外露 | 无 |
| Fish speaker 标签外露 | 无 |
| 峰值音量 | mean -28.2 dB，max -7.6 dB |

判断：v3 是当前建议复听主样。若 v3 通过，再把完整 `minimax导演稿_v1` 的开头按 v3 方式改成 `v2`，再生成整期。

用户复听反馈：v3 可以，当前阶段完成；后续结合新的故事继续调整。

阶段结论：

- Pando 短样不再继续打磨。
- 当前 MiniMax 正式稿基线为：稳定音色、无 `voice_modify`、无手写 native tags，生动度主要靠更口语化的台词、提前反问、短句和换人密度。
- 下一轮不直接从 Pando 整期生成开始，而是用新故事验证这套音频导演规则能否迁移。

## 人工复听重点

- 开头爸爸是否仍像自然聊天，而不是念稿或主持。
- 孩子第一句“你念吧”是否过短、过机械。
- 450ms 换人停顿是否太齐。
- 这 40 秒是否足够形成钩子；如果偏慢，优先改台词长度，而不是加情绪。

## 下一步

若后续仍要生成 Pando 整期，先把完整导演稿开头改成更口语化版本，再生成完整音频：

```powershell
$env:HEYTODAY_TTS_BACKEND = "minimax"
D:/project-script/VoxCPM/.venv/Scripts/python.exe tts/出音频.py 稿子/2026-06-30_Pando一棵树的树林_minimax导演稿_v1.md
```

若短样仍觉得平，先在导演稿里改台词和停顿，不回到 D 类 `voice_modify`。
