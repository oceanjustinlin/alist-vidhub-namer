"""Mock-client coverage for the season wrap mutation path.

These exercise the parts no offline parsing test reaches: the preflight that
runs against a fresh listing, the automatic restore after a mid-run failure,
and the rollback conflict checks. The fake client records every call so a test
can assert that a refusal happened *before* anything was moved.
"""

import contextlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "alist_vidhub_namer.py"
SPEC = importlib.util.spec_from_file_location("alist_vidhub_namer", SCRIPT_PATH)
NAMER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NAMER)

SHOW = "/Library/TV Shows/Breaking Bad (2008) {tmdb-1396}"
SEASON_FOLDER = "Season 01"
DESTINATION = SHOW + "/" + SEASON_FOLDER
EPISODES = ["Breaking.Bad.S01E01.Pilot.1080p.mkv", "Breaking.Bad.S01E02.1080p.mkv"]


class FakeClient:
    """Stands in for AListClient. `fail_move_on` makes one move raise so the
    automatic-restore path can be driven without a server."""

    def __init__(self, root_names, base_url="http://localhost:5244",
                 fail_move_on=None, writable=True):
        self.dirs = {SHOW: list(root_names)}
        self.base_url = base_url
        self.fail_move_on = fail_move_on
        self.writable = writable
        self.calls = []

    def list_dir(self, path, refresh=False):
        if path not in self.dirs:
            raise NAMER.ToolError("no such directory: {}".format(path))
        self.calls.append(("list", path))
        return {
            "write": self.writable,
            "providers": ["local"],
            "content": [{"name": name, "is_dir": False} for name in self.dirs[path]],
        }

    def mkdir(self, path):
        self.calls.append(("mkdir", path))
        self.dirs.setdefault(path, [])

    def move(self, src_dir, dst_dir, names):
        self.calls.append(("move", src_dir, dst_dir, tuple(names)))
        for name in names:
            if name == self.fail_move_on:
                raise NAMER.ToolError("simulated move failure for {}".format(name))
            self.dirs[src_dir].remove(name)
            self.dirs.setdefault(dst_dir, []).append(name)

    @property
    def moves(self):
        return [call for call in self.calls if call[0] == "move"]


class Args:
    def __init__(self, **kwargs):
        self.timeout = 30
        self.interactive_auth = False
        self.move_delay = 0
        self.execute = True
        self.confirm_root = SHOW
        self.confirm_file_count = len(EPISODES)
        self.__dict__.update(kwargs)


class SeasonWrapApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.plan_path = self.tmp / "plan.json"
        self.journal_path = self.tmp / "journal.json"
        self.state_db = str(self.tmp / "absent-state.sqlite3")
        self.plan_path.write_text(json.dumps(self._plan()), encoding="utf-8")

    @staticmethod
    def _plan(names=EPISODES):
        return {
            "schema_version": NAMER.SCHEMA_VERSION,
            "plan_id": "test",
            "created_at": "2026-01-01T00:00:00+00:00",
            "plan_kind": "season_wrap",
            "alist_url": "http://localhost:5244",
            "root_path": SHOW,
            "season": 1,
            "season_folder": SEASON_FOLDER,
            "destination_path": DESTINATION,
            "writable": True,
            "providers": ["local"],
            "file_count": len(names),
            "entries": [
                {
                    "name": name,
                    "source_path": SHOW + "/" + name,
                    "target_path": DESTINATION + "/" + name,
                }
                for name in names
            ],
        }

    def _run_apply(self, client, **overrides):
        args = Args(plan=str(self.plan_path), journal=str(self.journal_path),
                    state_db=self.state_db, **overrides)
        with unittest.mock.patch.object(
            NAMER.AListClient, "from_environment", staticmethod(lambda *a, **k: client)
        ), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            NAMER.command_season_wrap_apply(args)
        return args

    def _journal(self):
        return json.loads(self.journal_path.read_text(encoding="utf-8"))

    def test_wraps_every_planned_file(self):
        client = FakeClient(EPISODES)
        self._run_apply(client)
        self.assertEqual(client.dirs[SHOW], [])
        self.assertEqual(sorted(client.dirs[DESTINATION]), sorted(EPISODES))
        journal = self._journal()
        self.assertEqual(journal["status"], "complete")
        self.assertTrue(all(r["state"] == "moved" for r in journal["entries"]))

    def test_preflight_refuses_a_sidecar_that_appeared_after_planning(self):
        # The plan was written when only the videos were present; a subtitle
        # landed in the folder afterwards. Nothing may move.
        client = FakeClient(EPISODES + ["Breaking.Bad.S01E01.Pilot.1080p.zh.srt"])
        with self.assertRaises(NAMER.ToolError) as caught:
            self._run_apply(client)
        self.assertIn("stranded", str(caught.exception))
        self.assertEqual(client.moves, [])
        self.assertFalse(self.journal_path.exists())

    def test_preflight_refuses_when_the_season_folder_already_exists(self):
        client = FakeClient(EPISODES + [SEASON_FOLDER])
        with self.assertRaises(NAMER.ToolError):
            self._run_apply(client)
        self.assertEqual(client.moves, [])

    def test_confirmations_are_checked_before_any_call(self):
        client = FakeClient(EPISODES)
        for override in [{"confirm_root": "/wrong"}, {"confirm_file_count": 99}]:
            with self.subTest(**override):
                with self.assertRaises(NAMER.ToolError):
                    self._run_apply(client, **override)
                self.assertEqual(client.calls, [])

    def test_a_failed_move_restores_what_already_moved(self):
        client = FakeClient(EPISODES, fail_move_on=EPISODES[1])
        with self.assertRaises(NAMER.ToolError):
            self._run_apply(client)
        # The first episode moved, then the second failed; the first must come
        # back rather than being left behind in a half-built season folder.
        self.assertEqual(sorted(client.dirs[SHOW]), sorted(EPISODES))
        self.assertEqual(client.dirs[DESTINATION], [])
        journal = self._journal()
        self.assertEqual(journal["status"], "restored")
        self.assertEqual([r["state"] for r in journal["entries"]], ["restored", "pending"])

    def test_journal_is_never_overwritten(self):
        self.journal_path.write_text("{}", encoding="utf-8")
        client = FakeClient(EPISODES)
        with self.assertRaises(NAMER.ToolError):
            self._run_apply(client)
        self.assertEqual(self.journal_path.read_text(encoding="utf-8"), "{}")
        self.assertEqual(client.calls, [])


class SeasonWrapRollbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.journal_path = self.tmp / "journal.json"
        self.state_db = str(self.tmp / "absent-state.sqlite3")
        self.journal_path.write_text(json.dumps(self._journal()), encoding="utf-8")

    @staticmethod
    def _journal(state="moved"):
        return {
            "schema_version": NAMER.SCHEMA_VERSION,
            "journal_kind": "season_wrap",
            "run_id": "test",
            "plan_id": "test",
            "alist_url": "http://localhost:5244",
            "root_path": SHOW,
            "season": 1,
            "season_folder": SEASON_FOLDER,
            "destination_path": DESTINATION,
            "destination_created": True,
            "created_at": "2026-01-01T00:00:00+00:00",
            "status": "complete",
            "entries": [
                {
                    "name": name,
                    "source_path": SHOW + "/" + name,
                    "target_path": DESTINATION + "/" + name,
                    "state": state,
                    "error": None,
                }
                for name in EPISODES
            ],
            "rollback_note": None,
        }

    def _run_rollback(self, client, **overrides):
        args = Args(journal=str(self.journal_path), state_db=self.state_db, **overrides)
        with unittest.mock.patch.object(
            NAMER.AListClient, "from_environment", staticmethod(lambda *a, **k: client)
        ), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            NAMER.command_season_wrap_rollback(args)

    def test_restores_every_file_to_the_series_folder(self):
        client = FakeClient([])
        client.dirs[DESTINATION] = list(EPISODES)
        self._run_rollback(client)
        self.assertEqual(sorted(client.dirs[SHOW]), sorted(EPISODES))
        self.assertEqual(client.dirs[DESTINATION], [])
        self.assertEqual(json.loads(self.journal_path.read_text())["status"], "rolled_back")

    def test_refuses_when_the_original_location_is_occupied(self):
        # Something already sits where the file came from; moving back would
        # collide, so the whole rollback must stop before the first move.
        client = FakeClient([EPISODES[0]])
        client.dirs[DESTINATION] = list(EPISODES)
        with self.assertRaises(NAMER.ToolError) as caught:
            self._run_rollback(client)
        self.assertIn("occupied", str(caught.exception))
        self.assertEqual(client.moves, [])

    def test_refuses_when_a_moved_file_vanished_from_the_season_folder(self):
        client = FakeClient([])
        client.dirs[DESTINATION] = [EPISODES[0]]
        with self.assertRaises(NAMER.ToolError):
            self._run_rollback(client)
        self.assertEqual(client.moves, [])

    def test_nothing_to_roll_back_does_not_touch_the_server(self):
        # An apply that failed at mkdir leaves no season folder to list.
        self.journal_path.write_text(json.dumps(self._journal(state="pending")))
        client = FakeClient([])
        self._run_rollback(client)
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
