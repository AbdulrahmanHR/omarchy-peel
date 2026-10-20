"""End-to-end tests for bin/peel-tool, run against the real programs.

    python3 -I -m unittest discover -s tests -p 'test_peel_tool*' -v
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "bin" / "peel-tool"

HOSTILE = [
    "-rf.png",
    "label:pwned.png",
    "|touch PWNED_PIPE.png",
    "a[0].png",
    "$(touch PWNED_SUB).png",
    "x;touch PWNED_SEMI.png",
    "%d%s.png",
]


# Never read the real ~/.config/peel.
ISOLATED_CONFIG = tempfile.mkdtemp(prefix="peel-tool-test-config-")


def tool(*args, check=True):
    proc = subprocess.run([str(TOOL), *map(str, args)], capture_output=True, text=True, timeout=900,
                          env=dict(os.environ, XDG_CONFIG_HOME=ISOLATED_CONFIG))
    if check and proc.returncode != 0:
        raise AssertionError(f"peel-tool {' '.join(map(str, args))} failed:\n{proc.stderr}")
    return proc


def sh(*argv):
    subprocess.run(argv, check=True, capture_output=True, timeout=120)


def ffprobe(path, entries):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "csv=p=0",
                          f"file:{path}"], capture_output=True, text=True)
    return out.stdout.strip()


def identify(path):
    with open(path, "rb") as fin:
        out = subprocess.run(["magick", "identify", "-format", "%m %w %h\n", "-"], stdin=fin,
                             capture_output=True, text=True)
    return out.stdout.split("\n")[0].strip()


def npages(path):
    return int(subprocess.run(["qpdf", "--show-npages", str(path)], capture_output=True, text=True,
                              check=True).stdout.strip())


def targets(*files):
    return [t["id"] for t in json.loads(tool("targets", "--json", "--", *files).stdout)["tools"]]


class Fixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="peel-tool-test-"))
        t = cls.tmp
        cls.png, cls.mp4, cls.wav, cls.pdf, cls.pdf2 = (t / n for n in
                                                       ("base.png", "base.mp4", "base.wav", "base.pdf", "base2.pdf"))
        cls.big = t / "big.png"
        cls.mp3 = t / "base.mp3"
        sh("magick", "-size", "65x47", "gradient:orange-blue", f"PNG:{cls.png}")
        sh("magick", "-size", "3000x1000", "gradient:red-blue", f"PNG:{cls.big}")
        sh("ffmpeg", "-nostdin", "-y", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc=size=66x48:rate=10:duration=2",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
           "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", f"file:{cls.mp4}")
        # 1s silence, 1s tone, 1s silence.
        sh("ffmpeg", "-nostdin", "-y", "-loglevel", "error",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
           "-af", "adelay=1000:all=1,apad=pad_dur=1", f"file:{cls.wav}")
        sh("ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", f"file:{cls.wav}", f"file:{cls.mp3}")
        sh("magick", "-size", "65x47", "gradient:orange-blue", f"PDF:{cls.pdf}")
        sh("magick", "-size", "65x47", "gradient:red-green", f"PDF:{cls.pdf2}")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def fresh(self, src, name=None):
        d = Path(tempfile.mkdtemp(dir=self.tmp))
        dst = d / (name or src.name)
        shutil.copy(src, dst)
        return dst

    def run_tool(self, tool_id, src, expect_name):
        before = Path(src).read_bytes()
        out = Path(tool("run", "--tool", tool_id, "--", src).stdout.strip())
        self.assertEqual(out.name, expect_name)
        self.assertEqual(out.parent, Path(src).parent.resolve())
        self.assertGreater(out.stat().st_size, 0)
        self.assertEqual(Path(src).read_bytes(), before)
        self.assertEqual([p.name for p in out.parent.iterdir() if p.name.startswith(".")], [])
        return out


class Targets(Fixtures):
    def test_png(self):
        self.assertEqual(targets(self.png), ["compress", "resize-half", "strip-metadata", "rotate", "to-grayscale"])

    def test_mp4(self):
        self.assertEqual(targets(self.mp4), ["compress", "extract-audio", "snapshot", "resize-half",
                                             "strip-metadata", "rotate"])

    def test_audio(self):
        self.assertEqual(targets(self.wav), ["compress", "trim-silence", "strip-metadata"])

    def test_single_pdf(self):
        self.assertEqual(targets(self.pdf), ["compress", "split-pdf", "strip-metadata"])

    def test_two_pdfs(self):
        self.assertEqual(targets(self.pdf, self.pdf2), ["compress", "merge-pdf", "split-pdf", "strip-metadata"])

    def test_mixed_is_intersection(self):
        self.assertEqual(targets(self.png, self.mp4), ["compress", "resize-half", "strip-metadata", "rotate"])
        self.assertEqual(targets(self.png, self.pdf), ["compress", "strip-metadata"])

    def test_labels(self):
        data = json.loads(tool("targets", "--json", "--", self.png).stdout)
        self.assertEqual(data["tools"][0], {"id": "compress", "label": "Compress"})


class Image(Fixtures):
    def test_compress_shrinks_large(self):
        out = self.run_tool("compress", self.fresh(self.big), "big (compressed).png")
        self.assertEqual(identify(out), "PNG 2560 853")

    def test_compress_small_keeps_size(self):
        out = self.run_tool("compress", self.fresh(self.png), "base (compressed).png")
        self.assertEqual(identify(out), "PNG 65 47")

    def test_compress_jpeg(self):
        src = self.fresh(self.png, "photo.jpg")
        sh("magick", str(self.png), f"JPEG:{src}")
        self.assertEqual(identify(self.run_tool("compress", src, "photo (compressed).jpg")).split()[0], "JPEG")

    def test_strip(self):
        self.assertEqual(identify(self.run_tool("strip-metadata", self.fresh(self.png), "base (no info).png")),
                         "PNG 65 47")

    def test_half(self):
        self.assertEqual(identify(self.run_tool("resize-half", self.fresh(self.png), "base (half).png")),
                         "PNG 33 24")

    def test_rotate(self):
        self.assertEqual(identify(self.run_tool("rotate", self.fresh(self.png), "base (rotated).png")),
                         "PNG 47 65")

    def test_gray(self):
        out = self.run_tool("to-grayscale", self.fresh(self.png), "base (gray).png")
        sat = subprocess.run(["magick", str(out), "-colorspace", "HSL", "-channel", "G", "-separate",
                              "-format", "%[fx:maxima]", "info:"], capture_output=True, text=True).stdout
        self.assertEqual(float(sat), 0.0)

    def test_never_overwrites(self):
        src = self.fresh(self.png)
        first = Path(tool("run", "--tool", "rotate", "--", src).stdout.strip())
        second = Path(tool("run", "--tool", "rotate", "--", src).stdout.strip())
        self.assertEqual(first.name, "base (rotated).png")
        self.assertEqual(second.name, "base (rotated) (1).png")


class Video(Fixtures):
    def test_compress(self):
        out = self.run_tool("compress", self.fresh(self.mp4), "base (compressed).mp4")
        self.assertEqual(ffprobe(out, "stream=codec_name"), "h264\naac")

    def test_compress_webm(self):
        src = self.fresh(self.mp4, "clip.webm")
        sh("ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", f"file:{self.mp4}", "-c:v", "libvpx-vp9",
           "-c:a", "libopus", "-f", "webm", f"file:{src}")
        out = self.run_tool("compress", src, "clip (compressed).webm")
        self.assertIn("vp9", ffprobe(out, "stream=codec_name"))

    def test_strip(self):
        out = self.run_tool("strip-metadata", self.fresh(self.mp4), "base (no info).mp4")
        self.assertEqual(ffprobe(out, "stream=codec_name"), "h264\naac")

    def test_half(self):
        out = self.run_tool("resize-half", self.fresh(self.mp4), "base (half).mp4")
        self.assertEqual(ffprobe(out, "stream=width,height").splitlines()[0], "32,24")

    def test_rotate(self):
        out = self.run_tool("rotate", self.fresh(self.mp4), "base (rotated).mp4")
        self.assertEqual(ffprobe(out, "stream=width,height").splitlines()[0], "48,66")

    def test_extract_audio(self):
        out = self.run_tool("extract-audio", self.fresh(self.mp4, "clip.mp4"), "clip.m4a")
        self.assertEqual(ffprobe(out, "stream=codec_name"), "aac")

    def test_snapshot(self):
        out = self.run_tool("snapshot", self.fresh(self.mp4, "clip.mp4"), "clip (frame).png")
        self.assertEqual(identify(out), "PNG 66 48")

    def test_progress_events(self):
        src = self.fresh(self.mp4)
        proc = tool("run", "--tool", "compress", "--progress", "--", src)
        events = [json.loads(l) for l in proc.stdout.splitlines()]
        self.assertEqual([e["event"] for e in events if e["event"] != "progress"], ["start", "done", "finished"])
        self.assertEqual(events[-1], {"event": "finished", "ok": 1, "failed": 0, "skipped": 0})


class Audio(Fixtures):
    def test_trim(self):
        before = float(ffprobe(self.wav, "format=duration"))
        out = self.run_tool("trim-silence", self.fresh(self.wav, "tone.wav"), "tone (trimmed).wav")
        after = float(ffprobe(out, "format=duration"))
        self.assertLess(after, before - 1.0)
        self.assertGreater(after, 0.5)

    def test_strip(self):
        out = self.run_tool("strip-metadata", self.fresh(self.wav, "tone.wav"), "tone (no info).wav")
        self.assertEqual(ffprobe(out, "stream=codec_name"), "pcm_s16le")

    def test_compress_mp3(self):
        out = self.run_tool("compress", self.fresh(self.mp3, "tone.mp3"), "tone (compressed).mp3")
        self.assertEqual(ffprobe(out, "stream=codec_name"), "mp3")

    def test_compress_lossless_skipped(self):
        src = self.fresh(self.wav, "tone.wav")
        proc = tool("run", "--tool", "compress", "--progress", "--", src)
        events = [json.loads(l) for l in proc.stdout.splitlines()]
        skipped = [e for e in events if e["event"] == "skipped"]
        self.assertEqual(len(skipped), 1)
        self.assertTrue(skipped[0]["reason"])
        self.assertEqual(events[-1]["skipped"], 1)
        self.assertEqual(sorted(p.name for p in src.parent.iterdir()), ["tone.wav"])


class Pdf(Fixtures):
    def test_compress(self):
        out = self.run_tool("compress", self.fresh(self.pdf, "doc.pdf"), "doc (compressed).pdf")
        self.assertEqual(npages(out), 1)

    def test_strip(self):
        out = self.run_tool("strip-metadata", self.fresh(self.pdf, "doc.pdf"), "doc (no info).pdf")
        self.assertEqual(npages(out), 1)

    def test_merge(self):
        d = Path(tempfile.mkdtemp(dir=self.tmp))
        a, b = d / "a.pdf", d / "b.pdf"
        shutil.copy(self.pdf, a)
        shutil.copy(self.pdf2, b)
        out = Path(tool("run", "--tool", "merge-pdf", "--", a, b).stdout.strip())
        self.assertEqual(out.name, "a (merged).pdf")
        self.assertEqual(npages(out), 2)
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["a (merged).pdf", "a.pdf", "b.pdf"])

    def test_merge_needs_two(self):
        self.assertNotEqual(tool("run", "--tool", "merge-pdf", "--", self.pdf, check=False).returncode, 0)

    def test_split(self):
        d = Path(tempfile.mkdtemp(dir=self.tmp))
        multi = d / "doc.pdf"
        sh("qpdf", "--empty", "--pages", str(self.pdf), str(self.pdf2), "--", str(multi))
        before = multi.read_bytes()
        tool("run", "--tool", "split-pdf", "--", multi)
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["doc (page 1).pdf", "doc (page 2).pdf", "doc.pdf"])
        self.assertEqual(npages(d / "doc (page 2).pdf"), 1)
        self.assertEqual(multi.read_bytes(), before)


class HostileNames(Fixtures):
    def no_pwned(self, directory):
        self.assertEqual([p.name for p in directory.iterdir() if p.name.startswith("PWNED")], [])
        self.assertEqual([p.name for p in directory.iterdir() if p.name.startswith(".")], [])

    def test_compress_png(self):
        for name in HOSTILE:
            with self.subTest(name=name):
                src = self.fresh(self.png, name)
                out = Path(tool("run", "--tool", "compress", "--", src).stdout.strip())
                self.assertEqual(out.name, f"{Path(name).stem} (compressed).png")
                self.assertTrue(identify(out).startswith("PNG"))
                self.no_pwned(src.parent)

    def test_compress_mp4(self):
        for name in ("%03d|concat:x.mp4", "-rf.mp4", "label:pwned.mp4"):
            with self.subTest(name=name):
                src = self.fresh(self.mp4, name)
                out = Path(tool("run", "--tool", "compress", "--", src).stdout.strip())
                self.assertEqual(out.name, f"{Path(name).stem} (compressed).mp4")
                self.assertIn("h264", ffprobe(out, "stream=codec_name"))
                self.no_pwned(src.parent)

    def test_compress_pdf(self):
        src = self.fresh(self.pdf, "%d%s $(touch PWNED_SUB).pdf")
        out = Path(tool("run", "--tool", "compress", "--", src).stdout.strip())
        self.assertEqual(npages(out), 1)
        self.no_pwned(src.parent)

    def test_merge_pdf(self):
        for name in HOSTILE:
            with self.subTest(name=name):
                d = Path(tempfile.mkdtemp(dir=self.tmp))
                a = d / Path(name).with_suffix(".pdf").name
                b = d / "@1-2.pdf"
                shutil.copy(self.pdf, a)
                shutil.copy(self.pdf2, b)
                out = Path(tool("run", "--tool", "merge-pdf", "--", a, b).stdout.strip())
                self.assertEqual(out.name, f"{a.stem} (merged).pdf")
                self.assertEqual(npages(out), 2)
                self.no_pwned(d)


if __name__ == "__main__":
    unittest.main()
