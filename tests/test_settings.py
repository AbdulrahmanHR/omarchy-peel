"""Settings contract tests: `peel config` and conversions honouring the settings.

Always runs with a temp XDG_CONFIG_HOME, never the real ~/.config/peel.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PEEL = ROOT / "bin" / "peel"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="peel-settings-"))
        self.cfg = self.tmp / "xdg"
        self.work = self.tmp / "work"
        self.work.mkdir()
        self.env = dict(os.environ, XDG_CONFIG_HOME=str(self.cfg))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def peel(self, *args):
        return subprocess.run([str(PEEL), *map(str, args)], capture_output=True, text=True,
                              env=self.env, timeout=600)

    def ok(self, *args):
        proc = self.peel(*args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def set(self, name, value):
        self.ok("config", "set", name, value)

    def cfg_json(self):
        return json.loads(self.ok("config", "--json").stdout)

    def convert(self, src, to):
        return Path(self.ok("convert", "--to", to, src).stdout.strip().splitlines()[0])

    def events(self, src, to):
        proc = self.ok("convert", "--to", to, "--progress", src)
        return [json.loads(l) for l in proc.stdout.splitlines()]

    def mk(self, name, *magick_args):
        path = self.work / name
        subprocess.run(["magick", *magick_args, str(path)], check=True, capture_output=True)
        return path

    def mkvideo(self, name, size, dur=1, rate=25, audio=False):
        path = self.work / name
        argv = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi",
                "-i", f"testsrc=size={size}:rate={rate}:duration={dur}"]
        if audio:
            argv += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}"]
        subprocess.run(argv + [str(path)], check=True, capture_output=True)
        return path

    def ffprobe(self, path, entries, stream=None):
        argv = ["ffprobe", "-v", "error"]
        if stream:
            argv += ["-select_streams", stream]
        argv += ["-show_entries", entries, "-of", "json", str(path)]
        return json.loads(subprocess.run(argv, capture_output=True, text=True).stdout)

    def dims(self, path):
        out = subprocess.run(["magick", "identify", "-format", "%w %h", str(path) + "[0]"],
                             capture_output=True, text=True).stdout.split()
        return int(out[0]), int(out[1])


class ConfigCommand(Base):
    def test_defaults(self):
        out = self.cfg_json()
        self.assertEqual(out["config"]["quality"], "balanced")
        self.assertEqual(out["config"]["advanced"], {})
        self.assertEqual(out["config"]["output"], {"location": "beside", "folder": ""})
        self.assertEqual(out["options"]["keys"][-1], "off")
        self.assertEqual([q["id"] for q in out["options"]["quality"]], ["high", "balanced", "small"])
        fields = {f["key"]: f for f in out["options"]["advanced"]}
        self.assertEqual(len(fields), 10)
        for key, f in fields.items():
            self.assertEqual(set(f["presets"]), {"high", "balanced", "small"}, key)
            self.assertIn(key, out["effective"])
            self.assertEqual(out["effective"][key], f["presets"]["balanced"])
        self.assertEqual(fields["image.quality"]["presets"], {"high": 92, "balanced": 85, "small": 70})
        self.assertEqual(fields["metadata.keep"]["type"], "boolean")
        self.assertEqual(fields["video.speed"]["presets"]["small"], "faster")
        self.assertEqual([o["value"] for o in out["options"]["output"]["location"]], ["beside", "folder"])

    def test_quality_preset_switch_changes_effective(self):
        self.set("quality", "small")
        out = self.cfg_json()
        self.assertEqual(out["config"]["quality"], "small")
        self.assertEqual(out["effective"]["image.quality"], 70)
        self.assertEqual(out["effective"]["image.maxSide"], 2560)
        self.assertEqual(out["effective"]["metadata.keep"], False)
        self.set("quality", "high")
        self.assertEqual(self.cfg_json()["effective"]["video.crf"], 18)

    def test_override_beats_preset_and_default_clears(self):
        self.set("advanced.video.crf", "20")
        out = self.cfg_json()
        self.assertEqual(out["config"]["advanced"], {"video.crf": 20})
        self.assertEqual(out["effective"]["video.crf"], 20)
        self.set("quality", "small")
        self.assertEqual(self.cfg_json()["effective"]["video.crf"], 20)
        self.set("advanced.video.crf", "default")
        out = self.cfg_json()
        self.assertEqual(out["config"]["advanced"], {})
        self.assertEqual(out["effective"]["video.crf"], 28)

    def test_every_field_type(self):
        good = {"image.quality": "50", "image.maxSide": "1280", "video.crf": "14", "video.maxHeight": "480",
                "video.speed": "slower", "audio.bitrate": "320", "gif.fps": "30", "gif.width": "0",
                "pdf.dpi": "72", "metadata.keep": "false"}
        for key, value in good.items():
            self.set(f"advanced.{key}", value)
        adv = self.cfg_json()["config"]["advanced"]
        self.assertEqual(adv["image.quality"], 50)
        self.assertEqual(adv["video.speed"], "slower")
        self.assertIs(adv["metadata.keep"], False)
        self.assertEqual(adv["gif.width"], 0)
        bad = {"image.quality": ["0", "101", "abc", "5.5", ""], "image.maxSide": ["999", "x"],
               "video.crf": ["13", "41"], "video.maxHeight": ["100"], "video.speed": ["ultrafast", "1"],
               "audio.bitrate": ["100", "0"], "gif.fps": ["4", "31"], "gif.width": ["-1"],
               "pdf.dpi": ["100"], "metadata.keep": ["yes", "1", "True"], "nope.field": ["1"]}
        before = (self.cfg / "peel" / "config.json").read_text()
        for key, values in bad.items():
            for value in values:
                proc = self.peel("config", "set", f"advanced.{key}", value)
                self.assertEqual(proc.returncode, 1, (key, value))
                self.assertEqual(len(proc.stderr.strip().splitlines()), 1, (key, value))
        self.assertEqual((self.cfg / "peel" / "config.json").read_text(), before)

    def test_bad_enums(self):
        self.assertEqual(self.peel("config", "set", "quality", "ultra").returncode, 1)
        self.assertEqual(self.peel("config", "set", "output.location", "cloud").returncode, 1)
        self.assertEqual(self.peel("config", "set", "bogus", "x").returncode, 1)
        self.assertFalse((self.cfg / "peel" / "config.json").exists())

    def test_output_folder_rules(self):
        folder = self.tmp / "out"
        self.assertEqual(self.peel("config", "set", "output.folder", str(folder)).returncode, 1)  # missing
        folder.mkdir()
        self.assertEqual(self.peel("config", "set", "output.folder", "out").returncode, 1)  # relative
        f = self.tmp / "file"
        f.write_text("x")
        self.assertEqual(self.peel("config", "set", "output.folder", str(f)).returncode, 1)  # not a dir
        self.set("output.folder", str(folder))
        self.set("output.location", "folder")
        out = self.cfg_json()["config"]["output"]
        self.assertEqual(out, {"location": "folder", "folder": str(folder)})

    def test_write_is_atomic_leaves_only_config(self):
        self.set("quality", "high")
        self.assertEqual([p.name for p in (self.cfg / "peel").iterdir()], ["config.json"])

    def test_invalid_stored_values_are_ignored_with_warning(self):
        (self.cfg / "peel").mkdir(parents=True)
        (self.cfg / "peel" / "config.json").write_text(json.dumps({
            "version": 1, "quality": "ultra", "output": {"location": "moon", "folder": 5},
            "advanced": {"video.crf": 99, "image.quality": 60, "bogus": 1, "metadata.keep": "no",
                         "gif.fps": True}}))
        proc = self.ok("config", "--json")
        out = json.loads(proc.stdout)
        self.assertEqual(out["config"]["quality"], "balanced")
        self.assertEqual(out["config"]["output"], {"location": "beside", "folder": ""})
        self.assertEqual(out["config"]["advanced"], {"image.quality": 60})
        self.assertEqual(out["effective"]["image.quality"], 60)
        self.assertEqual(out["effective"]["video.crf"], 23)
        self.assertGreaterEqual(proc.stderr.count("invalid config"), 6)
        # And a conversion still runs.
        src = self.mk("a.png", "-size", "20x20", "xc:red")
        self.assertTrue(self.convert(src, "jpg").exists())


class Behaviour(Base):
    def test_quality_preset_changes_jpg_size(self):
        src = self.mk("noise.png", "-size", "800x600", "plasma:fractal")
        self.set("quality", "high")
        big = self.convert(src, "jpg")
        big = big.rename(self.work / "high.jpg")
        self.set("quality", "small")
        small = self.convert(src, "jpg")
        self.assertLess(small.stat().st_size, big.stat().st_size)

    def test_max_side_shrinks_but_never_upscales(self):
        big = self.mk("big.png", "-size", "4000x3000", "gradient:red-blue")
        small = self.mk("small.png", "-size", "100x80", "gradient:red-blue")
        self.set("advanced.image.maxSide", "2560")
        w, h = self.dims(self.convert(big, "jpg"))
        self.assertEqual(max(w, h), 2560)
        self.assertEqual((w, h), (2560, 1920))
        self.assertEqual(self.dims(self.convert(small, "jpg")), (100, 80))

    def test_max_side_applies_to_svg(self):
        svg = self.work / "v.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="4000" height="2000">'
                       '<rect width="4000" height="2000" fill="red"/></svg>')
        self.set("advanced.image.maxSide", "1280")
        for to in ("png", "webp"):
            w, h = self.dims(self.convert(svg, to))
            self.assertEqual((w, h), (1280, 640), to)

    def test_video_max_height_even_width(self):
        src = self.mkvideo("clip.mp4", "640x720")
        self.set("advanced.video.maxHeight", "480")
        for to in ("mkv", "webm", "avi"):
            out = self.convert(src, to)
            s = self.ffprobe(out, "stream=width,height", "v:0")["streams"][0]
            self.assertEqual(s["height"], 480, to)
            self.assertEqual(s["width"] % 2, 0, to)
            self.assertEqual(s["width"], 426, to)
        # no upscale
        small = self.mkvideo("tiny.mp4", "160x120")
        out = self.convert(small, "mov")
        s = self.ffprobe(out, "stream=width,height", "v:0")["streams"][0]
        self.assertEqual((s["width"], s["height"]), (160, 120))

    def test_video_crf_changes_size_and_wmv_works(self):
        src = self.mkvideo("n.mp4", "320x240", dur=2)
        self.set("advanced.video.crf", "14")
        hi = self.convert(src, "mkv").rename(self.work / "hi.mkv")
        self.set("advanced.video.crf", "40")
        lo = self.convert(src, "mkv")
        self.assertLess(lo.stat().st_size, hi.stat().st_size)
        self.assertGreater(self.convert(src, "wmv").stat().st_size, 0)

    def test_audio_bitrate_mp3(self):
        src = self.work / "tone.wav"
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=5", str(src)], check=True)
        self.set("advanced.audio.bitrate", "128")
        out = self.convert(src, "mp3")
        rate = int(self.ffprobe(out, "format=bit_rate")["format"]["bit_rate"])
        self.assertAlmostEqual(rate, 128000, delta=128000 * 0.15)
        for to in ("m4a", "ogg", "opus", "wma"):
            self.assertGreater(self.convert(src, to).stat().st_size, 0, to)

    def test_gif_fps_and_width(self):
        src = self.mkvideo("g.mp4", "640x480", dur=2, rate=30)
        self.set("advanced.gif.fps", "8")
        self.set("advanced.gif.width", "320")
        out = self.convert(src, "gif")
        s = self.ffprobe(out, "stream=r_frame_rate,width", "v:0")["streams"][0]
        num, den = s["r_frame_rate"].split("/")
        self.assertAlmostEqual(int(num) / int(den), 8, delta=0.5)
        self.assertEqual(s["width"], 320)
        self.set("advanced.gif.width", "0")
        out = self.convert(src, "gif")
        self.assertEqual(self.ffprobe(out, "stream=width", "v:0")["streams"][0]["width"], 640)
        self.set("advanced.gif.width", "1280")  # never upscale
        out = self.convert(src, "gif")
        self.assertEqual(self.ffprobe(out, "stream=width", "v:0")["streams"][0]["width"], 640)

    def test_pdf_dpi(self):
        if not shutil.which("pdftoppm"):
            self.skipTest("pdftoppm missing")
        pdf = self.work / "p.pdf"
        subprocess.run(["magick", "-size", "612x792", "gradient:white-black", str(pdf)], check=True,
                       capture_output=True)
        self.set("advanced.pdf.dpi", "300")
        hi = self.convert(pdf, "png").rename(self.work / "hi.png")
        self.set("advanced.pdf.dpi", "72")
        lo = self.convert(pdf, "png")
        self.assertLess(self.dims(lo)[0], self.dims(hi)[0])
        self.assertLess(lo.stat().st_size, hi.stat().st_size)
        self.assertAlmostEqual(self.dims(lo)[0], 612, delta=3)

    def identify_verbose(self, path):
        return subprocess.run(["magick", "identify", "-verbose", str(path)], capture_output=True,
                              text=True).stdout

    def test_metadata_keep_false_strips(self):
        src = self.mk("tagged.jpg", "-size", "40x40", "xc:red", "-set", "comment", "SECRETNOTE")
        self.assertIn("SECRETNOTE", self.identify_verbose(src))
        out = self.convert(src, "png").rename(self.work / "kept.png")
        self.assertIn("SECRETNOTE", self.identify_verbose(out))
        self.set("advanced.metadata.keep", "false")
        out = self.convert(src, "png")
        verbose = self.identify_verbose(out)
        self.assertNotIn("SECRETNOTE", verbose)

    def test_metadata_keep_false_video(self):
        src = self.work / "t.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc=size=64x64:rate=10:duration=1", "-metadata", "title=SECRETTITLE",
                        str(src)], check=True)
        kept = self.convert(src, "mkv").rename(self.work / "kept.mkv")
        self.assertIn("SECRETTITLE", json.dumps(self.ffprobe(kept, "format_tags")))
        self.set("advanced.metadata.keep", "false")
        out = self.convert(src, "mkv")
        self.assertNotIn("SECRETTITLE", json.dumps(self.ffprobe(out, "format_tags")))

    def test_output_folder_and_fallback(self):
        src = self.mk("pic.png", "-size", "30x30", "xc:blue")
        folder = self.tmp / "dest"
        folder.mkdir()
        self.set("output.folder", str(folder))
        self.set("output.location", "folder")
        out = self.convert(src, "jpg")
        self.assertEqual(out, folder / "pic.jpg")
        self.assertFalse((self.work / "pic.jpg").exists())
        again = self.convert(src, "jpg")  # no-overwrite naming
        self.assertEqual(again, folder / "pic (1).jpg")
        self.assertEqual([p.name for p in folder.iterdir() if p.name.startswith(".")], [])
        # Folder disappears: fall back beside the source, warn once.
        shutil.rmtree(folder)
        src2 = self.mk("two.png", "-size", "30x30", "xc:green")
        events = self.events([src, src2][0], "webp")
        warnings = [e for e in events if e["event"] == "warning"]
        self.assertEqual(len(warnings), 1)
        done = [e for e in events if e["event"] == "done"]
        self.assertEqual(Path(done[0]["output"]), self.work / "pic.webp")
        events = [json.loads(l) for l in self.ok("convert", "--to", "bmp", "--progress", src, src2).stdout.splitlines()]
        self.assertEqual(len([e for e in events if e["event"] == "warning"]), 1)
        self.assertEqual(len([e for e in events if e["event"] == "done"]), 2)


if __name__ == "__main__":
    unittest.main()
