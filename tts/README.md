# tts —— 把稿子变成音频（手工三步第三步）

手工三步里的 ③ TTS。本机已装好 **VoxCPM2**（本地、离线、免费、中文原生），用它把一期稿子合成一个 mp3，拷到手机放给孩子听。

## 一条命令

在 `heytoday/` 目录下：

```powershell
D:/project-script/VoxCPM/.venv/Scripts/python.exe tts/出音频.py 稿子/2026-06-30_Pando一棵树的树林_小学档.md
```

不带参数则自动取 `稿子/` 里最新一期。输出到 `音频/日期_话题.mp3`。

## 它做了什么

- **自动双声**：爸爸=温和中年男声、孩子=清亮男孩声（用户 2026-06-30 选的方案）。
- **锚点克隆保稳**：首次运行各生成一个锚点音色存到 `tts/voices/`，之后**每天复用同一锚点**——两个"角色"天天听起来是同一个人。想换音色：改 `出音频.py` 顶部 `VOICE_DESIGN`，删掉 `tts/voices/` 下对应 wav，再跑。
- 自动从「## 正文」里抓 `**爸爸**：`/`**孩子**：` 台词，剥掉 `**`、（舞台提示）、出处与自检；句间留停顿、换人留更长停顿；整段统一音量；ffmpeg 导出 mp3。

## 调参（都在 `出音频.py` 顶部 CONFIG）

- `CFG_VALUE`：嗓音发紧就调低（更松弛自然）。
- `INFERENCE_TIMESTEPS`：越高越精细越慢。
- `PAUSE_SAME` / `PAUSE_SWITCH`：嫌太赶就加大（家庭收听时的慢聊感）。
- `MP3_BITRATE`：语音 96k 足够。

## 环境（已就绪，留档）

- VoxCPM venv：`D:/project-script/VoxCPM/.venv`（Python 3.12，torch cu128，CUDA=True，RTX 5060 8G）
- 模型 `openbmb/VoxCPM2` 权重已在 HF 缓存；ffmpeg 系统已装。
- 实测：Pando 这期 47 句，约 8–12 分钟跑完，出 6 分半 mp3。

## 换后端：云端 TTS 与对话感验证

逐句生成再拼接容易带来"无互动感 + 情绪生硬"。用环境变量 `HEYTODAY_TTS_BACKEND` 切后端（默认 `voxcpm`，不改现状）：

- `voxcpm`（默认）：现状，本机逐句克隆 + 拼接，离线免费，作退路。
- `fish`：Fish Audio 云端，优先用于验证官方多说话人路径；非稳定模型会自动退到逐句拼接。
- `minimax`：MiniMax 云端 `speech-2.8-hd`，公开 T2A 文档当前只确认单 `voice_id` 控制；本脚本先用逐句/逐 turn 生成后拼接，作为“精细参数控制 + 对话感”测试通道。若后续确认 MiniMax 有稳定原生多说话人 API，再把它升为主路线。
- `moss`：本地 MOSS-TTSD，待接入（Stage C）。

密钥/配置放在 **`tts/.env`**（脚本自动读取；系统已设的同名环境变量优先）。Fish 需要：
1. `FISH_API_KEY`：注册 <https://fish.audio> → 控制台拿。
2. `FISH_VOICE_ID_DAD` / `FISH_VOICE_ID_KID`：把 `voices/爸爸_anchor.wav`、`孩子_anchor.wav` 上传 fish.audio 控制台各建一个 voice model，复制 id（顺序固定：DAD=speaker:0，KID=speaker:1）。

```powershell
# tts/.env 填好后：
$env:HEYTODAY_TTS_BACKEND="fish"; D:/project-script/VoxCPM/.venv/Scripts/python.exe tts/出音频.py 稿子/2026-06-30_Pando一棵树的树林_小学档.md
```

情绪映射：稿子里的 `（笑）（叹气）（兴奋）（惊讶）（轻声）` 自动转成 Fish 行内标签 `[laughs]/[sigh]/[excited]/[surprised]/[whisper]`；问号/感叹/省略号靠文本本身承载。

MiniMax 需要：
1. `MINIMAX_API_KEY`：MiniMax 开放平台「账户管理 > 接口密钥」里拿。
2. `MINIMAX_MODEL`：默认 `speech-2.8-hd`。
3. `MINIMAX_VOICE_ID_DAD` / `MINIMAX_VOICE_ID_KID`：默认先用系统音色；有自定义/复刻音色后替换为自己的 voice id。
4. `MINIMAX_ENDPOINT`：优先尝试的 endpoint。本项目使用 MiniMax 国内版 key，默认走 `https://api.minimaxi.com/v1/t2a_v2`。
5. `MINIMAX_ENDPOINTS`：可选，多个 endpoint 候选用逗号或分号分隔。脚本遇到鉴权类错误会自动尝试下一个候选，并把最终成功的 endpoint 写入 `.minimax-request.json`。

endpoint 说明：`.io` 是国际版 endpoint，当前 `.com` key 不通用；日常不要混用。本项目默认只尝试国内版 `.com`：

```text
https://api.minimaxi.com/v1/t2a_v2
```

只有在换成国际版 key 时，才显式配置 `MINIMAX_ENDPOINT` 或 `MINIMAX_ENDPOINTS` 为 `https://api.minimax.io/v1/t2a_v2` / `https://api-uw.minimax.io/v1/t2a_v2`。

```powershell
$env:HEYTODAY_TTS_BACKEND="minimax"; D:/project-script/VoxCPM/.venv/Scripts/python.exe tts/出音频.py 稿子/2026-06-30_Pando一棵树的树林_小学档.md
```

endpoint 短测：

```powershell
$env:HEYTODAY_TTS_BACKEND="minimax"
D:/project-script/VoxCPM/.venv/Scripts/python.exe tts/出音频.py 稿子/_MiniMax_endpoint兼容短测.md
```

MiniMax 后端只使用 Speech-2.8 原生控制；原生多说话人能力需另行短测确认：
- 文本内 `\n` 或 `<换段>` → 发送为换行，测试段落切换。
- 文本内 `<#0.70#>` → 发送为停顿控制。
- 舞台提示 `（笑）/（惊呼）/（叹气）/（吸气）` → 转为 `(laughs)/(gasps)/(sighs)/(inhale)` 等原生语气词标签。
- 舞台提示 `（开心）/（紧张）/（平静）/（温和）` → 转为官方 `emotion` 枚举中的 `happy/fearful/calm`；`（压低）/（轻声）/（慢）/（快）/（喊）` 只调 `speed/vol/pitch`。
- 舞台提示 `（音色=male-qn-qingse）` → 覆盖本句 `voice_setting.voice_id`，用于快速试听系统音色。
- 舞台提示 `（更低沉/更明亮/浑厚/清脆/柔和/有力）` → 转为 `voice_modify.pitch/timbre/intensity`。
- 舞台提示 `（音效=spacious_echo）/（音效=lofi_telephone）/（音效=robotic）` → 转为 `voice_modify.sound_effects`。
- 请求里固定带 `language_boost=Chinese`、mp3/32k/128k，并带 `pronunciation_dict.tone`。这里不再只是测试项：专名、外文名、品牌名和关键多音字短语可以写入字典；临时补充可用 `MINIMAX_PRONUNCIATION_TONE` 注入，最终以 `.minimax-request.json` 里的 `payload_features.pronunciation_dict` 为核对依据。
- 不建议在导演正文里直接塞 `(shu3)` 这类拼音括号；当前脚本会清理普通括号舞台提示，正式主线优先用 `pronunciation_dict.tone` 留痕。
- `timbre_weights` 是文档里的 legacy 字段；当前用系统音色实测返回 `voice id not exist`，先保留脚本解析能力，但不放进主测试音频。

高情绪能力短测：

```powershell
$env:HEYTODAY_TTS_BACKEND="minimax"; D:/project-script/VoxCPM/.venv/Scripts/python.exe tts/出音频.py 稿子/_MiniMax_Speech28高情绪能力测试.md
```

控制面板短测：

```powershell
$env:HEYTODAY_TTS_BACKEND="minimax"; D:/project-script/VoxCPM/.venv/Scripts/python.exe tts/出音频.py 稿子/_MiniMax_Speech28控制面板测试.md
```

> `tts/.env` 是本机密钥文件——别外传、别贴聊天、别提交版本库。
