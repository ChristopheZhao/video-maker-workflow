from __future__ import annotations

import unittest

from video_workflow_service.workflow.contracts import LanguageDetectInput
from video_workflow_service.workflow.language_detect import detect_language_step


class _NoopTraceLogger:
    def append(self, project_id: str, **kwargs) -> None:
        return None


class LanguageDetectTestCase(unittest.TestCase):
    def test_detect_language_prefers_chinese_for_chinese_prompt(self) -> None:
        result = detect_language_step(
            LanguageDetectInput(raw_prompt="一个古装女人站在药房里，慢慢说道：“他们都以为我只是个医娘子。”"),
            trace_logger=_NoopTraceLogger(),
            project_id="prj_test",
        )

        self.assertEqual(result.input_language, "zh")
        self.assertEqual(result.dialogue_language, "zh")
        self.assertEqual(result.audio_language, "zh")
        self.assertFalse(result.mixed_language)

    def test_detect_language_prefers_english_for_english_prompt(self) -> None:
        result = detect_language_step(
            LanguageDetectInput(
                raw_prompt='A woman stands in an apothecary and says softly: "They think I\'m just a healer\'s wife."'
            ),
            trace_logger=_NoopTraceLogger(),
            project_id="prj_test",
        )

        self.assertEqual(result.input_language, "en")
        self.assertEqual(result.dialogue_language, "en")
        self.assertEqual(result.audio_language, "en")
        self.assertFalse(result.mixed_language)

    def test_detect_language_marks_mixed_language_prompt(self) -> None:
        result = detect_language_step(
            LanguageDetectInput(
                raw_prompt='一个古装女人站在药房里，慢慢说道: "They think I\'m just a healer\'s wife."'
            ),
            trace_logger=_NoopTraceLogger(),
            project_id="prj_test",
        )

        self.assertEqual(result.input_language, "zh")
        self.assertEqual(result.dialogue_language, "en")
        self.assertEqual(result.audio_language, "en")
        self.assertTrue(result.mixed_language)


if __name__ == "__main__":
    unittest.main()
