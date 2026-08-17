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

    def test_embedded_digit_in_a_real_title_does_not_flag_the_rest_as_unknown(self):
        # "Chapter 1: Angel of Death" (The OA S02E01) — a bare number appearing
        # mid-title used to be mistaken for the start of the technical region,
        # flagging every later title word ("Angel", "of", "Death") as unknown.
        tokens, unknown = NAMER.suffix_tokens(
            "Chapter.1.Angel.of.Death.1080p-YYeTs"
        )
        self.assertEqual(unknown, [])
        self.assertEqual(".".join(tokens), "Chapter.1.Angel.of.Death.1080p-YYeTs")

    def test_chained_audio_channel_digits_are_recognized(self):
        # "TrueHD.7.1" splits into three tokens on its own dots; the second
        # digit chains back to the codec through the first.
        tokens, unknown = NAMER.suffix_tokens("TrueHD.7.1.Atmos")
        self.assertEqual(unknown, [])
        self.assertEqual(".".join(tokens), "TrueHD.7.1.Atmos")

    def test_channel_digits_chain_through_codec_spellings_with_suffixes(self):
        # The codec immediately before the digits is not always a bare word:
        # "Atmos", "DD+5" and "DTS-X" all license the channel count that
        # follows, and missing any of them sends a common release to review.
        for tail in ["TrueHD.Atmos.7.1", "DD+5.1", "DTS-X.7.1", "DDP5.1.Atmos"]:
            with self.subTest(tail=tail):
                self.assertEqual(NAMER.suffix_tokens(tail)[1], [])

    def test_common_atmos_release_stays_ready(self):
        parsed = NAMER.parse_video_name(
            "Show.S01E01.1080p.BluRay.TrueHD.Atmos.7.1.x265-GRP.mkv"
        )
        self.assertEqual(parsed["status"], "ready")

    def test_bare_digit_without_a_preceding_codec_is_not_a_channel_count(self):
        tokens, unknown = NAMER.suffix_tokens("Halloween.3.AwesomeLand.WEB-HR")
        self.assertEqual(unknown, [])

    def test_bd_hr_style_source_tag_is_recognized(self):
        tokens, unknown = NAMER.suffix_tokens("BD-HR.AC3.1024X576.x264-YYeTs")
        self.assertEqual(unknown, [])

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


class GenericEpisodeTitleTests(unittest.TestCase):
    """Some limited series never get real episode titles in TMDB's own
    database; it fills the field with 'Episode 1', 'Episode 2', etc. That
    duplicates the SxxEyy key already in the filename, so it counts as absent."""

    def test_matches_generic_placeholder(self):
        for name in ["Episode 1", "episode 12", "Episode  7"]:
            with self.subTest(name=name):
                self.assertTrue(NAMER.GENERIC_EPISODE_TITLE_RE.match(name))

    def test_does_not_match_a_real_title(self):
        for name in ["Homecoming", "Episode One", "The Episode", "1:23:45"]:
            with self.subTest(name=name):
                self.assertFalse(NAMER.GENERIC_EPISODE_TITLE_RE.match(name))


class CurlyQuoteNormalizationTests(unittest.TestCase):
    """TMDB titles inconsistently use straight vs. typographic punctuation
    across shows and even within one show's own episode list; normalize to
    ASCII so the library does not mix styles."""

    def test_curly_apostrophe_becomes_straight(self):
        self.assertEqual(NAMER.safe_component("Mac’s Banging the Waitress"),
                         "Mac's.Banging.the.Waitress")

    def test_curly_double_quotes_are_stripped_like_straight_ones(self):
        self.assertEqual(NAMER.safe_component("The “Big” Deal"),
                         "The.Big.Deal")


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
