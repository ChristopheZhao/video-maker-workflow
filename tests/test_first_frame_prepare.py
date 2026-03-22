from __future__ import annotations

import unittest

from video_workflow_service.workflow.first_frame_prepare import _aspect_ratio_to_image_size


class FirstFramePrepareTestCase(unittest.TestCase):
    def test_aspect_ratio_sizes_meet_seedream_minimum_pixel_requirement(self) -> None:
        self.assertEqual(_aspect_ratio_to_image_size("9:16"), "1440x2560")
        self.assertEqual(_aspect_ratio_to_image_size("16:9"), "2560x1440")
        self.assertEqual(_aspect_ratio_to_image_size("1:1"), "2048x2048")

    def test_unknown_aspect_ratio_falls_back_to_supported_vertical_size(self) -> None:
        self.assertEqual(_aspect_ratio_to_image_size(""), "1440x2560")


if __name__ == "__main__":
    unittest.main()
