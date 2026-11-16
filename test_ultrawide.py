import os
import struct
import tempfile
import unittest
from unittest import mock

import ultrawide


class ViewportScanTests(unittest.TestCase):
    def setUp(self):
        self.memory = tempfile.TemporaryFile()
        self.memory.truncate(4096)
        self.fd = self.memory.fileno()
        self.maps = ["00000000-00001000 rw-p 00000000 00:00 0"]

    def tearDown(self):
        self.memory.close()

    def write(self, address, data):
        self.assertEqual(os.pwrite(self.fd, data, address), len(data))

    def viewport(self, address, width=683, name="$Viewport"):
        type_address, object_address, name_address = address + 128, address + 192, address + 256
        self.write(address - 48, struct.pack("<Q", type_address))
        self.write(address, struct.pack("<ii", width, 400))
        self.write(type_address, struct.pack("<I4xQ", 11, object_address))
        self.write(object_address + 16, struct.pack("<Q", name_address))
        self.write(name_address, (name + "\0").encode("utf-16-le"))

    def test_scans_stock_and_patched_across_chunk_boundary(self):
        for width in (683, 860, 1100, 100):
            with self.subTest(width=width):
                self.viewport(252, width)
                with mock.patch.object(ultrawide, "CHUNK_SIZE", 256):
                    self.assertEqual(ultrawide.find_viewport(self.fd, self.maps), 252)

    def test_rejects_pair_with_wrong_type(self):
        self.viewport(512, name="$WrongTyp")
        with self.assertRaisesRegex(RuntimeError, "found 0"):
            ultrawide.find_viewport(self.fd, self.maps)

    def test_rejects_ambiguous_viewports(self):
        self.viewport(512)
        self.viewport(2048, width=860)
        with self.assertRaisesRegex(RuntimeError, "found 2"):
            ultrawide.find_viewport(self.fd, self.maps)

    def test_short_memory_read_is_an_error(self):
        with self.assertRaisesRegex(RuntimeError, "Short memory read"):
            ultrawide.find_viewport(self.fd, ["00000000-00002000 rw-p 00000000 00:00 0"])


class FullscreenWindowTests(unittest.TestCase):
    def test_accepts_matching_fullscreen_window(self):
        responses = ["0x012 0 42 0 0 3440 1440 host Dead Cells\n",
                     "_NET_WM_STATE(ATOM) = _NET_WM_STATE_FULLSCREEN\n"]
        with mock.patch.object(ultrawide, "run_command", side_effect=responses):
            self.assertEqual(ultrawide.fullscreen_window(42), ("0x012", (3440, 1440)))

    def test_detects_other_resolution(self):
        responses = ["0x012 0 42 0 0 2560 1080 host Dead Cells\n",
                     "_NET_WM_STATE(ATOM) = _NET_WM_STATE_FULLSCREEN\n"]
        with mock.patch.object(ultrawide, "run_command", side_effect=responses):
            self.assertEqual(ultrawide.fullscreen_window(42), ("0x012", (2560, 1080)))

    def test_rejects_non_fullscreen_window(self):
        responses = ["0x012 0 42 0 0 3440 1440 host Dead Cells\n",
                     "_NET_WM_STATE(ATOM) =\n"]
        with mock.patch.object(ultrawide, "run_command", side_effect=responses):
            with self.assertRaisesRegex(RuntimeError, "must be in X11 fullscreen"):
                ultrawide.fullscreen_window(42)


class BuildTests(unittest.TestCase):
    def test_unknown_bytecode_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = ultrawide.Path(directory)
            (path / "hlboot.dat").write_bytes(b"not the tested game build")
            with self.assertRaisesRegex(RuntimeError, "differs from the tested build"):
                ultrawide.check_build(path)


class ResolutionTests(unittest.TestCase):
    def test_fit(self):
        for resolution, width in [((3440, 1440), 860), ((2560, 1080), 854),
                                  ((5120, 1440), 1280), ((1920, 1080), 683)]:
            with self.subTest(resolution=resolution):
                self.assertEqual(ultrawide.fit_width(resolution), width)

    def test_parse_resolution(self):
        self.assertEqual(ultrawide.parse_resolution("3440X1440"), (3440, 1440))
        for value in ("0x1440", "3440", "abcx1440", "3440x1440x1", "99999x1"):
            with self.subTest(value=value), self.assertRaises(ultrawide.argparse.ArgumentTypeError):
                ultrawide.parse_resolution(value)

    def test_parse_width(self):
        self.assertEqual(ultrawide.parse_width("900"), 900)
        for value in ("0", "8193", "no"):
            with self.subTest(value=value), self.assertRaises(ultrawide.argparse.ArgumentTypeError):
                ultrawide.parse_width(value)


if __name__ == "__main__":
    unittest.main()
