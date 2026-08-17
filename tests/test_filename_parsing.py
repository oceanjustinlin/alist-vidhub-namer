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

    def test_suffix_drops_latin_language_markers(self):
        self.assertEqual(
            NAMER.clean_suffix("1080p.WEB.h264-cakes.chs.eng"),
            "1080p.WEB.h264-cakes",
        )
        self.assertEqual(
            NAMER.clean_suffix("{tmdb-1}.1080p.BluRay.x264.AAC.CHS"),
            "{tmdb-1}.1080p.BluRay.x264.AAC",
        )

    def test_suffix_canonicalizes_tag_spelling_but_not_release_groups(self):
        self.assertEqual(
            NAMER.clean_suffix("1080p.web.h264-cakes"), "1080p.WEB.h264-cakes"
        )
        self.assertEqual(
            NAMER.clean_suffix("{tmdb-4951}.1080p.BD中英双字"),
            "{tmdb-4951}.1080p.BluRay",
        )
        self.assertEqual(
            NAMER.clean_suffix("1080p.iP.WEB-DL.AAC2.0.H.264-playWEB"),
            "1080p.iP.WEB-DL.AAC2.0.H.264-playWEB",
        )


class SuffixWhitelistTests(unittest.TestCase):
    def test_drops_site_and_channel_watermarks(self):
        self.assertEqual(
            NAMER.clean_suffix("1080p.WEB.h264-ETHEL[EZTVx.to]"),
            "1080p.WEB.h264-ETHEL",
        )
        self.assertEqual(NAMER.clean_suffix("{tmdb-1}.SW-115"), "{tmdb-1}")
        self.assertEqual(NAMER.clean_suffix("1080p.CHS-HAN@CHAOSPACE"), "1080p")

    def test_drops_vague_quality_word_beside_a_resolution(self):
        self.assertEqual(NAMER.clean_suffix("中英字幕.1080p.HD.@TheTaoSong"), "1080p")
        # With no resolution to duplicate, HD is the only quality signal: keep it.
        self.assertEqual(NAMER.clean_suffix("HD.x264-NTb"), "HD.x264-NTb")

    def test_unknown_technical_token_is_reported_not_stripped(self):
        tokens, unknown = NAMER.suffix_tokens("1080p.WEB.h264-cakes.SomeJunkToken")
        self.assertEqual(".".join(tokens), "1080p.WEB.h264-cakes.SomeJunkToken")
        self.assertEqual(unknown, ["SomeJunkToken"])

    def test_episode_title_words_are_not_whitelist_violations(self):
        tokens, unknown = NAMER.suffix_tokens(
            "Boo.to.a.Goose.1080p.iP.WEB-DL.AAC2.0.H.264-playWEB.chs.eng"
        )
        self.assertEqual(unknown, [])
        self.assertEqual(
            ".".join(tokens), "Boo.to.a.Goose.1080p.iP.WEB-DL.AAC2.0.H.264-playWEB"
        )

    def test_unknown_token_forces_review(self):
        parsed = NAMER.parse_video_name("Show.S01E01.1080p.WEB.x264.SomeJunkToken.mkv")
        self.assertEqual(parsed["status"], "review")
        self.assertTrue(
            any(r.startswith("unrecognized_tail_token:") for r in parsed["reason"])
        )


class EpisodeTitleTests(unittest.TestCase):
    """The episode title is a required field; see references/naming.md."""

    @staticmethod
    def _entry(name, season, episode):
        return {
            "old_name": name, "directory": "/x", "media_type": "tv",
            "season": season, "episode": episode,
        }

    def test_title_is_added_when_the_source_has_none(self):
        self.assertEqual(
            NAMER.build_tmdb_suggestion(
                self._entry("Chernobyl.S01E01.mp4", 1, 1),
                {"tmdb_id": 87108, "title": "Chernobyl"},
                "1:23:45",
            ),
            "Chernobyl.S01E01.1.23.45.mp4",
        )

    def test_technical_tags_survive_a_added_title(self):
        self.assertEqual(
            NAMER.build_tmdb_suggestion(
                self._entry("The.OA.S01E01.1080p-YYeTs.mp4", 1, 1),
                {"tmdb_id": 69061, "title": "The OA"},
                "Homecoming",
            ),
            "The.OA.S01E01.Homecoming.1080p-YYeTs.mp4",
        )

    def test_matching_source_title_is_not_duplicated(self):
        # "Demon 79" ends in a bare number, which a token-wise scan mistakes
        # for a technical tag and leaves behind.
        self.assertEqual(
            NAMER.build_tmdb_suggestion(
                self._entry("Black.Mirror.S06E05.Demon.79.mp4", 6, 5),
                {"tmdb_id": 42009, "title": "Black Mirror"},
                "Demon 79",
            ),
            "Black.Mirror.S06E05.Demon.79.mp4",
        )
        self.assertEqual(
            NAMER.build_tmdb_suggestion(
                self._entry("Barry.S04E01.yikes.1080p.x264-NTb.mp4", 4, 1),
                {"tmdb_id": 73107, "title": "Barry"},
                "yikes",
            ),
            "Barry.S04E01.yikes.1080p.x264-NTb.mp4",
        )

    def test_localized_source_title_is_replaced(self):
        self.assertEqual(
            NAMER.build_tmdb_suggestion(
                self._entry("黑镜.S06E01.琼糟透了.mp4", 6, 1),
                {"tmdb_id": 42009, "title": "Black Mirror"},
                "Joan Is Awful",
            ),
            "Black.Mirror.S06E01.Joan.Is.Awful.mp4",
        )

    def test_missing_title_leaves_the_name_otherwise_intact(self):
        self.assertEqual(
            NAMER.build_tmdb_suggestion(
                self._entry("Show.S01E09.1080p.WEB.mp4", 1, 9),
                {"tmdb_id": 1, "title": "Show"},
                None,
            ),
            "Show.S01E09.1080p.WEB.mp4",
        )


class ManualTargetValidationTests(unittest.TestCase):
    def test_accepts_canonical_target(self):
        NAMER.validate_manual_target("x.mp4", "Rain.Dogs.S01E01.1080p.WEB.h264-cakes.mp4")

    def test_rejects_cjk_in_video_filename(self):
        with self.assertRaises(NAMER.ToolError):
            NAMER.validate_manual_target("x.mp4", "黑镜.S06E01.琼糟透了.mp4")

    def test_rejects_embedded_subtitle_marker(self):
        with self.assertRaises(NAMER.ToolError):
            NAMER.validate_manual_target(
                "x.mp4", "Rain.Dogs.S01E01.1080p.WEB.h264-cakes.chs.eng.mp4"
            )


if __name__ == "__main__":
    unittest.main()
