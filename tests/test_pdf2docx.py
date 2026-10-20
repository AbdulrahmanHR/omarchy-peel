"""PDF -> DOCX through a FAKE pdf2docx on PATH (the real one is optional).

    python3 -I -m unittest tests.test_pdf2docx
"""

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PEEL = ROOT / "bin" / "peel"
CONFIG = tempfile.mkdtemp(prefix="peel-test-config-")

FAKE = """#!/usr/bin/env python3
import os, shutil, sys
d = os.path.dirname(os.path.abspath(__file__))
open(os.path.join(d, "argv.log"), "a").write(repr(sys.argv[1:]) + "\\n")
mode = open(os.path.join(d, "mode")).read().strip()
if mode == "good":
    shutil.copy(os.path.join(d, "fixture.docx"), sys.argv[3])
elif mode == "garbage":
    open(sys.argv[3], "wb").write(b"not a zip at all")
elif mode == "empty":
    open(sys.argv[3], "wb").close()
"""


def peel(*args, path):
    env = dict(os.environ, XDG_CONFIG_HOME=CONFIG, PATH=path)
    return subprocess.run([str(PEEL), *map(str, args)], capture_output=True, text=True,
                          timeout=300, env=env)


class Pdf2DocxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("soffice") or not shutil.which("pdftotext"):
            raise unittest.SkipTest("soffice needed to build the docx fixture")
        cls.root = Path(tempfile.mkdtemp(prefix="peel-p2d-"))
        cls.fake = cls.root / "fakebin"
        cls.fake.mkdir()
        (cls.fake / "pdf2docx").write_text(FAKE)
        (cls.fake / "pdf2docx").chmod(0o755)
        txt = cls.root / "fixture.txt"
        txt.write_text("hello\n")
        out = subprocess.run([str(PEEL), "convert", "--to", "docx", str(txt)], capture_output=True,
                             text=True, env=dict(os.environ, XDG_CONFIG_HOME=CONFIG))
        assert out.returncode == 0, out.stderr
        shutil.move(cls.root / "fixture.docx", cls.fake / "fixture.docx")
        cls.with_fake = f"{cls.fake}:{os.environ['PATH']}"
        cls.without = os.pathsep.join(p for p in os.environ["PATH"].split(os.pathsep)
                                      if not (Path(p) / "pdf2docx").exists())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="peel-p2d-job-", dir=self.root))
        (self.fake / "argv.log").unlink(missing_ok=True)

    def mode(self, name):
        (self.fake / "mode").write_text(name)

    def pdf(self, name="doc.pdf"):
        path = self.dir / name
        path.write_bytes(b"%PDF-1.4\n%%EOF\n")
        return path

    def leftovers(self):
        return sorted(p.name for p in self.dir.iterdir() if p.name.startswith("."))

    def test_targets_gated_on_tool(self):
        pdf = self.pdf()
        with_ = peel("targets", pdf, path=self.with_fake)
        self.assertIn("docx", with_.stdout.split())
        without = peel("targets", pdf, path=self.without)
        self.assertNotIn("docx", without.stdout.split())

    def test_conversion_publishes_next_to_source(self):
        self.mode("good")
        pdf = self.pdf()
        (self.dir / "doc.docx").write_text("keep")
        proc = peel("convert", "--to", "docx", pdf, path=self.with_fake)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual((self.dir / "doc.docx").read_text(), "keep")
        self.assertTrue((self.dir / "doc (1).docx").stat().st_size > 0)
        self.assertEqual(self.leftovers(), [])

    def test_failures(self):
        for mode in ("none", "empty", "garbage"):
            with self.subTest(mode=mode):
                self.mode(mode)
                pdf = self.pdf(f"{mode}.pdf")
                proc = peel("convert", "--to", "docx", pdf, path=self.with_fake)
                self.assertEqual(proc.returncode, 1)
                self.assertIn("pdf2docx produced no output", proc.stderr)
                self.assertFalse((self.dir / f"{mode}.docx").exists())
                self.assertEqual(self.leftovers(), [])

    def test_hostile_names_never_reach_argv(self):
        self.mode("good")
        for name in ("--force=1.pdf", "-x.pdf"):
            with self.subTest(name=name):
                (self.fake / "argv.log").unlink(missing_ok=True)
                proc = peel("convert", "--to", "docx", self.pdf(name), path=self.with_fake)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                argv = eval((self.fake / "argv.log").read_text().splitlines()[0])
                self.assertEqual(argv[0], "convert")
                self.assertEqual(Path(argv[1]).name, "input.pdf")
                self.assertEqual(Path(argv[2]).name, "out.docx")
                self.assertTrue(all(a == "convert" or not a.startswith("-") for a in argv))
                self.assertTrue(all("=" not in Path(a).name for a in argv))
                self.assertTrue((self.dir / (name[:-4] + ".docx")).exists())


if __name__ == "__main__":
    unittest.main()
