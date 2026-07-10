"""手动运行 SenseVoice 音频评估；只在生成后、人工复听前调用。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from audio_review import review_episode


def main() -> None:
    parser = argparse.ArgumentParser(
        description="对 MiniMax line_parts 做 SenseVoice ASR + 情绪预检"
    )
    parser.add_argument("request_json", type=Path, help="*.minimax-request.json 路径")
    parser.add_argument("--device", help="默认自动选择 cuda:0 或 cpu")
    parser.add_argument("--round", type=int, default=1, help="评估轮次，默认 1")
    parser.add_argument(
        "--model", default="iic/SenseVoiceSmall", help="SenseVoice 模型标识"
    )
    args = parser.parse_args()

    result = review_episode(
        args.request_json,
        model_name=args.model,
        device=args.device,
        round_number=args.round,
    )
    print("SenseVoice 手工预检完成")
    print(f"高风险 turn：{result['review_required']}")
    print(f"原始记录：{result['raw_path']}")
    print(f"复听排序：{result['review_path']}")
    print(f"小修建议：{result['fix_plan_path']}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
