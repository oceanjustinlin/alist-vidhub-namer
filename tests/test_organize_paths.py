import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "alist_vidhub_namer.py"
SPEC = importlib.util.spec_from_file_location("alist_vidhub_namer", SCRIPT_PATH)
NAMER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NAMER)

ROOT = "/Library/Incoming"


class OrganizeRelativePathTests(unittest.TestCase):
    def test_bare_name_is_a_direct_child(self):
        self.assertEqual(
            NAMER.resolve_organize_relative_path(ROOT, "Inception (2010) {tmdb-27205}"),
            (ROOT, "Inception (2010) {tmdb-27205}",
             ROOT + "/Inception (2010) {tmdb-27205}"),
        )

    def test_relative_path_addresses_a_nested_folder(self):
        self.assertEqual(
            NAMER.resolve_organize_relative_path(ROOT, "Staging/2024/Inception"),
            (ROOT + "/Staging/2024", "Inception",
             ROOT + "/Staging/2024/Inception"),
        )

    def test_traversal_and_absolute_values_are_refused(self):
        for value in ["..", "../sibling", "Staging/../../etc", "/etc/passwd",
                      "Staging/./Inception", "", "Staging//Inception"]:
            with self.subTest(value=value):
                with self.assertRaises(NAMER.ToolError):
                    NAMER.resolve_organize_relative_path(ROOT, value)

    def test_resolved_path_never_escapes_the_root(self):
        for value in ["Staging/2024/Inception", "Inception"]:
            _, _, full = NAMER.resolve_organize_relative_path(ROOT, value)
            self.assertTrue(NAMER.path_is_within(ROOT, full))


class OrganizePlanValidationTests(unittest.TestCase):
    """A plan whose sources nest inside one another cannot be applied safely:
    moving the outer folder carries the inner one along, so the second move
    finds nothing at the path it recorded."""

    @staticmethod
    def _plan(entries, destination="Movies"):
        destination_path = ROOT + "/" + destination
        return {
            "schema_version": NAMER.SCHEMA_VERSION,
            "plan_id": "test",
            "created_at": "2026-01-01T00:00:00+00:00",
            "plan_kind": "organize_move",
            "alist_url": "http://localhost:5244",
            "alist_version": "v3.61.0",
            "root_path": ROOT,
            "destination_name": destination,
            "destination_path": destination_path,
            "create_destination": True,
            "writable": True,
            "providers": ["local"],
            "folder_count": len(entries),
            "entries": [
                {
                    "name": name,
                    "source_dir": source_dir,
                    "source_path": source_dir + "/" + name,
                    "target_dir": destination_path,
                    "target_path": destination_path + "/" + name,
                }
                for source_dir, name in entries
            ],
        }

    def test_accepts_nested_sources(self):
        NAMER.validate_organize_plan(
            self._plan([(ROOT, "Inception"), (ROOT + "/Staging/2024", "Arrival")])
        )

    def test_rejects_overlapping_sources(self):
        plan = self._plan([(ROOT, "Staging"), (ROOT + "/Staging", "Arrival")])
        with self.assertRaises(NAMER.ToolError):
            NAMER.validate_organize_plan(plan)

    def test_rejects_duplicate_target_names_from_different_sources(self):
        plan = self._plan([(ROOT + "/A", "Arrival"), (ROOT + "/B", "Arrival")])
        with self.assertRaises(NAMER.ToolError):
            NAMER.validate_organize_plan(plan)

    def test_rejects_source_outside_root(self):
        plan = self._plan([("/Elsewhere", "Arrival")])
        with self.assertRaises(NAMER.ToolError):
            NAMER.validate_organize_plan(plan)


class SeasonWrapPlanValidationTests(unittest.TestCase):
    """season-wrap-apply moves whatever the plan file names, so the SxxEyy and
    season checks have to live in the validator it runs against that file --
    not only in the plan command that first wrote it."""

    SHOW = "/Library/TV Shows/Breaking Bad (2008) {tmdb-1396}"

    @classmethod
    def _plan(cls, names, season=1):
        folder = "Season {:02d}".format(season)
        destination = cls.SHOW + "/" + folder
        return {
            "schema_version": NAMER.SCHEMA_VERSION,
            "plan_kind": "season_wrap",
            "root_path": cls.SHOW,
            "season": season,
            "season_folder": folder,
            "destination_path": destination,
            "file_count": len(names),
            "entries": [
                {
                    "name": name,
                    "source_path": cls.SHOW + "/" + name,
                    "target_path": destination + "/" + name,
                }
                for name in names
            ],
        }

    def test_accepts_episodes_of_the_planned_season(self):
        NAMER.validate_season_wrap_plan(self._plan([
            "Breaking.Bad.S01E01.Pilot.1080p.mkv",
            "Breaking.Bad.S01E01.Pilot.1080p.zh.srt",
        ]))

    def test_rejects_an_episode_from_another_season(self):
        with self.assertRaises(NAMER.ToolError):
            NAMER.validate_season_wrap_plan(
                self._plan(["Breaking.Bad.S05E14.Ozymandias.1080p.mkv"])
            )

    def test_rejects_a_file_with_no_episode_marker(self):
        for name in ["poster.jpg", "Some.Movie.2019.1080p.mkv"]:
            with self.subTest(name=name):
                with self.assertRaises(NAMER.ToolError):
                    NAMER.validate_season_wrap_plan(self._plan([name]))

    def test_rejects_a_destination_outside_the_series_folder(self):
        plan = self._plan(["Breaking.Bad.S01E01.Pilot.1080p.mkv"])
        plan["destination_path"] = "/Library/TV Shows/Season 01"
        with self.assertRaises(NAMER.ToolError):
            NAMER.validate_season_wrap_plan(plan)


if __name__ == "__main__":
    unittest.main()
