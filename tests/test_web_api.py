import io
import json
import tempfile
import unittest
from pathlib import Path

import web_app


class WebApiTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.original_paths = {
            "SONG_DIR": web_app.SONG_DIR,
            "ARCHIVE_DIR": web_app.ARCHIVE_DIR,
            "GENERATED_DIR": web_app.GENERATED_DIR,
            "DB_PATH": web_app.DB_PATH,
            "SETTINGS_PATH": web_app.SETTINGS_PATH,
            "JOBS_PATH": web_app.JOBS_PATH,
        }
        web_app.SONG_DIR = root / "songs"
        web_app.ARCHIVE_DIR = root / "archive"
        web_app.GENERATED_DIR = root / "generated"
        web_app.DB_PATH = root / "song_db.json"
        web_app.SETTINGS_PATH = root / "settings.local.json"
        web_app.JOBS_PATH = root / "lyrics_jobs.json"
        for directory in (web_app.SONG_DIR, web_app.ARCHIVE_DIR, web_app.GENERATED_DIR):
            directory.mkdir(parents=True)
        web_app.atomic_write_json(web_app.DB_PATH, {})
        web_app.atomic_write_json(web_app.JOBS_PATH, {})
        web_app.audio_probe_cache.clear()
        web_app.app.config.update(TESTING=True)
        self.client = web_app.app.test_client()

    def tearDown(self):
        for name, value in self.original_paths.items():
            setattr(web_app, name, value)
        self.temporary.cleanup()

    def test_typed_lrc_is_saved_as_canonical_json(self):
        response = self.client.post(
            "/api/upload/lyrics-text",
            json={
                "song_name": "Demo",
                "lyrics_type": "lrc",
                "lyrics_text": "[00:01.20]最初の行\n[00:02.50]second",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["saved"], "Demo.json")
        self.assertTrue((web_app.SONG_DIR / "Demo.json").exists())
        self.assertFalse((web_app.SONG_DIR / "Demo.lrc").exists())
        document = json.loads((web_app.SONG_DIR / "Demo.json").read_text(encoding="utf-8"))
        self.assertEqual(document["title"], "Demo")
        self.assertEqual(document["artists"], [])
        self.assertEqual([line["time"] for line in document["lyrics"]], [1.2, 2.5])

    def test_song_metadata_is_saved_and_exposed_by_manifest(self):
        response = self.client.post(
            "/api/upload/lyrics-text",
            json={
                "song_name": "Metadata Demo",
                "artist": "歌手甲 / 歌手乙",
                "album": "专辑 A",
                "lyrics_type": "lrc",
                "lyrics_text": "[00:01]line",
            },
        )

        self.assertEqual(response.status_code, 200)
        document = json.loads((web_app.SONG_DIR / "Metadata Demo.json").read_text(encoding="utf-8"))
        self.assertEqual(document["artists"], ["歌手甲", "歌手乙"])
        self.assertEqual(document["album"], "专辑 A")
        detail = self.client.get("/api/songs/Metadata%20Demo").get_json()
        self.assertEqual(detail["artists"], ["歌手甲", "歌手乙"])
        self.assertEqual(detail["artist"], "歌手甲 / 歌手乙")
        manifest = self.client.get("/api/sync/manifest").get_json()
        summary = next(song for song in manifest["songs"] if song["name"] == "Metadata Demo")
        self.assertTrue(summary["document_version"])
        self.assertEqual(summary["audio_version"], "")

    def test_uploaded_lrc_is_validated_before_it_is_written(self):
        response = self.client.post(
            "/api/upload/lyrics",
            data={"lyrics": (io.BytesIO(b"plain text"), "Broken.lrc")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(list(web_app.SONG_DIR.iterdir()), [])

    def test_json_editor_removes_unsafe_markup(self):
        response = self.client.post(
            "/api/songs/Demo/lyrics",
            json=[
                {
                    "time": 1,
                    "original_html": '<ruby onclick="bad()">歌<rt>うた</rt></ruby><script>alert(1)</script>',
                    "translation": "<b>译文</b>",
                }
            ],
        )

        self.assertEqual(response.status_code, 200)
        document = json.loads((web_app.SONG_DIR / "Demo.json").read_text(encoding="utf-8"))
        lyrics = document["lyrics"]
        self.assertNotIn("onclick", lyrics[0]["original_html"])
        self.assertNotIn("<script", lyrics[0]["original_html"])
        self.assertEqual(lyrics[0]["translation"], "译文")

    def test_rename_moves_song_files_metadata_and_workspace(self):
        web_app.atomic_write_json(web_app.SONG_DIR / "Old.json", [])
        (web_app.SONG_DIR / "Old.mp3").write_bytes(b"audio")
        web_app.atomic_write_json(web_app.SONG_DIR / "Old.lyrics_source.json", {"song_name": "Old"})
        web_app.atomic_write_json(web_app.DB_PATH, {"Old": {"learned": True}})
        web_app.atomic_write_json(
            web_app.JOBS_PATH,
            {"job": {"song_name": "Old", "payload": {"song_name": "Old"}}},
        )

        response = self.client.post("/api/songs/Old/rename", json={"new_name": "New"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue((web_app.SONG_DIR / "New.json").exists())
        self.assertTrue((web_app.SONG_DIR / "New.mp3").exists())
        workspace = json.loads((web_app.SONG_DIR / "New.lyrics_source.json").read_text(encoding="utf-8"))
        self.assertEqual(workspace["song_name"], "New")
        self.assertIn("New", web_app.load_db())
        self.assertNotIn("Old", web_app.load_db())
        job = web_app.load_jobs()["job"]
        self.assertEqual(job["song_name"], "New")
        self.assertEqual(job["payload"]["song_name"], "New")

    def test_legacy_generation_job_type_is_rejected(self):
        response = self.client.post(
            "/api/convert-jobs",
            json={"song_name": "Demo", "type": "convert_lyrics"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("旧歌词生成流程已停用", response.get_json()["error"])

    def test_song_name_cannot_escape_data_directory(self):
        response = self.client.post(
            "/api/upload/lyrics-text",
            json={"song_name": "../", "lyrics_type": "lrc", "lyrics_text": "[00:01]line"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(list(web_app.SONG_DIR.iterdir()), [])

    def test_existing_legacy_filename_is_resolved_without_renaming_it(self):
        legacy_name = "un：c - Song"
        web_app.atomic_write_json(web_app.SONG_DIR / f"{legacy_name}.json", [])

        response = self.client.get(f"/api/songs/{legacy_name}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["name"], legacy_name)
        self.assertEqual(response.get_json()["title"], "Song")
        self.assertEqual(response.get_json()["artists"], ["un：c"])
        self.assertTrue((web_app.SONG_DIR / f"{legacy_name}.json").exists())


if __name__ == "__main__":
    unittest.main()
