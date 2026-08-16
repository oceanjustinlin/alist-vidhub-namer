import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "alist_vidhub_namer.py"
SPEC = importlib.util.spec_from_file_location("alist_vidhub_namer", SCRIPT_PATH)
NAMER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NAMER)


class FilenameParsingTests(unittest.TestCase):
    def test_movie_suffix_drops_chinese_subtitle_and_release_group_notes(self):
        parsed = NAMER.parse_video_name(
            "Triangle.of.Sadness.2022.{tmdb-497828}.1080p.中英字幕.亿万同人字幕组.mkv"
        )

        self.assertEqual(parsed["suffix"], "{tmdb-497828}.1080p")
        self.assertEqual(
            NAMER.build_name(parsed),
            "Triangle.of.Sadness.2022.{tmdb-497828}.1080p.mkv",
        )

    def test_suffix_keeps_ascii_technical_tag_joined_to_chinese_note(self):
        self.assertEqual(NAMER.clean_suffix("1080p中英字幕.WEB-DL"), "1080p.WEB-DL")

    def test_suffix_preserves_non_chinese_tags(self):
        self.assertEqual(
            NAMER.clean_suffix("{tmdb-497828}.1080p.WEB-DL.x265.DDP5.1"),
            "{tmdb-497828}.1080p.WEB-DL.x265.DDP5.1",
        )


if __name__ == "__main__":
    unittest.main()
