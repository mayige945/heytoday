import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tts"))

import audio_review  # noqa: E402
from audio_review import (  # noqa: E402
    character_error_rate,
    make_review_record,
    parse_sensevoice_text,
)


class SenseVoiceTextTests(unittest.TestCase):
    def test_extracts_metadata_and_transcript(self):
        parsed = parse_sensevoice_text(
            "<|zh|><|HAPPY|><|Speech|><|withitn|>等等，差这么多？"
        )

        self.assertEqual(parsed["language"], "zh")
        self.assertEqual(parsed["emotion"], "HAPPY")
        self.assertEqual(parsed["event"], "Speech")
        self.assertEqual(parsed["transcript"], "等等，差这么多？")


class ReviewRecordTests(unittest.TestCase):
    def test_character_error_rate_ignores_tts_control_markers_and_punctuation(self):
        self.assertEqual(
            character_error_rate("先听一个数字。<#0.25#>", "先听一个数字"),
            0.0,
        )

    def test_character_error_rate_treats_chinese_and_arabic_numbers_as_equal(self):
        self.assertEqual(
            character_error_rate("一千四百万到两千万种", "1400万到2000万种"),
            0.0,
        )

    def test_marks_high_cer_and_emotion_mismatch_for_human_review(self):
        record = make_review_record(
            line_id=12,
            speaker="孩子",
            tts_text="哇，这棵树自己就是一片森林？",
            sensevoice_raw="<|zh|><|NEUTRAL|><|Speech|><|withitn|>哇，这棵树就是森林",
            planned_emotion="happy",
        )

        self.assertGreater(record["cer"], 0.10)
        self.assertIn("asr_mismatch", record["flags"])
        self.assertIn("emotion_mismatch", record["flags"])
        self.assertEqual(record["decision"]["status"], "needs_human")
        self.assertGreaterEqual(record["priority"], 100)

    def test_does_not_infer_an_emotion_mismatch_without_a_director_intent(self):
        record = make_review_record(
            line_id=2,
            speaker="孩子",
            tts_text="等等，差这么多？",
            sensevoice_raw="<|zh|><|ANGRY|><|Speech|><|withitn|>等等，差这么多",
            planned_emotion=None,
        )

        self.assertNotIn("emotion_mismatch", record["flags"])


class EpisodeReviewTests(unittest.TestCase):
    def test_writes_auditable_records_and_sorts_human_review_queue(self):
        class FakeSenseVoice:
            def generate(self, *, input, language, use_itn):
                if Path(input).name.startswith("01_"):
                    return [
                        {"text": "<|zh|><|NEUTRAL|><|Speech|><|withitn|>你好"}
                    ]
                return [{"text": "<|zh|><|HAPPY|><|Speech|><|withitn|>这是"}]

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            request_path = output_dir / "episode.minimax-request.json"
            request_path.write_text(
                json.dumps(
                    {
                        "turns": [
                            {
                                "speaker": "爸爸",
                                "text": "你好。",
                                "voice_setting": {"emotion": "calm"},
                            },
                            {
                                "speaker": "孩子",
                                "text": "这是测试。",
                                "voice_setting": {},
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            line_parts = output_dir / "episode.line_parts"
            line_parts.mkdir()
            (line_parts / "01_爸爸.mp3").touch()
            (line_parts / "02_孩子.mp3").touch()

            with patch("audio_review.load_sensevoice", return_value=FakeSenseVoice()):
                result = audio_review.review_episode(request_path, device="cpu")

            raw_records = [
                json.loads(line)
                for line in Path(result["raw_path"]).read_text(encoding="utf-8").splitlines()
            ]
            fix_plan = json.loads(
                Path(result["fix_plan_path"]).read_text(encoding="utf-8")
            )
            review_rows = Path(result["review_path"]).read_text(
                encoding="utf-8-sig"
            ).splitlines()

            self.assertEqual(len(raw_records), 2)
            self.assertEqual(raw_records[0]["detectors"][0]["name"], "SenseVoiceSmall")
            self.assertEqual(result["review_required"], 1)
            self.assertEqual(fix_plan["items"][0]["line_id"], 2)
            self.assertTrue(review_rows[1].startswith("2,"))

    def test_keeps_the_review_queue_when_one_turn_inference_fails(self):
        class PartlyBrokenSenseVoice:
            def generate(self, *, input, language, use_itn):
                if Path(input).name.startswith("02_"):
                    raise RuntimeError("broken mp3")
                return [{"text": "<|zh|><|NEUTRAL|><|Speech|><|withitn|>你好"}]

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            request_path = output_dir / "episode.minimax-request.json"
            request_path.write_text(
                json.dumps(
                    {
                        "turns": [
                            {"speaker": "爸爸", "text": "你好", "voice_setting": {}},
                            {"speaker": "孩子", "text": "测试", "voice_setting": {}},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            line_parts = output_dir / "episode.line_parts"
            line_parts.mkdir()
            (line_parts / "01_爸爸.mp3").touch()
            (line_parts / "02_孩子.mp3").touch()

            with patch(
                "audio_review.load_sensevoice", return_value=PartlyBrokenSenseVoice()
            ):
                result = audio_review.review_episode(request_path, device="cpu")

            raw_records = [
                json.loads(line)
                for line in Path(result["raw_path"]).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(result["review_required"], 1)
            self.assertEqual(raw_records[1]["decision"]["reason"], "assessment_error")
            self.assertEqual(raw_records[1]["detectors"][0]["error"], "broken mp3")


if __name__ == "__main__":
    unittest.main()
