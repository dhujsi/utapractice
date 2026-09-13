import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import netease_bridge


class NeteaseBridgeTestCase(unittest.TestCase):
    def test_merge_lyrics_builds_one_canonical_document(self):
        merged = netease_bridge.merge_lyrics_single_file(
            "[00:01.00]歌\n[00:02.00]次",
            "[00:01.10]song",
            "[00:01.00]uta",
        )

        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["translation"], "song")
        self.assertEqual(merged[0]["roman"], "uta")
        self.assertEqual(merged[1]["translation"], "")

    def test_safe_name_uses_the_same_canonical_rules_as_the_web_app(self):
        self.assertEqual(netease_bridge.safe_name("  A：B  "), "A_B")
        with self.assertRaises(ValueError):
            netease_bridge.safe_name("../")

    def test_json_save_replaces_the_document_without_leaving_temp_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "song.json"
            netease_bridge.json_save(target, [{"time": 1}])
            netease_bridge.json_save(target, [{"time": 2}])

            self.assertIn('"time": 2', target.read_text(encoding="utf-8"))
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_download_refreshes_song_metadata_in_the_canonical_document(self):
        with tempfile.TemporaryDirectory() as directory:
            original_song_dir = netease_bridge.SONG_DIR
            netease_bridge.SONG_DIR = Path(directory)
            try:
                (netease_bridge.SONG_DIR / "Demo.mp3").write_bytes(b"audio")
                netease_bridge.json_save(
                    netease_bridge.SONG_DIR / "Demo.json",
                    [{"time": 1, "original_html": "line"}],
                )
                with patch.object(netease_bridge, "ncm_request", side_effect=RuntimeError("offline")):
                    result = netease_bridge.download_song("42", "Demo", "Singer", "exhigh", "Album")

                document = json.loads((netease_bridge.SONG_DIR / "Demo.json").read_text(encoding="utf-8"))
                self.assertEqual(result["artists"], ["Singer"])
                self.assertEqual(document["title"], "Demo")
                self.assertEqual(document["artists"], ["Singer"])
                self.assertEqual(document["album"], "Album")
                self.assertEqual(document["source"]["song_id"], "42")
            finally:
                netease_bridge.SONG_DIR = original_song_dir


if __name__ == "__main__":
    unittest.main()
