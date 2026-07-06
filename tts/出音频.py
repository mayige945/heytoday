# -*- coding: utf-8 -*-
"""
出音频.py —— 把一期稿子（Markdown）变成一个可放给孩子听的 mp3。

手工三步的第三步（TTS）的最小实现。用本机已装好的 VoxCPM2（本地、离线、免费）。
设计目标：最小成本、一条命令跑通、两个稳定的声音（爸爸 + 孩子）。

用法（在 heytoday 目录下）：
    D:/project-script/VoxCPM/.venv/Scripts/python.exe tts/出音频.py
    D:/project-script/VoxCPM/.venv/Scripts/python.exe tts/出音频.py 稿子/2026-06-30_Pando一棵树的树林_小学档.md

做法（自动双声 + 锚点克隆，保证音色天天一致）：
  1. 第一次运行时，用 VoxCPM 的「声音设计」各生成一个锚点片段，存到 tts/voices/。
     以后每天复用这两个锚点 —— 这样"爸爸""孩子"两个角色每期听起来都是同一个人。
  2. 解析稿子「正文」里的 **爸爸**：… / **孩子**：… 台词（自动去掉 **、（舞台提示）、出处自检等）。
  3. 每句用各自锚点做零样本克隆合成；句间留停顿、换人留更长停顿；拼成整段。
  4. 用 ffmpeg 导出 音频/日期_话题.mp3。

要改音色 / 语速感觉，调下面 CONFIG 即可（删掉 tts/voices/ 下的锚点会按新描述重生成）。
"""

import os
import re
import sys
import glob
import shutil
import subprocess
import json
from pathlib import Path

import numpy as np
import soundfile as sf

# ---------------- CONFIG（最常调的都在这） ----------------
HF_MODEL_ID = "openbmb/VoxCPM2"

# 两个角色的「声音设计」描述（只在生成锚点那一次用到；想换音色就改这里并删掉对应锚点 wav）
VOICE_DESIGN = {
    "爸爸": "一位中年男性，声音温和、沉稳，语速从容，像在自家早餐桌上轻松和孩子聊天",
    "孩子": "一个十岁左右的小男孩，声音清亮、自然，带着好奇和一点点活泼",
}
# 生成锚点时念的中性句子（内容不重要，只为定音色）
ANCHOR_SENTENCE = {
    "爸爸": "来，我们慢慢聊，我也不太确定，咱俩一起想想看。",
    "孩子": "真的吗？那到底是为什么呀，我有点想不明白。",
}

# 逐句情绪控制（VoxCPM「可控声音克隆」：锚点定音色不变，叠加 (描述) 调情绪/语速）
USE_PER_LINE_CONTROL = True
SPEAKER_TONE = {           # 每个角色的基础语气，每句都带上
    "爸爸": "温和从容",
    "孩子": "自然好奇",
}
# 真人录音锚点的朗读文本（开启「极致克隆」：参考音频+这段文本一起喂，保真最高）。
# 必须与录音实际读的内容一致；留空则该角色退回普通克隆。
ANCHOR_TRANSCRIPT = {     # 录音不保证逐字匹配脚本，先用普通克隆（留空）；若确认逐字读了可填回开启极致克隆
    "爸爸": "",
    "孩子": "",
}
STAGE_MAP = {              # 把稿子里的舞台提示（…）翻成情绪/语速指令（命中关键词即取）
    "笑": "带着笑意",
    "停": "放慢、停顿思考",
    "顿": "放慢、停顿思考",
    "没接话": "语气很轻、若有所思",
    "沉默": "语气很轻、若有所思",
    "想": "慢慢地、像在想",
}

CFG_VALUE = 1.3            # 越高越贴文本（偏平）、越低越松弛会演；治"生硬"就调低（默认2.0，现降到1.3）
INFERENCE_TIMESTEPS = 24   # 越高越精细越慢（默认10，提到24求更自然）
PAUSE_SAME = 0.40          # 同一个人连说，句间停顿（秒）
PAUSE_SWITCH = 0.70        # 换人说话，停顿（秒）
MP3_BITRATE = "96k"        # 语音 96k 足够，文件小好传手机
# --------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent      # heytoday/
VOICES_DIR = REPO / "tts" / "voices"
OUT_DIR = REPO / "音频"
SPEAKERS = ("爸爸", "孩子")

# ---------------- 多后端（云端 TTS / 对话感验证） ----------------
# 用环境变量 HEYTODAY_TTS_BACKEND 切换（密钥/配置见 tts/.env）：
#   voxcpm（默认/本机退路，逐句克隆+拼接）| fish（云·单次双人，验听感）| minimax（云·逐句双声拼接）| moss（本地·待接入）
SPK_IDX = {"爸爸": 0, "孩子": 1}            # Fish/MOSS 的说话人序号（0=爸爸 / 1=孩子）
FISH_MODEL = "s2-pro"                      # Fish 官方文档标注：多说话人 dialogue 仅 S2-Pro 支持
FISH_TEMPERATURE = 0.85   # 官方"controls expressiveness"，上调让对话带语调起伏（默认0.7）；读数字/片头嫌乱可降到0.6
FISH_TOP_P = 0.7          # 只用 temperature 一个旋钮调表现力，这个不动
FISH_SPEED = 1.06         # 活泼口语底色（别超1.15，孩子档听清优先）
FISH_CHUNK_MAX_CHARS = 650 # 长篇多说话人整段生成容易 speaker 漂移；超过该长度自动按 turn 分块生成再拼接
FISH_PAUSE_SAME_MS = 250  # Fish 逐句保底拼接：同一说话人连续两句之间的停顿
FISH_PAUSE_SWITCH_MS = 450 # Fish 逐句保底拼接：换人停顿
FISH_TAG = {                                # 仅留 4 个有声学特征、实测生效的极端标签；其余情绪靠台词+标点（见 手工跑通/02_音频导演稿/情绪playbook_v1.md）
    "笑": "[laughing]", "哈": "[laughing]",
    "轻声": "[whispering]", "放轻": "[whispering]", "压低": "[whispering]",
    "喊": "[shouting]", "惊呼": "[shouting]",
    "哭": "[crying loudly]",
}
MINIMAX_ENDPOINT = "https://api.minimaxi.com/v1/t2a_v2"
MINIMAX_COMPAT_ENDPOINTS = [
    "https://api.minimaxi.com/v1/t2a_v2",
]
MINIMAX_MODEL = "speech-2.8-hd"
MINIMAX_VOICE_ID_DAD = "Chinese (Mandarin)_Sincere_Adult"
MINIMAX_VOICE_ID_KID = "Chinese (Mandarin)_Pure-hearted_Boy"
MINIMAX_SPEED = 1.0
MINIMAX_VOL = 1.0
MINIMAX_PITCH = 0
MINIMAX_SAMPLE_RATE = 32000
MINIMAX_BITRATE = 128000
MINIMAX_PAUSE_SAME_MS = 250
MINIMAX_PAUSE_SWITCH_MS = 450
MINIMAX_NATIVE_TAGS = {
    "laughs", "chuckle", "coughs", "clear-throat", "groans", "breath", "pant",
    "inhale", "exhale", "gasps", "sniffs", "sighs", "snorts", "burps",
    "lip-smacking", "humming", "hissing", "emm", "sneezes",
}
MINIMAX_TAG = {                             # Speech-2.8 原生语气词标签，谨慎少用
    "轻笑": "(chuckle)", "笑": "(laughs)", "哈": "(laughs)",
    "叹气": "(sighs)", "叹": "(sighs)",
    "吸气": "(inhale)", "喘": "(pant)",
    "惊呼": "(gasps)", "震惊": "(gasps)", "惊": "(gasps)",
    "清嗓": "(clear-throat)", "咳": "(coughs)",
    "嗯": "(emm)",
}
MINIMAX_EMOTION = {
    "开心": "happy", "高兴": "happy", "兴奋": "happy", "笑": "happy",
    "难过": "sad", "伤心": "sad", "失落": "sad", "叹": "sad",
    "生气": "angry", "愤怒": "angry", "急": "angry",
    "厌恶": "disgusted",
    "害怕": "fearful", "紧张": "fearful",
    "震惊": "surprised", "惊": "surprised",
    "平静": "calm", "温和": "calm",
}
MINIMAX_SOUND_EFFECTS = {
    "空旷": "spacious_echo", "空间": "spacious_echo", "回音": "spacious_echo",
    "礼堂": "auditorium_echo", "广播": "auditorium_echo",
    "电话": "lofi_telephone",
    "机器人": "robotic", "电音": "robotic",
}


def load_env_file():
    """把 tts/.env（或 heytoday/.env）里的 KEY=VALUE 读进环境变量（系统已设的同名变量优先）。"""
    for envp in (REPO / ".env", REPO / "tts" / ".env"):
        if not envp.exists():
            continue
        for line in envp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("找不到 ffmpeg：系统未安装，venv 里也没有 imageio-ffmpeg。")


def pick_episode() -> Path:
    """命令行给了就用；否则取 稿子/ 里最新的一期。"""
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if not p.is_absolute():
            p = REPO / p
        if not p.exists():
            sys.exit(f"找不到稿子：{p}")
        return p
    cands = sorted(glob.glob(str(REPO / "稿子" / "*.md")))
    if not cands:
        sys.exit("稿子/ 目录下没有 .md。")
    return Path(cands[-1])


def clean_line(text: str) -> str:
    """去掉 markdown 加粗、（舞台提示）、多余空白，只留要念的话。"""
    text = text.replace("**", "")
    text = re.sub(r"（[^（）]*）", "", text)   # 全角舞台提示，如（笑）（停一下）
    text = re.sub(r"\([^()]*\)", "", text)     # 半角同理
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_dialogue(md_path: Path):
    """抽出「正文」里的 (说话人, 台词) 列表。"""
    raw = md_path.read_text(encoding="utf-8").splitlines()
    # 锁定正文区间：从 '## 正文' 到其后第一条 '---'
    start = next((i for i, l in enumerate(raw) if l.startswith("## 正文")), None)
    if start is None:
        sys.exit("稿子里没有「## 正文」小节。")
    body = []
    for l in raw[start + 1:]:
        if l.strip() == "---":
            break
        body.append(l)

    pat = re.compile(r"^\*\*(爸爸|孩子)\*\*：(.+)$")
    out = []
    for l in body:
        m = pat.match(l.strip())
        if not m:
            continue
        out.append((m.group(1), m.group(2)))   # 保留原始台词（含舞台提示），情绪在后面提取
    if not out:
        sys.exit("正文里没解析到任何 **爸爸**：/ **孩子**： 台词，检查体例。")
    return out


def build_control(speaker, raw_said):
    """据舞台提示 + 标点给这句拼一段情绪/语速指令；返回 (控制串, 要念的文本)。"""
    cues = []
    for d in re.findall(r"（([^（）]*)）", raw_said) + re.findall(r"\(([^()]*)\)", raw_said):
        for k, v in STAGE_MAP.items():
            if k in d and v not in cues:
                cues.append(v)
    spoken = re.sub(r"\[[^\[\]]*\]", "", clean_line(raw_said))   # voxcpm 不识别 Fish [标签]，剥掉免得念出来
    if spoken.endswith(("？", "?")):
        cues.append("语气上扬、带点好奇")
    elif spoken.endswith(("！", "!")):
        cues.append("语气惊讶、有点激动")
    if "……" in spoken:
        cues.append("中途略停顿、放缓")
    uniq = []
    for c in cues:                              # 去重 + 限量，避免指令打架
        if c not in uniq:
            uniq.append(c)
    parts = [SPEAKER_TONE.get(speaker, "")] + uniq[:2]
    return "，".join(p for p in parts if p), spoken


def ensure_anchors(model, sr):
    """每个角色一个固定锚点 wav；已存在就复用（保证天天同一个声音）。"""
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    anchors = {}
    for sp in SPEAKERS:
        wav_path = VOICES_DIR / f"{sp}_anchor.wav"
        if not wav_path.exists():
            print(f"  · 生成 {sp} 锚点音色（仅首次）…", flush=True)
            text = f"({VOICE_DESIGN[sp]}){ANCHOR_SENTENCE[sp]}"
            audio = model.generate(text=text, cfg_value=CFG_VALUE,
                                   inference_timesteps=INFERENCE_TIMESTEPS)
            sf.write(str(wav_path), audio, sr)
        anchors[sp] = str(wav_path)
    return anchors


def build_fish_script(lines):
    """把 (说话人, 原始台词) 列表拼成一段 Fish 多说话人脚本：
    <|speaker:0|>[情绪]这句话<|speaker:1|>…  —— 整段一次生成，不拼接。
    情绪来自舞台提示（转 Fish 行内标签）；问号/感叹/省略号靠文本本身承载。"""
    parts = []
    for sp, raw in lines:
        spoken = clean_line(raw)                         # 复用现有：剥 ** 和（舞台提示）
        if not spoken:
            continue
        tags = []
        for d in re.findall(r"（([^（）]*)）", raw) + re.findall(r"\(([^()]*)\)", raw):
            for k, v in FISH_TAG.items():
                if k in d and v not in tags:
                    tags.append(v)
        prefix = tags[0] if tags else ""                 # 一句最多一个标签，避免打架
        parts.append(f"<|speaker:{SPK_IDX[sp]}|>{prefix}{spoken}")
    if not parts:
        sys.exit("没有可合成的台词。")
    text = "".join(parts)
    # 关键：Fish S2 标签必须用半角 []，且标签后留 ASCII 空格更有效。
    # 多标签不推荐用于正文；若出现 [a][b]正文，只在最后一个标签后补空格。
    text = re.sub(r"(\[[^\[\]]*\])(?=\S)", r"\1 ", text)
    return text


def build_fish_turn_text(sp, raw):
    """单 voice_id 生成时的一句文本：不带 speaker 标签，只保留 Fish S2 方括号控制。"""
    spoken = clean_line(raw)
    if not spoken:
        return ""
    tags = []
    for d in re.findall(r"（([^（）]*)）", raw) + re.findall(r"\(([^()]*)\)", raw):
        for k, v in FISH_TAG.items():
            if k in d and v not in tags:
                tags.append(v)
    prefix = tags[0] if tags else ""
    text = f"{prefix}{spoken}"
    return re.sub(r"(\[[^\[\]]*\])(?=\S)", r"\1 ", text)


def mask_id(value):
    if not value:
        return ""
    return f"{value[:8]}...{value[-6:]}"


def env_float(name, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        sys.exit(f"{name} 必须是数字，当前是：{raw!r}")


def env_int(name, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        sys.exit(f"{name} 必须是整数，当前是：{raw!r}")


class MiniMaxRequestError(Exception):
    def __init__(self, message, *, http_status=None, status_code=None, status_msg=None, body=None):
        super().__init__(message)
        self.http_status = http_status
        self.status_code = status_code
        self.status_msg = status_msg or ""
        self.body = body or ""

    @property
    def is_auth_error(self):
        msg = self.status_msg.lower()
        return self.http_status in {401, 403} or self.status_code in {1008, 2049} or "api key" in msg


def split_env_list(value):
    return [item.strip() for item in re.split(r"[,，;；\s]+", value or "") if item.strip()]


def minimax_endpoint_candidates():
    """按本项目使用的 MiniMax 国内版 endpoint 优先生成候选。"""
    configured = split_env_list(os.environ.get("MINIMAX_ENDPOINTS", ""))
    single = os.environ.get("MINIMAX_ENDPOINT", "").strip()
    if single:
        configured.insert(0, single)
    if not configured:
        configured.append(MINIMAX_ENDPOINT)

    out = []
    for endpoint in configured + MINIMAX_COMPAT_ENDPOINTS:
        endpoint = endpoint.rstrip()
        if endpoint and endpoint not in out:
            out.append(endpoint)
    return out


def fish_payload(text, ref, model_name):
    return {
        "text": text,
        "reference_id": ref,
        "format": "mp3",
        "mp3_bitrate": 128,
        "temperature": env_float("FISH_TEMPERATURE", FISH_TEMPERATURE),
        "top_p": env_float("FISH_TOP_P", FISH_TOP_P),
        "prosody": {"speed": env_float("FISH_SPEED", FISH_SPEED), "volume": 0},
        "chunk_length": 300,
        "normalize": os.environ.get("FISH_NORMALIZE", "true").strip().lower() != "false",
        "condition_on_previous_chunks": True,
    }


def write_fish_debug(mp3_out, lines, text, ref, model_name, chunks):
    """落盘实际送给 Fish 的文本和脱敏元数据，便于听感异常时追溯。"""
    debug_txt = mp3_out.with_suffix(".fish-request.txt")
    debug_json = mp3_out.with_suffix(".fish-request.json")
    debug_txt.write_text(text, encoding="utf-8")
    debug_json.write_text(
        json.dumps(
            {
                "model": model_name,
                "voice_ids": [mask_id(v) for v in ref] if isinstance(ref, list) else mask_id(ref),
                "turn_count": len(lines),
                "dad_turns": sum(s == "爸爸" for s, _ in lines),
                "kid_turns": sum(s == "孩子" for s, _ in lines),
                "text_chars": len(text),
                "speaker_0_tags": text.count("<|speaker:0|>"),
                "speaker_1_tags": text.count("<|speaker:1|>"),
                "chunk_count": len(chunks),
                "chunks": [
                    {
                        "turn_count": len(chunk_lines),
                        "chars": len(chunk_text),
                        "dad_turns": sum(s == "爸爸" for s, _ in chunk_lines),
                        "kid_turns": sum(s == "孩子" for s, _ in chunk_lines),
                    }
                    for chunk_lines, chunk_text, _ in chunks
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def chunk_fish_lines(lines, max_chars):
    """按完整 turn 切分，避免 Fish 服务端在长文本中间切坏说话人上下文。"""
    chunks = []
    current = []
    current_chars = 0
    for line in lines:
        line_text = build_fish_script([line])
        if current and current_chars + len(line_text) > max_chars:
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(line)
        current_chars += len(line_text)
    if current:
        chunks.append(current)
    return chunks


def request_fish_audio(session, key, model_name, payload, out_path):
    r = session.post(
        "https://api.fish.audio/v1/tts",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json", "model": model_name},
        json=payload,
        stream=True, timeout=600,
    )
    if r.status_code != 200:
        sys.exit(f"Fish 接口报错 {r.status_code}：{r.text[:300]}")
    with open(out_path, "wb") as f:
        for chunk in r.iter_content(8192):
            if chunk:
                f.write(chunk)


def parse_minimax_timbre_weights(value):
    """解析 voiceA:70,voiceB:30 形式的 timbre_weights。"""
    weights = []
    for item in re.split(r"[,，]", value):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            sys.exit(f"MiniMax 混合音色格式错误：{value!r}；应为 voice_id:weight,voice_id:weight")
        voice_id, weight = item.rsplit(":", 1)
        try:
            weight_int = int(weight.strip())
        except ValueError:
            sys.exit(f"MiniMax 混合音色 weight 必须是整数：{item!r}")
        weights.append({"voice_id": voice_id.strip(), "weight": weight_int})
    if len(weights) > 4:
        sys.exit("MiniMax timbre_weights 最多 4 个 voice_id。")
    return weights


def minimax_line_controls(raw, speaker):
    """从中文舞台提示提取 MiniMax 原生控制；返回 (文本前缀, voice_setting 增量, 顶层扩展)。"""
    cues = re.findall(r"（([^（）]*)）", raw) + re.findall(r"\(([^()]*)\)", raw)
    tags = []
    controls = {}
    extras = {}
    voice_modify = {}
    for cue in cues:
        cue = cue.strip()
        if cue in MINIMAX_NATIVE_TAGS:
            tag = f"({cue})"
            if tag not in tags:
                tags.append(tag)
            continue
        voice_match = re.search(r"(?:音色|voice|voice_id)\s*=\s*([^\s，,；;]+)", cue, re.I)
        if voice_match:
            controls["voice_id"] = voice_match.group(1).strip()
        mix_match = re.search(r"(?:混合音色|timbre_weights)\s*=\s*(.+)$", cue, re.I)
        if mix_match:
            extras["timbre_weights"] = parse_minimax_timbre_weights(mix_match.group(1).strip())
        effect_match = re.search(r"(?:音效|sound_effects)\s*=\s*([a-z_]+)", cue, re.I)
        if effect_match:
            voice_modify["sound_effects"] = effect_match.group(1).strip()
        for k, v in MINIMAX_SOUND_EFFECTS.items():
            if k in cue:
                voice_modify["sound_effects"] = v
        for k, v in MINIMAX_TAG.items():
            if k in cue and v not in tags:
                tags.append(v)
        for k, v in MINIMAX_EMOTION.items():
            if k in cue:
                controls["emotion"] = v
                break
        if "快" in cue or "急" in cue:
            controls["speed"] = 1.18
        if "慢" in cue or "轻声" in cue or "压低" in cue:
            controls["speed"] = 0.88
        if "喊" in cue or "兴奋" in cue or "惊呼" in cue:
            controls["vol"] = 1.18
            controls["pitch"] = 2 if speaker == "孩子" else 1
        if "低" in cue or "压低" in cue:
            controls["pitch"] = -2
        if "高音" in cue or "尖" in cue:
            controls["pitch"] = 4
        if "低音" in cue or "低沉" in cue:
            controls["pitch"] = -4
        if "大声" in cue:
            controls["vol"] = 1.35
        if "小声" in cue:
            controls["vol"] = 0.72
        if "更明亮" in cue:
            voice_modify["pitch"] = 45
        if "更低沉" in cue:
            voice_modify["pitch"] = -45
        if "柔和" in cue:
            voice_modify["intensity"] = 55
        if "有力" in cue or "力量" in cue:
            voice_modify["intensity"] = -55
        if "清脆" in cue:
            voice_modify["timbre"] = 55
        if "浑厚" in cue or "磁性" in cue:
            voice_modify["timbre"] = -55
        if "规范化" in cue or "text_normalization" in cue:
            controls["text_normalization"] = True
        if "latex" in cue.lower() or "公式" in cue:
            controls["latex_read"] = True
    if voice_modify:
        extras["voice_modify"] = voice_modify
    return "".join(tags[:2]), controls, extras


def build_minimax_turn_text(raw, speaker):
    """MiniMax 单 voice_id 合成文本：只使用 Speech-2.8 原生文本控制。"""
    prefix, _, _ = minimax_line_controls(raw, speaker)
    text = re.sub(r"\[[^\[\]]*\]", "", raw)       # Fish S2 方括号标签不传给 MiniMax
    for tag in MINIMAX_NATIVE_TAGS:               # 保护用户手写的 MiniMax 原生标签
        text = re.sub(rf"\({re.escape(tag)}\)", f"@@MM_TAG_{tag}@@", text)
    text = re.sub(r"（[^（）]*）", "", text)         # 中文舞台提示只用于控制，不朗读
    text = re.sub(r"\([^()]*\)", "", text)         # 非原生半角提示也不朗读
    for tag in MINIMAX_NATIVE_TAGS:
        text = text.replace(f"@@MM_TAG_{tag}@@", f"({tag})")
    text = text.replace("\\n", "\n").replace("<换段>", "\n")
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return ""
    return f"{prefix}{text}"


def minimax_payload(text, voice_id, model_name, speaker, line_controls=None, line_extras=None):
    line_controls = line_controls or {}
    line_extras = line_extras or {}
    voice_setting = {
        "voice_id": voice_id,
        "speed": env_float("MINIMAX_SPEED", MINIMAX_SPEED),
        "vol": env_float("MINIMAX_VOL", MINIMAX_VOL),
        "pitch": env_int("MINIMAX_PITCH", MINIMAX_PITCH),
    }
    emotion = os.environ.get(f"MINIMAX_EMOTION_{'DAD' if speaker == '爸爸' else 'KID'}", "").strip()
    if emotion:
        voice_setting["emotion"] = emotion
    voice_setting.update(line_controls)
    payload = {
        "model": model_name,
        "text": text,
        "stream": False,
        "voice_setting": voice_setting,
        "pronunciation_dict": {
            "tone": [
                "Pando/(pan1)(duo1)",
                "MiniMax/(mi2)(ni3)(mai4)(ke4)(si1)",
            ]
        },
        "audio_setting": {
            "sample_rate": env_int("MINIMAX_SAMPLE_RATE", MINIMAX_SAMPLE_RATE),
            "bitrate": env_int("MINIMAX_BITRATE", MINIMAX_BITRATE),
            "format": "mp3",
            "channel": 1,
        },
        "language_boost": os.environ.get("MINIMAX_LANGUAGE_BOOST", "Chinese").strip(),
        "subtitle_enable": os.environ.get("MINIMAX_SUBTITLE_ENABLE", "").strip().lower() == "true",
        "subtitle_type": os.environ.get("MINIMAX_SUBTITLE_TYPE", "sentence").strip(),
        "output_format": "hex",
        "aigc_watermark": False,
    }
    payload.update(line_extras)
    return payload


def request_minimax_audio(session, key, endpoint, payload, out_path):
    try:
        r = session.post(
            endpoint,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=600,
        )
    except Exception as e:
        raise MiniMaxRequestError(f"MiniMax 请求失败：{e}") from e
    if r.status_code != 200:
        raise MiniMaxRequestError(
            f"MiniMax 接口报错 {r.status_code}：{r.text[:500]}",
            http_status=r.status_code,
            body=r.text[:500],
        )
    try:
        data = r.json()
    except ValueError:
        raise MiniMaxRequestError(f"MiniMax 返回的不是 JSON：{r.text[:300]}", body=r.text[:300])
    base_resp = data.get("base_resp") or {}
    if base_resp.get("status_code", 0) != 0:
        raise MiniMaxRequestError(
            f"MiniMax 业务报错：{json.dumps(base_resp, ensure_ascii=False)}",
            status_code=base_resp.get("status_code"),
            status_msg=base_resp.get("status_msg"),
            body=json.dumps(base_resp, ensure_ascii=False),
        )
    audio_hex = ((data.get("data") or {}).get("audio") or "").strip()
    if not audio_hex:
        raise MiniMaxRequestError(f"MiniMax 返回里没有 data.audio：{json.dumps(data, ensure_ascii=False)[:500]}")
    try:
        out_path.write_bytes(bytes.fromhex(audio_hex))
    except ValueError:
        raise MiniMaxRequestError("MiniMax 返回的 data.audio 不是合法 hex 音频。")


def request_minimax_audio_with_fallback(session, key, endpoints, payload, out_path, active_idx=0):
    last_error = None
    for idx in range(active_idx, len(endpoints)):
        endpoint = endpoints[idx]
        try:
            request_minimax_audio(session, key, endpoint, payload, out_path)
            if idx != active_idx:
                print(f"  · MiniMax endpoint 切换成功：{endpoint}", flush=True)
            return idx
        except MiniMaxRequestError as e:
            last_error = e
            if e.is_auth_error and idx + 1 < len(endpoints):
                print(f"  · MiniMax endpoint 鉴权失败，尝试下一个：{endpoint}", flush=True)
                continue
            break
    if last_error:
        sys.exit(str(last_error))
    sys.exit("MiniMax endpoint 列表为空。")


def concat_mp3(parts, mp3_out, reencode=False):
    ffmpeg = find_ffmpeg()
    list_path = mp3_out.with_suffix(".concat.txt")
    lines = []
    for part in parts:
        safe_path = str(part).replace("'", "'\\''")
        lines.append(f"file '{safe_path}'")
    list_path.write_text("\n".join(lines), encoding="utf-8")
    cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path)]
    if reencode:
        cmd += ["-ac", "1", "-b:a", "128k", str(mp3_out)]
    else:
        cmd += ["-c", "copy", str(mp3_out)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    list_path.unlink(missing_ok=True)


def ensure_silence_mp3(tmp_dir, ms):
    ffmpeg = find_ffmpeg()
    path = tmp_dir / f"silence_{ms}ms.mp3"
    if path.exists():
        return path
    subprocess.run(
        [
            ffmpeg, "-y",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=mono",
            "-t", f"{ms / 1000:.3f}",
            "-b:a", "128k",
            str(path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return path


def synth_fish_line_concat(session, key, model_name, lines, ref, mp3_out):
    """逐句只传一个 voice_id，避免非稳定多说话人路径把全段吃成第一个声音。"""
    same_ms = int(os.environ.get("FISH_PAUSE_SAME_MS", str(FISH_PAUSE_SAME_MS)))
    switch_ms = int(os.environ.get("FISH_PAUSE_SWITCH_MS", str(FISH_PAUSE_SWITCH_MS)))
    tmp_dir = mp3_out.parent / f"{mp3_out.stem}.line_parts"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    part_paths = []
    spoken_records = []
    prev_sp = None
    try:
        for idx, (sp, raw) in enumerate(lines, 1):
            text = build_fish_turn_text(sp, raw)
            if not text:
                continue
            part_path = tmp_dir / f"{idx:02d}_{sp}.mp3"
            print(f"  · Fish 单句 {idx}/{len(lines)}：{sp}，{len(text)} 字", flush=True)
            request_fish_audio(session, key, model_name, fish_payload(text, ref[SPK_IDX[sp]], model_name), part_path)
            if prev_sp is not None:
                gap_ms = switch_ms if sp != prev_sp else same_ms
                part_paths.append(ensure_silence_mp3(tmp_dir, gap_ms))
            part_paths.append(part_path)
            spoken_records.append({"speaker": sp, "chars": len(text), "text": text})
            prev_sp = sp
        if not part_paths:
            sys.exit("没有可合成的台词。")
        concat_mp3(part_paths, mp3_out)
        mp3_out.with_suffix(".fish-request.txt").write_text(
            "\n".join(f"{r['speaker']}：{r['text']}" for r in spoken_records),
            encoding="utf-8",
        )
        mp3_out.with_suffix(".fish-request.json").write_text(
            json.dumps(
                {
                    "model": model_name,
                    "mode": "line_concat",
                    "voice_ids": [mask_id(v) for v in ref],
                    "turn_count": len(lines),
                    "dad_turns": sum(s == "爸爸" for s, _ in lines),
                    "kid_turns": sum(s == "孩子" for s, _ in lines),
                    "pause_same_ms": same_ms,
                    "pause_switch_ms": switch_ms,
                    "turns": spoken_records,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    finally:
        # 保留 line_parts 下的单句片段，便于诊断某个角色或某句是否走样。
        pass


def synth_fish(lines, mp3_out):
    """Fish Audio 云端：单次生成整段双人对话，直接落 mp3。"""
    try:
        import requests
    except ImportError:
        sys.exit("缺 requests：在 VoxCPM 的 venv 里跑  pip install requests")
    key = os.environ.get("FISH_API_KEY", "").strip()
    ref = [os.environ.get("FISH_VOICE_ID_DAD", "").strip(),
           os.environ.get("FISH_VOICE_ID_KID", "").strip()]
    if not key:
        sys.exit("没填 FISH_API_KEY（在 tts/.env 里填）。")
    if not all(ref):
        sys.exit("没填 voice id（tts/.env 里 FISH_VOICE_ID_DAD / FISH_VOICE_ID_KID）。")
    model_name = os.environ.get("FISH_MODEL", FISH_MODEL)
    speaker_count = len({sp for sp, _ in lines})
    dialogue_mode = os.environ.get("FISH_DIALOGUE_MODE", "auto").strip().lower()
    allow_unsupported_multi = os.environ.get("FISH_ALLOW_UNSUPPORTED_MULTISPEAKER", "").strip().lower() == "true"
    if dialogue_mode in {"line", "line_concat", "single_concat"}:
        session = requests.Session()
        print(f"Fish（{model_name}）逐句单 voice_id 生成后拼接…（保底防串声）", flush=True)
        synth_fish_line_concat(session, key, model_name, lines, ref, mp3_out)
        return
    if speaker_count > 1 and model_name != "s2-pro" and dialogue_mode == "auto":
        session = requests.Session()
        print(f"Fish（{model_name}）非官方稳定多说话人路径，自动改用逐句单 voice_id 拼接…", flush=True)
        synth_fish_line_concat(session, key, model_name, lines, ref, mp3_out)
        return
    if speaker_count > 1 and model_name != "s2-pro" and not allow_unsupported_multi:
        sys.exit(
            f"Fish 官方仅标注 s2-pro 支持多说话人 dialogue；当前 FISH_MODEL={model_name!r}。\n"
            "为避免 speaker 串声，双人对话请改用 FISH_MODEL=s2-pro；"
            "若只是做不稳定实验，可临时设 FISH_ALLOW_UNSUPPORTED_MULTISPEAKER=true。"
        )
    text = build_fish_script(lines)
    max_chars = int(os.environ.get("FISH_CHUNK_MAX_CHARS", str(FISH_CHUNK_MAX_CHARS)))
    line_chunks = chunk_fish_lines(lines, max_chars) if len(text) > max_chars else [lines]
    chunk_records = [(chunk_lines, build_fish_script(chunk_lines), None) for chunk_lines in line_chunks]
    write_fish_debug(mp3_out, lines, text, ref, model_name, chunk_records)

    session = requests.Session()
    if len(line_chunks) == 1:
        print(f"Fish（{model_name}）单次生成整段双人对话…（不拼接）", flush=True)
        request_fish_audio(session, key, model_name, fish_payload(text, ref, model_name), mp3_out)
        return

    print(f"Fish（{model_name}）分 {len(line_chunks)} 段生成双人对话，再拼接，降低 speaker 漂移风险…", flush=True)
    part_paths = []
    tmp_dir = mp3_out.parent / f"{mp3_out.stem}.parts"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        for idx, chunk_lines in enumerate(line_chunks, 1):
            chunk_text = build_fish_script(chunk_lines)
            part_path = tmp_dir / f"{idx:02d}.mp3"
            print(f"  · Fish 段 {idx}/{len(line_chunks)}：{len(chunk_lines)} 句，{len(chunk_text)} 字", flush=True)
            request_fish_audio(session, key, model_name, fish_payload(chunk_text, ref, model_name), part_path)
            part_paths.append(part_path)
        concat_mp3(part_paths, mp3_out)
    finally:
        for part in part_paths:
            part.unlink(missing_ok=True)
        try:
            tmp_dir.rmdir()
        except OSError:
            pass


def synth_minimax(lines, mp3_out):
    """MiniMax 云端：HTTP T2A 单 voice_id 逐句生成，再拼接成双人对话。"""
    try:
        import requests
    except ImportError:
        sys.exit("缺 requests：在 VoxCPM 的 venv 里跑  pip install requests")
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not key:
        sys.exit("没填 MINIMAX_API_KEY（在 tts/.env 里填）。")
    model_name = os.environ.get("MINIMAX_MODEL", MINIMAX_MODEL).strip() or MINIMAX_MODEL
    endpoints = minimax_endpoint_candidates()
    active_endpoint_idx = 0
    voice_ids = {
        "爸爸": os.environ.get("MINIMAX_VOICE_ID_DAD", MINIMAX_VOICE_ID_DAD).strip() or MINIMAX_VOICE_ID_DAD,
        "孩子": os.environ.get("MINIMAX_VOICE_ID_KID", MINIMAX_VOICE_ID_KID).strip() or MINIMAX_VOICE_ID_KID,
    }
    same_ms = int(os.environ.get("MINIMAX_PAUSE_SAME_MS", str(MINIMAX_PAUSE_SAME_MS)))
    switch_ms = int(os.environ.get("MINIMAX_PAUSE_SWITCH_MS", str(MINIMAX_PAUSE_SWITCH_MS)))

    session = requests.Session()
    tmp_dir = mp3_out.parent / f"{mp3_out.stem}.line_parts"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    part_paths = []
    records = []
    prev_sp = None

    print(f"MiniMax（{model_name}）逐句双 voice_id 生成后拼接…", flush=True)
    for idx, (sp, raw) in enumerate(lines, 1):
        _, line_controls, line_extras = minimax_line_controls(raw, sp)
        text = build_minimax_turn_text(raw, sp)
        if not text:
            continue
        part_path = tmp_dir / f"{idx:02d}_{sp}.mp3"
        payload = minimax_payload(text, voice_ids[sp], model_name, sp, line_controls, line_extras)
        print(f"  · MiniMax 单句 {idx}/{len(lines)}：{sp}，{len(text)} 字", flush=True)
        active_endpoint_idx = request_minimax_audio_with_fallback(
            session, key, endpoints, payload, part_path, active_endpoint_idx
        )
        if prev_sp is not None:
            gap_ms = switch_ms if sp != prev_sp else same_ms
            part_paths.append(ensure_silence_mp3(tmp_dir, gap_ms))
        part_paths.append(part_path)
        records.append({
            "speaker": sp,
            "chars": len(text),
            "voice_setting": payload.get("voice_setting"),
            "voice_modify": payload.get("voice_modify"),
            "timbre_weights": payload.get("timbre_weights"),
            "text": text,
        })
        prev_sp = sp

    if not part_paths:
        sys.exit("没有可合成的台词。")
    concat_mp3(part_paths, mp3_out, reencode=True)
    mp3_out.with_suffix(".minimax-request.txt").write_text(
        "\n".join(f"{r['speaker']}：{r['text']}" for r in records),
        encoding="utf-8",
    )
    mp3_out.with_suffix(".minimax-request.json").write_text(
        json.dumps(
            {
                "model": model_name,
                "endpoint": endpoints[active_endpoint_idx],
                "endpoint_candidates": endpoints,
                "mode": "line_concat",
                "voice_ids": {sp: mask_id(v) for sp, v in voice_ids.items()},
                "payload_features": {
                    "text_pause_tag": "<#x#>",
                    "paragraph_marker": "\\n",
                    "native_tags": sorted(MINIMAX_NATIVE_TAGS),
                    "pronunciation_dict": ["Pando/(pan1)(duo1)", "MiniMax/(mi2)(ni3)(mai4)(ke4)(si1)"],
                    "language_boost": os.environ.get("MINIMAX_LANGUAGE_BOOST", "Chinese").strip(),
                    "subtitle_enable": os.environ.get("MINIMAX_SUBTITLE_ENABLE", "").strip().lower() == "true",
                    "subtitle_type": os.environ.get("MINIMAX_SUBTITLE_TYPE", "sentence").strip(),
                },
                "turn_count": len(lines),
                "dad_turns": sum(s == "爸爸" for s, _ in lines),
                "kid_turns": sum(s == "孩子" for s, _ in lines),
                "pause_same_ms": same_ms,
                "pause_switch_ms": switch_ms,
                "turns": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main():
    load_env_file()
    backend = os.environ.get("HEYTODAY_TTS_BACKEND", "voxcpm").strip().lower()

    episode = pick_episode()
    lines = parse_dialogue(episode)
    print(f"后端：{backend}", flush=True)
    print(f"稿子：{episode.name}", flush=True)
    print(f"台词：{len(lines)} 句（爸爸 {sum(s=='爸爸' for s,_ in lines)} / 孩子 {sum(s=='孩子' for s,_ in lines)}）", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = episode.stem.replace("_小学档", "")
    # 非默认后端输出加后缀，方便和 voxcpm 版 A/B（不互相覆盖）
    suffix = "" if backend == "voxcpm" else f".{backend}"
    mp3_out = OUT_DIR / f"{stem}{suffix}.mp3"

    # ---- 云端后端：Fish 可走原生多说话人；MiniMax 当前走逐 turn 可控拼接 ----
    if backend == "fish":
        synth_fish(lines, mp3_out)
        print(f"\n完成 → {mp3_out}\n拷到手机即可播放。", flush=True)
        return
    if backend == "minimax":
        synth_minimax(lines, mp3_out)
        print(f"\n完成 → {mp3_out}\n拷到手机即可播放。", flush=True)
        return
    if backend == "moss":
        sys.exit("moss 后端待接入（Stage C：本地 MOSS-TTSD）。先用 fish 验听感。")
    if backend != "voxcpm":
        sys.exit(f"未知后端 {backend!r}（可选 voxcpm / fish / minimax / moss）。")

    # ---- voxcpm（现状：逐句锚点克隆 + 拼接；本机退路 / 默认）----
    ffmpeg = find_ffmpeg()
    print("加载 VoxCPM2（首次约几十秒）…", flush=True)
    from voxcpm import VoxCPM
    model = VoxCPM.from_pretrained(HF_MODEL_ID, load_denoiser=False,
                                   device="cuda", optimize=False)
    sr = model.tts_model.sample_rate
    print(f"模型就绪，采样率 {sr} Hz。", flush=True)

    anchors = ensure_anchors(model, sr)

    segments = []
    prev = None
    for i, (sp, raw) in enumerate(lines, 1):
        control, spoken = build_control(sp, raw)
        if not spoken:
            continue
        if prev is not None:
            gap = PAUSE_SWITCH if sp != prev else PAUSE_SAME
            segments.append(np.zeros(int(sr * gap), dtype=np.float32))
        use_ctrl = USE_PER_LINE_CONTROL and control
        text = f"({control}){spoken}" if use_ctrl else spoken
        preview = spoken[:16] + ("…" if len(spoken) > 16 else "")
        print(f"[{i}/{len(lines)}] {sp}{('〔'+control+'〕') if use_ctrl else ''}: {preview}", flush=True)
        gen_kwargs = dict(reference_wav_path=anchors[sp],
                          cfg_value=CFG_VALUE, inference_timesteps=INFERENCE_TIMESTEPS)
        prompt_text = (ANCHOR_TRANSCRIPT.get(sp) or "").strip()
        if prompt_text:                          # 有朗读文本 → 极致克隆，保真最高
            gen_kwargs.update(prompt_wav_path=anchors[sp], prompt_text=prompt_text)
        audio = model.generate(text=text, **gen_kwargs)
        segments.append(np.asarray(audio, dtype=np.float32))
        prev = sp

    track = np.concatenate(segments)
    peak = float(np.max(np.abs(track))) if track.size else 0.0
    if peak > 0:
        track = (track / peak * 0.97).astype(np.float32)   # 整段统一峰值，音量一致

    wav_tmp = OUT_DIR / f"{stem}.tmp.wav"
    sf.write(str(wav_tmp), track, sr)

    subprocess.run([ffmpeg, "-y", "-i", str(wav_tmp), "-ac", "1",
                    "-b:a", MP3_BITRATE, str(mp3_out)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wav_tmp.unlink(missing_ok=True)

    dur = len(track) / sr
    print(f"\n完成 → {mp3_out}", flush=True)
    print(f"时长 {int(dur//60)} 分 {int(dur%60)} 秒，拷到手机即可播放。", flush=True)


if __name__ == "__main__":
    main()
