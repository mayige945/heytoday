# MiniMax Speech-2.8-HD 控制面板短测

> **怎么跑**：`$env:HEYTODAY_TTS_BACKEND="minimax"; D:/project-script/VoxCPM/.venv/Scripts/python.exe tts/出音频.py 稿子/_MiniMax_Speech28控制面板测试.md`
>
> **测试目标**：按 MiniMax T2A HTTP 文档逐项验听。每句尽量只突出一种控制：音色、语速、音量、音高、情绪、停顿、段落、语气词、voice_modify、sound_effects、发音字典。
>
> 注：文档里有 legacy `timbre_weights` 字段，但当前用系统音色测试返回 `voice id not exist`，先不放进主测试音频，避免拖断生成。

---

## 正文

**爸爸**：（音色=male-qn-qingse 平静）一号，切到系统音色 male-qn-qingse。先听音色本身，不加特别情绪。

**爸爸**：（音色=male-qn-jingying 有力）二号，切到 male-qn-jingying，并加一点力量感。听起来应该更硬、更亮。

**孩子**：（快 大声 高音 兴奋）三号，测试 voice_setting：速度更快，音量更大，音高更高，情绪是 happy！

**孩子**：（慢 小声 低音 紧张）四号，反过来：速度更慢，音量更小，音高更低，情绪是 fearful。

**爸爸**：（叹气 更低沉 浑厚 柔和）五号，测试 voice_modify：整体更低沉、更浑厚、更柔和。(sighs)<#0.60#>这句应该像把声音压下来。

**孩子**：（惊呼 更明亮 清脆 有力）六号，测试 voice_modify 的另一边：更明亮、更清脆、更有力。(gasps)<#0.40#>这句应该更跳、更锐。

**爸爸**：（音效=spacious_echo）七号，测试 voice_modify.sound_effects：spacious_echo。听听有没有空旷回音。

**孩子**：（音效=robotic）八号，测试 sound_effects：robotic。MiniMax 现在听起来像不像一台小机器人？

**爸爸**：（音效=lofi_telephone 厌恶）九号，测试 sound_effects：lofi_telephone，再加 disgusted 情绪。听听是不是像电话里皱着眉头说话。

**孩子**：（笑 开心）十号，测试原生语气词和文本停顿。(laughs)<#0.80#>笑完以后，应该停一下再继续。

**爸爸**：（平静）十一号，测试段落换行。\n第一段结束。<#0.50#>\n第二段开始，语气应该像换了一口气。

**孩子**：（兴奋）十二号，测试发音字典：Pando 和 MiniMax 应该按请求里的 pronunciation_dict 读。

---
