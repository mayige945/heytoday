"""手工音频评估的纯函数与 SenseVoice 执行入口。"""

from __future__ import annotations

import csv
import importlib.metadata
import json
import re
from pathlib import Path
from typing import Any


SENSEVOICE_TAG_RE = re.compile(r"<\|([^|>]+)\|>")
PAUSE_TAG_RE = re.compile(r"<#\d+(?:\.\d+)?#>")
CONTROL_WORD_RE = re.compile(r"\([^)]*\)|（[^）]*）")
KEEP_FOR_CER_RE = re.compile(r"[^\u4e00-\u9fffA-Za-z0-9]")
CHINESE_NUMBER_RE = re.compile(r"[零〇一二三四五六七八九两十百千万亿]+")
ARABIC_LARGE_NUMBER_RE = re.compile(r"(\d+)(万|亿)")
CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "两": 2,
}
CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10_000, "亿": 100_000_000}

EMOTION_GROUPS = {
    "happy": {"HAPPY", "SURPRISED"},
    "fearful": {"FEARFUL", "SAD", "ANGRY"},
    "calm": {"NEUTRAL", "CALM"},
}


def parse_sensevoice_text(raw_text: str) -> dict[str, str | None]:
    """拆出 SenseVoice 富文本中的语言、情绪、事件和转写正文。"""
    tags = SENSEVOICE_TAG_RE.findall(raw_text)
    transcript = SENSEVOICE_TAG_RE.sub("", raw_text).strip()
    return {
        "language": tags[0] if len(tags) > 0 else None,
        "emotion": tags[1].upper() if len(tags) > 1 else None,
        "event": tags[2] if len(tags) > 2 else None,
        "itn": tags[3] if len(tags) > 3 else None,
        "transcript": transcript,
    }


def chinese_number_to_int(value: str) -> int:
    """把常见中文整数转为阿拉伯数字，供 CER 消除格式差异。"""
    total = 0
    section = 0
    number = 0
    for char in value:
        if char in CHINESE_DIGITS:
            number = CHINESE_DIGITS[char]
            continue

        unit = CHINESE_UNITS[char]
        if unit < 10_000:
            section += (number or 1) * unit
        else:
            total += (section + number or 1) * unit
            section = 0
        number = 0
    return total + section + number


def normalize_numbers(text: str) -> str:
    def replace_arabic_large_number(match: re.Match[str]) -> str:
        multiplier = 10_000 if match.group(2) == "万" else 100_000_000
        return str(int(match.group(1)) * multiplier)

    text = ARABIC_LARGE_NUMBER_RE.sub(replace_arabic_large_number, text)
    return CHINESE_NUMBER_RE.sub(
        lambda match: str(chinese_number_to_int(match.group(0))), text
    )


def normalize_for_cer(text: str) -> str:
    without_controls = CONTROL_WORD_RE.sub("", PAUSE_TAG_RE.sub("", text))
    without_controls = normalize_numbers(without_controls)
    return KEEP_FOR_CER_RE.sub("", without_controls).lower()


def character_error_rate(expected: str, actual: str) -> float:
    """基于中文字符的 Levenshtein CER；TTS 停顿与标点不计入错误。"""
    reference = normalize_for_cer(expected)
    hypothesis = normalize_for_cer(actual)
    if not reference:
        return 0.0 if not hypothesis else 1.0

    previous = list(range(len(hypothesis) + 1))
    for index, reference_char in enumerate(reference, start=1):
        current = [index]
        for hypothesis_index, hypothesis_char in enumerate(hypothesis, start=1):
            current.append(
                min(
                    previous[hypothesis_index] + 1,
                    current[hypothesis_index - 1] + 1,
                    previous[hypothesis_index - 1]
                    + (reference_char != hypothesis_char),
                )
            )
        previous = current
    return previous[-1] / len(reference)


def expected_emotions(planned_emotion: str | None) -> list[str]:
    if not planned_emotion:
        return []
    return sorted(EMOTION_GROUPS.get(planned_emotion.lower(), set()))


def make_review_record(
    *,
    line_id: int,
    speaker: str,
    tts_text: str,
    sensevoice_raw: str,
    planned_emotion: str | None,
    cer_threshold: float = 0.10,
) -> dict[str, Any]:
    parsed = parse_sensevoice_text(sensevoice_raw)
    cer = character_error_rate(tts_text, parsed["transcript"] or "")
    expected = expected_emotions(planned_emotion)
    flags: list[str] = []

    if cer > cer_threshold:
        flags.append("asr_mismatch")
    if expected and parsed["emotion"] not in expected:
        flags.append("emotion_mismatch")

    priority = 0
    if "asr_mismatch" in flags:
        priority += 100
    if "emotion_mismatch" in flags:
        priority += 60

    return {
        "line_id": line_id,
        "speaker": speaker,
        "tts_text": tts_text,
        "asr_text": parsed["transcript"],
        "language": parsed["language"],
        "emotion": parsed["emotion"],
        "event": parsed["event"],
        "planned_emotion": planned_emotion,
        "expected_emotion_group": expected,
        "cer": round(cer, 4),
        "flags": flags,
        "priority": priority,
        "decision": {
            "status": "needs_human" if flags else "pass",
            "reason": "; ".join(flags) if flags else "asr_and_emotion_check_pass",
        },
    }


def make_unavailable_record(
    *,
    line_id: int,
    speaker: str,
    tts_text: str,
    planned_emotion: str | None,
    reason: str,
) -> dict[str, Any]:
    return {
        "line_id": line_id,
        "speaker": speaker,
        "tts_text": tts_text,
        "asr_text": None,
        "language": None,
        "emotion": None,
        "event": None,
        "planned_emotion": planned_emotion,
        "expected_emotion_group": expected_emotions(planned_emotion),
        "cer": None,
        "flags": [reason],
        "priority": 120,
        "decision": {"status": "needs_human", "reason": reason},
    }


def request_stem(request_path: Path) -> str:
    suffix = ".minimax-request.json"
    if not request_path.name.endswith(suffix):
        raise ValueError(f"请求记录必须以 {suffix} 结尾：{request_path}")
    return request_path.name[: -len(suffix)]


def line_part_path(line_parts_dir: Path, line_id: int, speaker: str) -> Path:
    return line_parts_dir / f"{line_id:02d}_{speaker}.mp3"


def suggested_actions(flags: list[str]) -> list[str]:
    actions: list[str] = []
    if "asr_mismatch" in flags:
        actions.append("核对错读位置；优先改 pronunciation_dict、专名写法或拆句后局部重生成")
    if "emotion_mismatch" in flags:
        actions.append("先改台词标点和口语节奏；必要时微调 emotion 或原生标签后局部重生成")
    return actions


def default_device() -> str:
    try:
        import torch

        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def load_sensevoice(model_name: str, device: str):
    try:
        from funasr import AutoModel
    except ImportError as exc:
        raise RuntimeError(
            "未安装 FunASR，无法执行手工评估。请在 VoxCPM venv 中安装 funasr。"
        ) from exc
    return AutoModel(model=model_name, device=device, disable_update=True)


def review_episode(
    request_path: Path,
    *,
    model_name: str = "iic/SenseVoiceSmall",
    device: str | None = None,
    round_number: int = 1,
) -> dict[str, Path | int]:
    """逐句运行 SenseVoice，输出原始结果、复听排序和小修建议。"""
    request_path = request_path.resolve()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    turns = request.get("turns")
    if not isinstance(turns, list) or not turns:
        raise ValueError(f"请求记录没有可评估的 turns：{request_path}")

    stem = request_stem(request_path)
    line_parts_dir = request_path.parent / f"{stem}.line_parts"
    if not line_parts_dir.is_dir():
        raise FileNotFoundError(f"找不到逐句音频目录：{line_parts_dir}")

    actual_device = device or default_device()
    model = load_sensevoice(model_name, actual_device)
    try:
        funasr_version = importlib.metadata.version("funasr")
    except importlib.metadata.PackageNotFoundError:
        funasr_version = "unknown"

    raw_records: list[dict[str, Any]] = []
    review_records: list[dict[str, Any]] = []
    fix_plan: list[dict[str, Any]] = []

    for line_id, turn in enumerate(turns, start=1):
        speaker = str(turn.get("speaker", "未知"))
        tts_text = str(turn.get("text", ""))
        audio_path = line_part_path(line_parts_dir, line_id, speaker)
        planned_emotion = (
            turn.get("voice_setting", {}).get("emotion")
            if isinstance(turn.get("voice_setting"), dict)
            else None
        )
        detector_error = None

        if not audio_path.is_file():
            record = make_unavailable_record(
                line_id=line_id,
                speaker=speaker,
                tts_text=tts_text,
                planned_emotion=planned_emotion,
                reason="missing_audio",
            )
            raw_output = None
        else:
            try:
                result = model.generate(
                    input=str(audio_path), language="auto", use_itn=True
                )
                raw_output = str(result[0].get("text", "")) if result else ""
                record = make_review_record(
                    line_id=line_id,
                    speaker=speaker,
                    tts_text=tts_text,
                    sensevoice_raw=raw_output,
                    planned_emotion=planned_emotion,
                )
            except Exception as exc:
                detector_error = str(exc)
                raw_output = None
                record = make_unavailable_record(
                    line_id=line_id,
                    speaker=speaker,
                    tts_text=tts_text,
                    planned_emotion=planned_emotion,
                    reason="assessment_error",
                )

        raw_records.append(
            {
                "run_id": f"{stem}_round{round_number}",
                "line_id": line_id,
                "speaker": speaker,
                "audio_path": str(audio_path),
                "tts_text": tts_text,
                "planned_cues": [planned_emotion] if planned_emotion else [],
                "expected_emotion_group": record["expected_emotion_group"],
                "detectors": [
                    {
                        "name": "SenseVoiceSmall",
                        "funasr_version": funasr_version,
                        "model": model_name,
                        "device": actual_device,
                        "output_type": "asr_ser_aed",
                        "raw_output": raw_output,
                        "error": detector_error,
                    }
                ],
                "decision": record["decision"],
            }
        )
        review_records.append(record)
        if record["flags"]:
            fix_plan.append(
                {
                    "line_id": line_id,
                    "speaker": speaker,
                    "problem": record["flags"],
                    "evidence": {
                        "tts_text": tts_text,
                        "asr_text": record["asr_text"],
                        "cer": record["cer"],
                        "planned_emotion": planned_emotion,
                        "detected_emotion": record["emotion"],
                    },
                    "actions": suggested_actions(record["flags"]),
                    "retry": 0,
                    "status": "needs_human_review",
                }
            )

    output_dir = request_path.parent
    raw_path = output_dir / f"{stem}.emotion_raw.jsonl"
    review_path = output_dir / f"{stem}.review_round{round_number}.csv"
    fix_plan_path = output_dir / f"{stem}.fix_plan_round{round_number}.json"

    with raw_path.open("w", encoding="utf-8") as handle:
        for record in raw_records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    csv_fields = [
        "line_id",
        "speaker",
        "tts_text",
        "asr_text",
        "language",
        "emotion",
        "planned_emotion",
        "expected_emotion_group",
        "cer",
        "flags",
        "priority",
        "decision_status",
        "decision_reason",
    ]
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields)
        writer.writeheader()
        for record in sorted(review_records, key=lambda item: item["priority"], reverse=True):
            writer.writerow(
                {
                    "line_id": record["line_id"],
                    "speaker": record["speaker"],
                    "tts_text": record["tts_text"],
                    "asr_text": record["asr_text"],
                    "language": record["language"],
                    "emotion": record["emotion"],
                    "planned_emotion": record["planned_emotion"],
                    "expected_emotion_group": ";".join(record["expected_emotion_group"]),
                    "cer": record["cer"],
                    "flags": ";".join(record["flags"]),
                    "priority": record["priority"],
                    "decision_status": record["decision"]["status"],
                    "decision_reason": record["decision"]["reason"],
                }
            )

    fix_plan_path.write_text(
        json.dumps(
            {
                "request_json": str(request_path),
                "round": round_number,
                "review_required": len(fix_plan),
                "items": fix_plan,
                "note": "自动结果只用于路由人工复听和提出局部建议，不单独决定通过。",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "raw_path": raw_path,
        "review_path": review_path,
        "fix_plan_path": fix_plan_path,
        "review_required": len(fix_plan),
    }
