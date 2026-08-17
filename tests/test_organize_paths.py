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


if __name__ == "__main__":
    unittest.main()
