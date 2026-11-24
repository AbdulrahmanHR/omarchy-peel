"""Tool options: the pages grammar, split modes, check/info, --opt, config tools, option-driven argv.

    python3 -I -m unittest tests.test_tool_options -v

Always runs with a temp XDG_CONFIG_HOME, never the real ~/.config/peel.
"""

import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "bin" / "peel-tool"
PEEL = ROOT / "bin" / "peel"


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


PT = load(TOOL, "peel_tool_mod")
PL = load(PEEL, "peel_mod")

FAKE = """#!/usr/bin/env python3
import json, os, sys
d = os.path.dirname(os.path.abspath(__file__))
name = os.path.basename(sys.argv[0])
open(os.path.join(d, "argv.log"), "a").write(json.dumps([name] + sys.argv[1:]) + "\\n")
out = None
if name == "magick":
    sys.stdin.buffer.read()
    sys.stdout.buffer.write(b"x")
elif name == "ffmpeg":
    out = sys.argv[-1][len("file:"):]
elif name == "gs":
    out = [a for a in sys.argv if a.startswith("-sOutputFile=")][0].split("=", 1)[1]
if out:
    open(out, "wb").write(b"x")
"""


def sh(*argv):
    subprocess.run(argv, check=True, capture_output=True, timeout=120)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="peel-opts-"))
        cls.cfg = cls.tmp / "xdg"
        cls.base = cls.tmp / "base"
        cls.base.mkdir()
        sh("magick", "-size", "65x47", "xc:white", f"PDF:{cls.base / 'one.pdf'}")
        cls.pdf12 = cls.base / "doc.pdf"
        sh("qpdf", "--empty", "--pages", *[str(cls.base / "one.pdf")] * 12, "--", str(cls.pdf12))
        cls.png = cls.base / "base.png"
        sh("magick", "-size", "65x47", "gradient:orange-blue", f"PNG:{cls.png}")
        cls.mp4 = cls.base / "base.mp4"
        sh("ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
           "testsrc=size=66x48:rate=10:duration=2", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
           "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", f"file:{cls.mp4}")
        cls.wav = cls.base / "base.wav"
        sh("ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
           f"file:{cls.wav}")
        cls.mp3 = cls.base / "base.mp3"
        sh("ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", f"file:{cls.wav}", f"file:{cls.mp3}")
        cls.fakes = cls.tmp / "fakes"
        cls.fakes.mkdir()
        for name in ("magick", "ffmpeg", "gs"):
            f = cls.fakes / name
            f.write_text(FAKE)
            f.chmod(f.stat().st_mode | stat.S_IXUSR)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        shutil.rmtree(self.cfg, ignore_errors=True)
        self.work = Path(tempfile.mkdtemp(dir=self.tmp))

    def fresh(self, src, name=None, same_dir=False):
        """A copy of src in its own new directory (or in self.work with same_dir)."""
        d = self.work if same_dir else Path(tempfile.mkdtemp(dir=self.work))
        dst = d / (name or src.name)
        shutil.copy(src, dst)
        return dst

    def env(self, fake=False):
        env = dict(os.environ, XDG_CONFIG_HOME=str(self.cfg))
        if fake:
            env["PATH"] = f"{self.fakes}{os.pathsep}{env['PATH']}"
        return env

    def tool(self, *args, fake=False):
        return subprocess.run([str(TOOL), *map(str, args)], capture_output=True, text=True, timeout=600,
                              env=self.env(fake))

    def peel(self, *args):
        return subprocess.run([str(PEEL), *map(str, args)], capture_output=True, text=True, timeout=120,
                              env=self.env())

    def check(self, tool_id, *opts, files=None):
        argv = ["check", "--json", "--tool", tool_id]
        for o in opts:
            argv += ["--opt", o]
        proc = self.tool(*argv, "--", *(files or [self.pdf12]))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def split(self, *opts, src=None):
        src = src or self.fresh(self.pdf12)
        argv = ["run", "--tool", "split-pdf"]
        for o in opts:
            argv += ["--opt", o]
        proc = self.tool(*argv, "--", src)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return sorted(p.name for p in src.parent.iterdir() if p.name != src.name)

    def fake_log(self):
        log = self.fakes / "argv.log"
        rows = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
        log.unlink(missing_ok=True)
        return rows

    def run_fake(self, tool_id, src, *opts):
        self.fake_log()
        argv = ["run", "--tool", tool_id]
        for o in opts:
            argv += ["--opt", o]
        proc = self.tool(*argv, "--", src, fake=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = self.fake_log()
        # Blank the one temp name and the input so the comparison is stable.
        return [[a.replace(str(src), "IN") if a != str(src) else "IN" for a in r] for r in rows]


def pages(text, count=12):
    return PT.resolve_pages(PT.parse_pages(text), count)


class Grammar(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(pages("5"), [[5]])
        self.assertEqual(pages("1-3, 5 , 8 - end"), [[1, 2, 3], [5], [8, 9, 10, 11, 12]])
        self.assertEqual(pages("end"), [[12]])
        self.assertEqual(pages("last"), [[12]])
        self.assertEqual(pages("LAST, 2-END"), [[12], list(range(2, 13))])
        self.assertEqual(pages("3-3"), [[3]])
        self.assertEqual(PT.parse_pages(""), [])
        self.assertEqual(PT.parse_pages("   "), [])

    def test_reversed(self):
        self.assertEqual(pages("5-2"), [[5, 4, 3, 2]])

    def test_invalid(self):
        for bad in ("0", "1-0", "a", "1,,2", "1,", ",1", "1-", "-3", "1--3", "1 2", "1-2-3", "end-3",
                    "1.5", "1;2", "1-3x", "-rf", "$(x)", "99999999999"):
            with self.subTest(bad=bad):
                with self.assertRaises(PT.ToolError):
                    PT.parse_pages(bad)
                with self.assertRaises(PL.PeelError):
                    PL.check_pages(bad)

    def test_past_the_end(self):
        for text, culprit in (("14", 14), ("1-13", 13), ("13-2", 13), ("3, 40", 40)):
            with self.subTest(text=text):
                with self.assertRaises(PT.ToolError) as caught:
                    pages(text)
                self.assertEqual(str(caught.exception), f"page {culprit} is past the end (12 pages)")
        with self.assertRaises(PT.ToolError):
            pages("20-end")

    def test_limits(self):
        PT.parse_pages(",".join(["1"] * 200))
        PL.check_pages(",".join(["1"] * 200))
        with self.assertRaises(PT.ToolError):
            PT.parse_pages(",".join(["1"] * 201))
        with self.assertRaises(PL.PeelError):
            PL.check_pages(",".join(["1"] * 201))
        PT.parse_pages("1" + " " * 499)
        with self.assertRaises(PT.ToolError):
            PT.parse_pages("1" + " " * 500)
        with self.assertRaises(PL.PeelError):
            PL.check_pages("1" + " " * 500)

    def test_page_runs_are_ints_only(self):
        self.assertEqual(PT.page_runs([1, 2, 3, 5, 9, 8]), "1-3,5,9-8")
        self.assertEqual(PT.page_runs([7]), "7")


class SplitPlanning(unittest.TestCase):
    def plan(self, mode, pages_text="", every=2, count=12):
        return PT.plan_split({"split-pdf.mode": mode, "split-pdf.every": every, "split-pdf.pages": pages_text}, count)

    def test_each(self):
        self.assertEqual(self.plan("each", count=3), [[1], [2], [3]])
        self.assertEqual(self.plan("each", "2-3, 9"), [[2], [3], [9]])

    def test_every(self):
        self.assertEqual(self.plan("every", every=5, count=12), [[1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11, 12]])
        self.assertEqual(self.plan("every", "4-9", every=4), [[4, 5, 6, 7], [8, 9]])

    def test_ranges_and_extract(self):
        self.assertEqual(self.plan("ranges", "1-3, 5, 8-end"), [[1, 2, 3], [5], [8, 9, 10, 11, 12]])
        self.assertEqual(self.plan("extract", "5-3, 1"), [[5, 4, 3, 1]])
        for mode in ("ranges", "extract"):
            with self.assertRaises(PT.ToolError):
                self.plan(mode, "")

    def test_too_many_outputs(self):
        with self.assertRaises(PT.ToolError):
            self.plan("each", count=2001)
        self.assertEqual(len(self.plan("each", count=2000)), 2000)

    def test_labels(self):
        label = PT.split_label
        self.assertEqual(label([5], 1, "each"), "page 5")
        self.assertEqual(label([1, 2, 3], 1, "ranges"), "pages 1-3")
        self.assertEqual(label([1, 4], 2, "ranges"), "part 2")
        self.assertEqual(label([3, 2], 3, "ranges"), "part 3")
        self.assertEqual(label([1, 4], 1, "extract"), "selected pages")


class SplitRuns(Base):
    def test_each_default(self):
        names = self.split()
        self.assertEqual(names, sorted(f"doc (page {n}).pdf" for n in range(1, 13)))

    def test_every(self):
        self.assertEqual(self.split("split-pdf.mode=every", "split-pdf.every=5"),
                         ["doc (pages 1-5).pdf", "doc (pages 11-12).pdf", "doc (pages 6-10).pdf"])

    def test_every_odd_tail_is_one_page(self):
        self.assertEqual(self.split("split-pdf.mode=every", "split-pdf.every=5", "split-pdf.pages=1-11"),
                         ["doc (page 11).pdf", "doc (pages 1-5).pdf", "doc (pages 6-10).pdf"])

    def test_ranges(self):
        src = self.fresh(self.pdf12)
        names = self.split("split-pdf.mode=ranges", "split-pdf.pages=1-3, 5, 8-end, 2-1, 4,7", src=src)
        self.assertIn("doc (pages 1-3).pdf", names)
        self.assertIn("doc (pages 8-12).pdf", names)
        self.assertIn("doc (part 4).pdf", names)   # 2-1 is reversed, not ascending
        self.assertIn("doc (page 5).pdf", names)
        self.assertEqual(len(names), 6)

    def test_extract_contiguous_and_not(self):
        self.assertEqual(self.split("split-pdf.mode=extract", "split-pdf.pages=2-4"), ["doc (pages 2-4).pdf"])
        self.assertEqual(self.split("split-pdf.mode=extract", "split-pdf.pages=1,4,9"),
                         ["doc (selected pages).pdf"])

    def test_extract_page_counts_and_order(self):
        src = self.fresh(self.pdf12)
        self.split("split-pdf.mode=extract", "split-pdf.pages=1,4,9,end", src=src)
        out = src.parent / "doc (selected pages).pdf"
        n = subprocess.run(["qpdf", "--show-npages", str(out)], capture_output=True, text=True).stdout.strip()
        self.assertEqual(n, "4")

    def test_pages_restrict_each(self):
        self.assertEqual(self.split("split-pdf.pages=2-3"), ["doc (page 2).pdf", "doc (page 3).pdf"])

    def test_past_the_end_makes_nothing(self):
        src = self.fresh(self.pdf12)
        proc = self.tool("run", "--tool", "split-pdf", "--opt", "split-pdf.pages=14", "--", src)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("page 14 is past the end (12 pages)", proc.stderr)
        self.assertEqual([p.name for p in src.parent.iterdir()], ["doc.pdf"])

    def test_progress_per_output(self):
        proc = self.tool("run", "--tool", "split-pdf", "--progress", "--opt", "split-pdf.mode=every",
                         "--opt", "split-pdf.every=4", "--", self.fresh(self.pdf12))
        events = [json.loads(l) for l in proc.stdout.splitlines()]
        pct = [e["pct"] for e in events if e["event"] == "progress"]
        self.assertEqual(pct, [33.3, 66.7, 100.0])
        done = [e for e in events if e["event"] == "done"][0]
        self.assertEqual(len(done["outputs"]), 3)

    def test_hostile_name_with_ranges(self):
        src = self.fresh(self.pdf12, "@x.pdf")
        names = self.split("split-pdf.mode=ranges", "split-pdf.pages=1-2, 5", src=src)
        self.assertEqual(names, ["@x (page 5).pdf", "@x (pages 1-2).pdf"])

    def test_saved_defaults_apply(self):
        self.assertEqual(self.peel("config", "set", "tools.split-pdf.mode", "every").returncode, 0)
        self.assertEqual(self.peel("config", "set", "tools.split-pdf.every", "6").returncode, 0)
        src = self.fresh(self.pdf12)
        self.assertEqual(self.tool("run", "--tool", "split-pdf", "--", src).returncode, 0)
        self.assertEqual(sorted(p.name for p in src.parent.iterdir() if p != src),
                         ["doc (pages 1-6).pdf", "doc (pages 7-12).pdf"])
        # --opt beats the saved value
        self.assertEqual(self.split("split-pdf.every=12", src=self.fresh(self.pdf12, "b.pdf")),
                         ["b (pages 1-12).pdf"])


class CheckInfoTargets(Base):
    def test_info(self):
        proc = self.tool("info", "--json", "--", self.pdf12, self.png)
        data = json.loads(proc.stdout)
        self.assertEqual(data["files"], [{"path": str(self.pdf12), "kind": "pdf", "pages": 12},
                                         {"path": str(self.png), "kind": "image"}])

    def test_check_ok(self):
        self.assertEqual(self.check("split-pdf", "split-pdf.mode=every", "split-pdf.every=3"),
                         {"ok": True, "error": "", "outputs": 4,
                          "summary": "4 PDFs: pages 1-3, 4-6, 7-9, 10-12"})

    def test_check_writes_nothing(self):
        src = self.fresh(self.pdf12)
        self.check("split-pdf", files=[src])
        self.assertEqual([p.name for p in src.parent.iterdir()], ["doc.pdf"])

    def test_check_errors_are_ok_false_exit_0(self):
        r = self.check("split-pdf", "split-pdf.pages=14")
        self.assertEqual((r["ok"], r["outputs"], r["summary"]), (False, 0, ""))
        self.assertEqual(r["error"], "doc.pdf: page 14 is past the end (12 pages)")
        r = self.check("split-pdf", "split-pdf.mode=extract")
        self.assertFalse(r["ok"])
        self.assertIn("pages", r["error"])
        r = self.check("split-pdf", "split-pdf.mode=bogus")
        self.assertFalse(r["ok"])
        self.assertTrue(r["error"].startswith("split-pdf.mode must be one of"))
        r = self.check("split-pdf", "nope=1")
        self.assertFalse(r["ok"])
        r = self.check("split-pdf", "split-pdf.pages=1-", )
        self.assertFalse(r["ok"])
        r = self.check("split-pdf", files=[self.png])
        self.assertFalse(r["ok"])
        r = self.check("rotate", "rotate.angle=45", files=[self.png])
        self.assertFalse(r["ok"])

    def test_check_several_files(self):
        other = self.fresh(self.pdf12, "b.pdf")
        r = self.check("split-pdf", "split-pdf.mode=every", "split-pdf.every=6", files=[self.pdf12, other])
        self.assertEqual((r["ok"], r["outputs"]), (True, 4))
        self.assertEqual(r["summary"], "2 PDFs: pages 1-6, 7-12")

    def test_check_summary_truncates(self):
        r = self.check("split-pdf")
        self.assertLessEqual(len(r["summary"]), 120)
        self.assertTrue(r["summary"].startswith("12 PDFs: pages 1, 2, 3"))
        self.assertTrue(r["summary"].endswith("…") or len(r["summary"]) < 120)

    def test_check_other_tools(self):
        r = self.check("rotate", "rotate.angle=180", files=[self.png])
        self.assertEqual((r["ok"], r["outputs"], r["summary"]), (True, 1, "Rotate 180°"))

    def test_targets_options_and_ask(self):
        def tools():
            data = json.loads(self.tool("targets", "--json", "--", self.pdf12).stdout)
            return {t["id"]: t for t in data["tools"]}
        t = tools()
        self.assertEqual(t["split-pdf"]["options"], ["split-pdf.mode", "split-pdf.every", "split-pdf.parts", "split-pdf.pages",
                                                  "split-pdf.folder"])
        self.assertTrue(t["split-pdf"]["ask"])
        self.assertEqual(t["strip-metadata"], {"id": "strip-metadata", "label": "Remove info",
                                              "options": [], "ask": False})
        self.assertFalse(t["compress"]["ask"])
        self.assertEqual(t["rotate"]["options"], ["rotate.angle", "rotate.pages"])
        self.peel("config", "set", "tools.ask", "always")
        t = tools()
        self.assertTrue(t["compress"]["ask"] and t["rotate"]["ask"] and t["split-pdf"]["ask"])
        self.assertFalse(t["strip-metadata"]["ask"])
        self.peel("config", "set", "tools.ask", "never")
        self.assertFalse(any(x["ask"] for x in tools().values()))


class OptRejection(Base):
    def reject(self, tool_id, opt, src=None):
        src = src or self.fresh(self.pdf12)
        proc = self.tool("run", "--tool", tool_id, "--opt", opt, "--", src)
        self.assertEqual(proc.returncode, 1, opt)
        self.assertEqual(len(proc.stderr.strip().splitlines()), 1, proc.stderr)
        self.assertEqual([p.name for p in src.parent.iterdir()], [src.name], "work started before validation")

    def test_rejects(self):
        for tool_id, opt in (("split-pdf", "split-pdf.mode=zip"), ("split-pdf", "split-pdf.every=0"),
                             ("split-pdf", "split-pdf.every=501"), ("split-pdf", "split-pdf.every=x"),
                             ("split-pdf", "split-pdf.pages=1,,2"), ("split-pdf", "split-pdf.pages=-rf"),
                             ("split-pdf", "rotate.angle=90"), ("split-pdf", "nope"),
                             ("split-pdf", "ask=never"), ("rotate", "rotate.angle=45"),
                             ("strip-metadata", "compress.level=light"), ("merge-pdf", "x=1")):
            with self.subTest(opt=opt):
                self.reject(tool_id, opt)

    def test_rejects_before_any_file_of_many(self):
        a, b = self.fresh(self.pdf12, "a.pdf", True), self.fresh(self.pdf12, "b.pdf", True)
        proc = self.tool("run", "--tool", "split-pdf", "--opt", "split-pdf.mode=zip", "--", a, b)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(sorted(p.name for p in self.work.iterdir()), ["a.pdf", "b.pdf"])


class ConfigTools(Base):
    def cfg_json(self):
        proc = self.peel("config", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_defaults(self):
        data = self.cfg_json()
        self.assertEqual(data["config"]["tools"], {})
        self.assertEqual(data["effectiveTools"], {
            "ask": "pdf", "split-pdf.mode": "each", "split-pdf.every": 2, "rotate.angle": 90,
            "split-pdf.parts": 2, "split-pdf.folder": False, "merge-pdf.mode": "append",
            "resize-half.scale": 50, "compress.level": "medium", "snapshot.at": 10,
            "trim-silence.threshold": -50})
        self.assertEqual(data["options"]["tools"], json.loads((ROOT / "registry" / "tool-options.json").read_text())["fields"])

    def test_set_get_default(self):
        self.assertEqual(self.peel("config", "set", "tools.rotate.angle", "270").returncode, 0)
        self.assertEqual(self.peel("config", "set", "tools.compress.level", "strong").returncode, 0)
        self.assertEqual(self.peel("config", "set", "tools.snapshot.at", "100").returncode, 0)
        self.assertEqual(self.peel("config", "set", "tools.trim-silence.threshold", "-40").returncode, 0)
        data = self.cfg_json()
        self.assertEqual(data["config"]["tools"], {"rotate.angle": 270, "compress.level": "strong",
                                                   "snapshot.at": 100, "trim-silence.threshold": -40})
        self.assertEqual(data["effectiveTools"]["rotate.angle"], 270)
        self.assertEqual(self.peel("config", "set", "tools.rotate.angle", "default").returncode, 0)
        data = self.cfg_json()
        self.assertNotIn("rotate.angle", data["config"]["tools"])
        self.assertEqual(data["effectiveTools"]["rotate.angle"], 90)

    def test_refusals(self):
        for key, value in (("split-pdf.pages", "1-3"), ("nope", "1"), ("rotate.angle", "45"),
                           ("rotate.angle", "x"), ("split-pdf.every", "0"), ("ask", "maybe"),
                           ("compress.level", "ultra"), ("snapshot.at", "101")):
            with self.subTest(key=key, value=value):
                proc = self.peel("config", "set", f"tools.{key}", value)
                self.assertEqual(proc.returncode, 1)
                self.assertEqual(len(proc.stderr.strip().splitlines()), 1)
        self.assertEqual(self.cfg_json()["config"]["tools"], {})
        self.assertEqual(self.peel("config", "set", "tools.split-pdf.pages", "default").returncode, 1)

    def test_bad_stored_entries_warn_and_drop(self):
        (self.cfg / "peel").mkdir(parents=True)
        (self.cfg / "peel" / "config.json").write_text(json.dumps({"tools": {
            "rotate.angle": 180, "split-pdf.pages": "1-3", "bogus": 1, "compress.level": "ultra"}}))
        proc = self.peel("config", "--json")
        self.assertEqual(json.loads(proc.stdout)["config"]["tools"], {"rotate.angle": 180})
        self.assertEqual(len(proc.stderr.strip().splitlines()), 3)
        (self.cfg / "peel" / "config.json").write_text(json.dumps({"tools": []}))
        proc = self.peel("config", "--json")
        self.assertEqual(json.loads(proc.stdout)["config"]["tools"], {})
        self.assertIn("'tools' must be an object", proc.stderr)

    def test_text_listing(self):
        out = self.peel("config").stdout
        self.assertIn("tools.rotate.angle = 90 (default)", out)


class RealRuns(Base):
    def test_rotate_pdf(self):
        src = self.fresh(self.pdf12)
        proc = self.tool("run", "--tool", "rotate", "--opt", "rotate.angle=270", "--", src)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = Path(proc.stdout.strip())
        self.assertEqual(out.name, "doc (rotated).pdf")
        dump = subprocess.run(["qpdf", "--json", str(out)], capture_output=True, text=True).stdout
        self.assertEqual(dump.count('"/Rotate": 270'), 12)

    def test_rotate_pdf_default(self):
        out = Path(self.tool("run", "--tool", "rotate", "--", self.fresh(self.pdf12)).stdout.strip())
        dump = subprocess.run(["qpdf", "--json", str(out)], capture_output=True, text=True).stdout
        self.assertEqual(dump.count('"/Rotate": 90'), 12)

    def test_snapshot_at_100(self):
        for at in ("0", "100"):
            with self.subTest(at=at):
                src = self.fresh(self.mp4, f"v{at}.mp4")
                proc = self.tool("run", "--tool", "snapshot", "--opt", f"snapshot.at={at}", "--", src)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                out = Path(proc.stdout.strip())
                self.assertEqual(out.name, f"v{at} (frame).png")
                self.assertGreater(out.stat().st_size, 0)

    def test_trim_threshold_runs(self):
        out = Path(self.tool("run", "--tool", "trim-silence", "--opt", "trim-silence.threshold=-40", "--",
                             self.fresh(self.wav)).stdout.strip())
        self.assertEqual(out.name, "base (trimmed).wav")

    def test_resize_scale_runs(self):
        out = Path(self.tool("run", "--tool", "resize-half", "--opt", "resize-half.scale=25", "--",
                             self.fresh(self.png)).stdout.strip())
        ident = subprocess.run(["magick", "identify", "-format", "%w", str(out)], capture_output=True,
                               text=True).stdout
        self.assertEqual(ident, "16")


SCALE_VF = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
VMAP = ["-map", "0:v:0", "-map", "0:a?", "-sn", "-dn", "-map_metadata", "0"]
FF_HEAD = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-protocol_whitelist", "file,pipe"]


def ff(post, muxer, pre=()):
    return FF_HEAD + list(pre) + ["-i", "file:IN"] + post + ["-progress", "pipe:1", "-nostats", "-f", muxer, "OUT"]


def norm(rows):
    """Blank the temp output name (random) so argv can be compared."""
    def one(arg):
        m = re.search(r"(-sOutputFile=)?(file:)?(/\S*/)?\.peel-tool-[0-9a-f]+\.\w+$", arg)
        return arg if not m else (m.group(1) or "") + "OUT"
    return [[one(a) for a in row] for row in rows]


def h264(crf, abr, faststart=True):
    base = ["-c:v", "libx264", "-preset", "medium", "-crf", crf, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", abr]
    return base + (["-movflags", "+faststart"] if faststart else [])


class OldBehaviourArgv(Base):
    """Default options must give exactly the argv the fixed presets used."""

    def argv(self, tool_id, src, *opts):
        return norm(self.run_fake(tool_id, src, *opts))

    def test_compress_image_medium(self):
        for opts in ((), ("compress.level=medium",)):
            self.assertEqual(self.argv("compress", self.fresh(self.png), *opts),
                             [["magick", "PNG:-", "-auto-orient", "-strip", "-resize", "2560x2560>",
                               "-quality", "75", "PNG:-"]])

    def test_compress_image_levels(self):
        light = self.argv("compress", self.fresh(self.png), "compress.level=light")[0]
        strong = self.argv("compress", self.fresh(self.png), "compress.level=strong")[0]
        self.assertEqual(light[3:8], ["-strip", "-resize", "3840x3840>", "-quality", "85"])
        self.assertEqual(strong[3:8], ["-strip", "-resize", "1920x1920>", "-quality", "60"])

    def test_compress_video(self):
        src = self.fresh(self.mp4)
        want = [ff(VMAP + ["-vf", SCALE_VF] + h264("28", "128k"), "mp4")]
        self.assertEqual(self.argv("compress", src), want)
        self.assertEqual(self.argv("compress", src, "compress.level=medium"), want)
        self.assertEqual(self.argv("compress", src, "compress.level=light"),
                         [ff(VMAP + ["-vf", SCALE_VF] + h264("23", "160k"), "mp4")])
        self.assertEqual(self.argv("compress", src, "compress.level=strong"),
                         [ff(VMAP + ["-vf", SCALE_VF] + h264("33", "96k"), "mp4")])

    def test_compress_webm(self):
        src = self.fresh(self.mp4, "clip.webm")
        vp9 = lambda crf, opus: ["-c:v", "libvpx-vp9", "-crf", crf, "-b:v", "0", "-row-mt", "1",
                                 "-c:a", "libopus", "-b:a", opus]
        # The fake ffprobe-able container is mp4 named .webm: ffprobe sniffs content, so this still runs.
        self.assertEqual(self.argv("compress", src), [ff(VMAP + ["-vf", SCALE_VF] + vp9("38", "96k"), "webm")])
        self.assertEqual(self.argv("compress", src, "compress.level=light"),
                         [ff(VMAP + ["-vf", SCALE_VF] + vp9("33", "128k"), "webm")])
        self.assertEqual(self.argv("compress", src, "compress.level=strong"),
                         [ff(VMAP + ["-vf", SCALE_VF] + vp9("43", "64k"), "webm")])

    def test_compress_audio(self):
        mp3 = lambda b: [ff(["-vn", "-sn", "-dn", "-map", "0:a:0", "-map_metadata", "0",
                             "-c:a", "libmp3lame", "-b:a", b], "mp3")]
        src = self.fresh(self.mp3)
        self.assertEqual(self.argv("compress", src), mp3("128k"))
        self.assertEqual(self.argv("compress", src, "compress.level=light"), mp3("160k"))
        self.assertEqual(self.argv("compress", src, "compress.level=strong"), mp3("96k"))

    def test_compress_pdf(self):
        def gs(preset):
            return [["gs", "-sDEVICE=pdfwrite", f"-dPDFSETTINGS={preset}", "-dCompatibilityLevel=1.5", "-dSAFER",
                     "-dBATCH", "-dNOPAUSE", "-dQUIET", "-sOutputFile=OUT", "-f", "IN"]]
        src = self.fresh(self.pdf12)
        self.assertEqual(self.argv("compress", src), gs("/ebook"))
        self.assertEqual(self.argv("compress", src, "compress.level=light"), gs("/printer"))
        self.assertEqual(self.argv("compress", src, "compress.level=strong"), gs("/screen"))

    def test_saved_level_is_used(self):
        self.peel("config", "set", "tools.compress.level", "strong")
        got = self.argv("compress", self.fresh(self.pdf12))
        self.assertIn("-dPDFSETTINGS=/screen", got[0])
        got = self.argv("compress", self.fresh(self.pdf12, "b.pdf"), "compress.level=light")
        self.assertIn("-dPDFSETTINGS=/printer", got[0])

    def test_resize_default(self):
        self.assertEqual(self.argv("resize-half", self.fresh(self.png)),
                         [["magick", "PNG:-", "-auto-orient", "-resize", "50%", "PNG:-"]])
        self.assertEqual(self.argv("resize-half", self.fresh(self.png, "c.png"), "resize-half.scale=75")[0][3:5],
                         ["-resize", "75%"])
        vf = lambda d: [ff(VMAP + ["-vf", f"scale=trunc(iw/{d})*2:trunc(ih/{d})*2"] + h264("23", "160k"), "mp4")]
        self.assertEqual(self.argv("resize-half", self.fresh(self.mp4)), vf("4"))
        self.assertEqual(self.argv("resize-half", self.fresh(self.mp4, "d.mp4"), "resize-half.scale=25"), vf("8"))

    def test_rotate_default(self):
        self.assertEqual(self.argv("rotate", self.fresh(self.png)),
                         [["magick", "PNG:-", "-auto-orient", "-rotate", "90", "PNG:-"]])
        self.assertEqual(self.argv("rotate", self.fresh(self.png, "c.png"), "rotate.angle=270")[0][3:5],
                         ["-rotate", "270"])
        vf = lambda t: [ff(VMAP + ["-vf", f"{t},pad=ceil(iw/2)*2:ceil(ih/2)*2"] + h264("23", "160k"), "mp4")]
        self.assertEqual(self.argv("rotate", self.fresh(self.mp4)), vf("transpose=1"))
        self.assertEqual(self.argv("rotate", self.fresh(self.mp4, "d.mp4"), "rotate.angle=270"), vf("transpose=2"))
        self.assertEqual(self.argv("rotate", self.fresh(self.mp4, "e.mp4"), "rotate.angle=180"),
                         vf("transpose=1,transpose=1"))

    def test_snapshot_default(self):
        got = self.argv("snapshot", self.fresh(self.mp4))
        self.assertEqual(got, [ff(["-map", "0:v:0", "-frames:v", "1", "-c:v", "png", "-update", "1"],
                                  "image2", pre=["-ss", "0.200"])])
        end = self.argv("snapshot", self.fresh(self.mp4, "e.mp4"), "snapshot.at=100")
        self.assertLess(float(end[0][end[0].index("-ss") + 1]), 2.0)
        self.assertGreater(float(end[0][end[0].index("-ss") + 1]), 1.5)

    def test_trim_default(self):
        edge = "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05"
        got = self.argv("trim-silence", self.fresh(self.wav))
        self.assertEqual(got, [ff(["-vn", "-sn", "-dn", "-map", "0:a:0", "-map_metadata", "0", "-af",
                                   f"{edge},areverse,{edge},areverse", "-c:a", "pcm_s16le"], "wav")])
        got = self.argv("trim-silence", self.fresh(self.wav, "b.wav"), "trim-silence.threshold=-60")
        self.assertIn(f"{edge.replace('-50', '-60')},areverse,{edge.replace('-50', '-60')},areverse", got[0])


def peel_tool_pages(text, count=12):
    return PT.resolve_pages(PT.parse_pages(text), count)


class GrammarRound2(unittest.TestCase):
    def test_odd_even_step(self):
        self.assertEqual(peel_tool_pages("odd"), [[1, 3, 5, 7, 9, 11]])
        self.assertEqual(peel_tool_pages("EVEN"), [[2, 4, 6, 8, 10, 12]])
        self.assertEqual(peel_tool_pages("1-end:3"), [[1, 4, 7, 10]])
        self.assertEqual(peel_tool_pages("2-9 : 4"), [[2, 6]])
        self.assertEqual(peel_tool_pages("11-1:5"), [[11, 6, 1]])
        self.assertEqual(peel_tool_pages("odd, 2-4"), [[1, 3, 5, 7, 9, 11], [2, 3, 4]])

    def test_bad_new_syntax(self):
        for bad in ("5:2", "1-5:0", "1-5:", "1-5:x", "odd:2", "end:2", "oddeven", "1-5:2:3", "1-5:-2"):
            with self.subTest(bad=bad):
                with self.assertRaises(PT.ToolError):
                    PT.parse_pages(bad)
                with self.assertRaises(PL.PeelError):
                    PL.check_pages(bad)
        for good in ("odd", "even", "1-5:2", "1-end:2", "3-1:2"):
            PL.check_pages(good)

    def test_reference_cap(self):
        PT.resolve_pages(PT.parse_pages(",".join(["1-500"] * 20)), 500)   # exactly 10000
        with self.assertRaises(PT.ToolError):
            PT.resolve_pages(PT.parse_pages(",".join(["1-500"] * 20) + ",1"), 500)

    def test_descending_runs(self):
        self.assertEqual(PT.page_runs([10, 9, 8, 7, 3, 4, 5, 1]), "10-7,3-5,1")
        self.assertEqual(PT.page_runs([2000 - i for i in range(2000)]), "2000-1")
        self.assertEqual(PT.page_runs([5, 4]), "5-4")
        self.assertEqual(PT.split_summary([[10, 9, 8, 7, 6, 5, 4, 3, 2, 1]]),
                         "1 PDF: pages 10-1")

    def plan(self, mode, text="", **extra):
        o = {"split-pdf.mode": mode, "split-pdf.every": 2, "split-pdf.parts": 2, "split-pdf.pages": text,
             "split-pdf.folder": False, **extra}
        return PT.plan_split(o, 12)

    def test_remove(self):
        self.assertEqual(self.plan("remove", "2-3, odd"), [[4, 6, 8, 10, 12]])
        self.assertEqual(self.plan("remove", "end"), [list(range(1, 12))])
        with self.assertRaises(PT.ToolError):
            self.plan("remove", "")
        with self.assertRaises(PT.ToolError):
            self.plan("remove", "1-end")

    def test_parts(self):
        self.assertEqual([len(g) for g in self.plan("parts", **{"split-pdf.parts": 5})], [3, 3, 2, 2, 2])
        self.assertEqual(self.plan("parts", "3-6", **{"split-pdf.parts": 2}), [[3, 4], [5, 6]])
        self.assertEqual([len(g) for g in self.plan("parts", **{"split-pdf.parts": 12})], [1] * 12)
        with self.assertRaises(PT.ToolError):
            self.plan("parts", **{"split-pdf.parts": 13})


class Round2Runs(Base):
    def test_check_parts_remove_rotate_pages(self):
        r = self.check("split-pdf", "split-pdf.mode=parts", "split-pdf.parts=5")
        self.assertEqual(r, {"ok": True, "error": "", "outputs": 5,
                             "summary": "5 PDFs: pages 1-3, 4-6, 7-8, 9-10, 11-12"})
        r = self.check("split-pdf", "split-pdf.mode=remove", "split-pdf.pages=2-3, odd")
        self.assertEqual(r["summary"], "1 PDF: pages 4+6+8+10+12")
        self.assertEqual((r["ok"], r["outputs"]), (True, 1))
        r = self.check("rotate", "rotate.pages=1-3")
        self.assertEqual((r["ok"], r["summary"]), (True, "Rotate 90°, pages 1-3"))
        self.assertFalse(self.check("rotate", "rotate.pages=13")["ok"])
        # ignored for non-PDF kinds
        self.assertTrue(self.check("rotate", "rotate.pages=13", files=[self.png])["ok"])

    def test_remove_run(self):
        src = self.fresh(self.pdf12)
        self.assertEqual(self.split("split-pdf.mode=remove", "split-pdf.pages=2-3, odd", src=src),
                         ["doc (selected pages).pdf"])
        n = subprocess.run(["qpdf", "--show-npages", str(src.parent / "doc (selected pages).pdf")],
                           capture_output=True, text=True).stdout.strip()
        self.assertEqual(n, "5")

    def test_parts_run(self):
        self.assertEqual(self.split("split-pdf.mode=parts", "split-pdf.parts=5"),
                         ["doc (pages 1-3).pdf", "doc (pages 11-12).pdf", "doc (pages 4-6).pdf",
                          "doc (pages 7-8).pdf", "doc (pages 9-10).pdf"])

    def test_descending_extract_run(self):
        src = self.fresh(self.pdf12)
        self.split("split-pdf.mode=extract", "split-pdf.pages=12-1", src=src)
        self.assertEqual(subprocess.run(["qpdf", "--show-npages", str(src.parent / "doc (selected pages).pdf")],
                                        capture_output=True, text=True).stdout.strip(), "12")

    def test_folder(self):
        src = self.fresh(self.pdf12)
        self.assertEqual(self.tool("run", "--tool", "split-pdf", "--opt", "split-pdf.mode=every",
                                   "--opt", "split-pdf.every=6", "--opt", "split-pdf.folder=true", "--", src).returncode, 0)
        self.assertEqual(sorted(p.name for p in src.parent.iterdir()), ["doc (split)", "doc.pdf"])
        self.assertEqual(sorted(p.name for p in (src.parent / "doc (split)").iterdir()),
                         ["doc (pages 1-6).pdf", "doc (pages 7-12).pdf"])
        self.tool("run", "--tool", "split-pdf", "--opt", "split-pdf.mode=every", "--opt", "split-pdf.every=6",
                  "--opt", "split-pdf.folder=true", "--", src)
        self.assertIn("doc (split) (1)", [p.name for p in src.parent.iterdir()])

    def test_folder_single_output_stays_flat(self):
        src = self.fresh(self.pdf12)
        self.split("split-pdf.mode=extract", "split-pdf.pages=1-2", "split-pdf.folder=true", src=src)
        self.assertEqual(sorted(p.name for p in src.parent.iterdir()), ["doc (pages 1-2).pdf", "doc.pdf"])

    def test_folder_cleaned_on_failure(self):
        src = self.fresh(self.pdf12)
        d = src.parent
        fake = self.tmp / "failbin"
        fake.mkdir(exist_ok=True)
        q = fake / "qpdf"
        real = shutil.which("qpdf")
        q.write_text(f"""#!/bin/sh
case "$1" in --show-npages) exec {real} "$@";; esac
echo x >> "$(dirname "$0")/calls"
if [ "$(wc -l < "$(dirname "$0")/calls")" -ge 3 ]; then echo boom >&2; exit 2; fi
exec {real} "$@"
""")
        q.chmod(0o755)
        (fake / "calls").unlink(missing_ok=True)
        env = self.env()
        env["PATH"] = f"{fake}{os.pathsep}{env['PATH']}"
        proc = subprocess.run([str(TOOL), "run", "--tool", "split-pdf", "--opt", "split-pdf.folder=true",
                               "--", str(src)], capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual([p.name for p in d.iterdir()], ["doc.pdf"])

    def test_rotate_pages_run(self):
        src = self.fresh(self.pdf12)
        out = Path(self.tool("run", "--tool", "rotate", "--opt", "rotate.angle=180",
                             "--opt", "rotate.pages=1-3, 12", "--", src).stdout.strip())
        dump = subprocess.run(["qpdf", "--json", str(out)], capture_output=True, text=True).stdout
        self.assertEqual(dump.count('"/Rotate": 180'), 4)

    def test_rotate_pages_ignored_for_images(self):
        out = Path(self.tool("run", "--tool", "rotate", "--opt", "rotate.pages=1-3", "--", self.fresh(self.png)).stdout.strip())
        self.assertTrue(out.exists())

    def test_ask_forced_for_pages_modes(self):
        def ask():
            d = json.loads(self.tool("targets", "--json", "--", self.pdf12).stdout)
            return {t["id"]: t["ask"] for t in d["tools"]}["split-pdf"]
        self.peel("config", "set", "tools.ask", "never")
        self.assertFalse(ask())
        for mode in ("ranges", "extract", "remove"):
            self.peel("config", "set", "tools.split-pdf.mode", mode)
            self.assertTrue(ask(), mode)
        self.peel("config", "set", "tools.split-pdf.mode", "parts")
        self.assertFalse(ask())

    def test_huge_selection_rejected_by_check_and_run(self):
        big = self.tmp / "big2000.pdf"
        if not big.exists():
            sh("qpdf", "--empty", "--pages", *([str(self.pdf12)] * 167), "--", str(big))
        pages = ",".join(["2000-1"] * 40)
        r = self.check("split-pdf", "split-pdf.mode=extract", "split-pdf.pages=" + pages,
                       files=[big])
        self.assertFalse(r["ok"])
        self.assertIn("10000", r["error"])
        proc = self.tool("run", "--tool", "split-pdf", "--progress", "--opt", "split-pdf.mode=extract",
                         "--opt", "split-pdf.pages=" + pages, "--", self.fresh(big))
        self.assertEqual(proc.returncode, 1)
        events = [json.loads(l) for l in proc.stdout.splitlines()]
        self.assertEqual(events[-1]["event"], "finished")
        self.assertNotIn("Traceback", proc.stderr)

    def test_long_descending_extract_ok(self):
        big = self.tmp / "big2000.pdf"
        if not big.exists():
            sh("qpdf", "--empty", "--pages", *([str(self.pdf12)] * 167), "--", str(big))
        src = self.fresh(big)
        self.split("split-pdf.mode=extract", "split-pdf.pages=2000-1, 2000-1, 1-2000", src=src)

    def test_oserror_from_popen_is_a_file_error(self):
        # An argv too long makes Popen raise OSError; run() turns it into ToolError.
        with self.assertRaises(PT.ToolError):
            PT.run(["true", "x" * 200000], 5)

    def test_sigterm_mid_split_leaves_nothing(self):
        import signal
        import time
        big = self.tmp / "big600.pdf"
        if not big.exists():
            sh("qpdf", "--empty", "--pages", *([str(self.pdf12)] * 50), "--", str(big))
        src = self.fresh(big)
        proc = subprocess.Popen([str(TOOL), "run", "--tool", "split-pdf", "--", str(src)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env())
        deadline = time.time() + 60
        while time.time() < deadline and sum(1 for p in src.parent.iterdir() if "(page" in p.name) < 5:
            time.sleep(0.05)
        self.assertGreaterEqual(sum(1 for p in src.parent.iterdir() if "(page" in p.name), 5)
        proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=60)
        self.assertEqual([p.name for p in src.parent.iterdir()], [src.name])

    def test_percent_directory_gs(self):
        d = self.work / "100%d"
        d.mkdir()
        src = d / "doc.pdf"
        shutil.copy(self.pdf12, src)
        proc = self.tool("run", "--tool", "compress", "--", src)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["doc (compressed).pdf", "doc.pdf"])

    def test_check_lossless_audio_matches_run(self):
        r = self.check("compress", files=[self.wav])
        self.assertEqual((r["ok"], r["error"]), (False, "base.wav: lossless audio, nothing to compress"))
        self.assertTrue(self.check("compress", files=[self.mp3])["ok"])


class MergeRound3(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # a: 4 pages 100pt wide, b: 3 pages 200 wide, c: 2 pages 300 wide
        cls.srcs = {}
        for name, width, n in (("a", 100, 4), ("b", 200, 3), ("c", 300, 2)):
            one = cls.base / f"{name}1.pdf"
            sh("magick", "-size", f"{width}x50", "xc:white", f"PDF:{one}")
            out = cls.base / f"{name}.pdf"
            sh("qpdf", "--empty", "--pages", *([str(one)] * n), "--", str(out))
            cls.srcs[name] = out

    def files(self, *names, same_dir=True):
        return [self.fresh(self.srcs[n], f"{n}.pdf", same_dir) for n in names]

    def widths(self, path):
        out = subprocess.run(["magick", "identify", "-format", "%w ", str(path)], capture_output=True,
                             text=True).stdout.split()
        return [int(w) for w in out]

    def merge(self, files, *opts, expect=0):
        argv = ["run", "--tool", "merge-pdf"]
        for o in opts:
            argv += ["--opt", o]
        proc = self.tool(*argv, "--", *files)
        self.assertEqual(proc.returncode, expect, proc.stderr)
        return proc

    def result(self, files, *opts):
        out = Path(self.merge(files, *opts).stdout.strip())
        self.assertTrue(out.name.startswith("a (merged)"), out.name)
        return self.widths(out)

    def chk(self, files, *opts):
        argv = ["check", "--json", "--tool", "merge-pdf"]
        for o in opts:
            argv += ["--opt", o]
        return json.loads(self.tool(*argv, "--", *files).stdout)

    def test_append_default_and_per_file_pages(self):
        a, b, c = self.files("a", "b", "c")
        self.assertEqual(self.result([a, b, c]), [100] * 4 + [200] * 3 + [300] * 2)
        self.assertEqual(self.result([a, b, c], "merge-pdf.pages.1=2-3", "merge-pdf.pages.3=end, 1"),
                         [100] * 2 + [200] * 3 + [300] * 2)
        self.assertEqual(self.result([a, b, c], "merge-pdf.pages.2=odd"), [100] * 4 + [200] * 2 + [300] * 2)

    def test_reordering_files_changes_result(self):
        a, b, c = self.files("a", "b", "c")
        proc = self.merge([c, a], "merge-pdf.pages.1=2")
        out = Path(proc.stdout.strip())
        self.assertEqual(out.name, "c (merged).pdf")
        self.assertEqual(self.widths(out), [300] + [100] * 4)

    def test_insert_positions(self):
        a, b, c = self.files("a", "b", "c")
        ins = ["merge-pdf.mode=insert"]
        self.assertEqual(self.result([a, b], *ins, "merge-pdf.at=0"), [200] * 3 + [100] * 4)
        self.assertEqual(self.result([a, b], *ins, "merge-pdf.at=2"), [100] * 2 + [200] * 3 + [100] * 2)
        self.assertEqual(self.result([a, b, c], *ins, "merge-pdf.at=4"), [100] * 4 + [200] * 3 + [300] * 2)
        # base selection: at counts within the selected pages of the base
        self.assertEqual(self.result([a, c], *ins, "merge-pdf.at=1", "merge-pdf.pages.1=3-4"),
                         [100] + [300] * 2 + [100])

    def test_at_past_the_end(self):
        a, b = self.files("a", "b")
        r = self.chk([a, b], "merge-pdf.mode=insert", "merge-pdf.at=5")
        self.assertEqual((r["ok"], r["error"]), (False, "page 5 is past the end of a.pdf (4 pages)"))
        proc = self.merge([a, b], "merge-pdf.mode=insert", "merge-pdf.at=5", expect=1)
        self.assertIn("page 5 is past the end of a.pdf (4 pages)", proc.stderr)
        self.assertEqual(sorted(p.name for p in self.work.iterdir()), ["a.pdf", "b.pdf"])

    def test_bad_indexes(self):
        a, b = self.files("a", "b")
        for opt in ("merge-pdf.pages.0=1", "merge-pdf.pages.3=1", "merge-pdf.pages.x=1", "merge-pdf.pages.1.5=1",
                    "merge-pdf.pages.-1=1", "merge-pdf.pages=1", "merge-pdf.pages.1=1,,2", "merge-pdf.pages.2=9"):
            with self.subTest(opt=opt):
                proc = self.merge([a, b], opt, expect=1)
                self.assertEqual(len(proc.stderr.strip().splitlines()), 1)
                r = self.chk([a, b], opt)
                self.assertFalse(r["ok"])
        self.assertEqual(sorted(p.name for p in self.work.iterdir()), ["a.pdf", "b.pdf"])

    def test_hostile_names(self):
        x = self.fresh(self.srcs["a"], "@x.pdf", True)
        y = self.fresh(self.srcs["b"], "-rf $(touch PWNED).pdf", True)
        out = Path(self.merge([x, y], "merge-pdf.pages.1=1-2").stdout.strip())
        self.assertEqual(out.name, "@x (merged).pdf")
        self.assertEqual(self.widths(out), [100] * 2 + [200] * 3)
        self.assertFalse(any(p.name.startswith("PWNED") for p in self.work.iterdir()))

    def test_cap_across_files(self):
        big = self.tmp / "big500.pdf"
        if not big.exists():
            sh("qpdf", "--empty", "--pages", *([str(self.srcs["a"])] * 125), "--", str(big))
        f1, f2 = self.fresh(big, "p.pdf", True), self.fresh(big, "q.pdf", True)
        sel = ",".join(["1-500"] * 10)   # 5000 each; together 10000 is the limit
        r = self.chk([f1, f2], f"merge-pdf.pages.1={sel}", f"merge-pdf.pages.2={sel}")
        self.assertTrue(r["ok"], r)
        r = self.chk([f1, f2], f"merge-pdf.pages.1={sel}", f"merge-pdf.pages.2={sel},1")
        self.assertFalse(r["ok"])
        self.assertIn("10000", r["error"])
        proc = self.merge([f1, f2], f"merge-pdf.pages.1={sel}", f"merge-pdf.pages.2={sel},1", expect=1)
        self.assertEqual([p.name for p in self.work.iterdir() if "merged" in p.name], [])

    def test_check_summaries_match_run(self):
        a, b, c = self.files("a", "b", "c")
        r = self.chk([a, b, c])
        self.assertEqual(r, {"ok": True, "error": "", "outputs": 1, "summary": "1 PDF, 9 pages from 3 files"})
        r = self.chk([a, b, c], "merge-pdf.mode=insert", "merge-pdf.at=3", "merge-pdf.pages.2=1-2")
        self.assertEqual(r["summary"], "1 PDF, 8 pages: 4 inserted after page 3 of a.pdf")
        got = self.result([a, b, c], "merge-pdf.mode=insert", "merge-pdf.at=3", "merge-pdf.pages.2=1-2")
        self.assertEqual(len(got), 8)
        self.assertEqual(got, [100] * 3 + [200] * 2 + [300] * 2 + [100])
        r = self.chk([a, b], "merge-pdf.pages.2=9")
        self.assertEqual((r["ok"], r["error"]), (False, "b.pdf: page 9 is past the end (3 pages)"))
        self.assertFalse(self.chk([a])["ok"])
        self.assertFalse(self.chk([a, self.png])["ok"])

    def test_ask_mapping_and_migration(self):
        def asks():
            d = json.loads(self.tool("targets", "--json", "--", self.pdf12, self.pdf12).stdout)
            return {t["id"]: t["ask"] for t in d["tools"]}
        a = asks()
        self.assertTrue(a["merge-pdf"] and a["split-pdf"])
        self.assertFalse(a["compress"])
        self.peel("config", "set", "tools.ask", "never")
        a = asks()
        self.assertFalse(a["merge-pdf"] or a["split-pdf"])
        self.peel("config", "set", "tools.ask", "always")
        self.assertTrue(all(v for k, v in asks().items() if k != "strip-metadata"))
        # a saved "split" loads as pdf, no warning
        (self.cfg / "peel").mkdir(parents=True, exist_ok=True)
        (self.cfg / "peel" / "config.json").write_text(json.dumps({"tools": {"ask": "split"}}))
        proc = self.peel("config", "--json")
        self.assertEqual(proc.stderr, "")
        d = json.loads(proc.stdout)
        self.assertEqual((d["config"]["tools"]["ask"], d["effectiveTools"]["ask"]), ("pdf", "pdf"))
        a = asks()
        self.assertTrue(a["merge-pdf"] and a["split-pdf"] and not a["compress"])
        self.assertEqual(self.peel("config", "set", "tools.ask", "split").returncode, 0)

    def test_config_refuses_merge_one_shots(self):
        for key, value in (("merge-pdf.pages", "1-2"), ("merge-pdf.at", "2"), ("merge-pdf.pages.1", "1")):
            self.assertEqual(self.peel("config", "set", f"tools.{key}", value).returncode, 1, key)
        self.assertEqual(self.peel("config", "set", "tools.merge-pdf.mode", "insert").returncode, 0)
        a, b = self.files("a", "b")
        out = Path(self.merge([a, b]).stdout.strip())     # saved mode insert, at 0
        self.assertEqual(self.widths(out), [200] * 3 + [100] * 4)


if __name__ == "__main__":
    unittest.main()
