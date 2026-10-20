"""End-to-end tests for bin/peel, run against the real converters.

    python3 -I -m unittest discover -s tests -v
    PEEL_FULL=1 ...   also runs every input -> output pair (a few minutes)
"""

import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import urllib.parse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PEEL = ROOT / "bin" / "peel"
REGISTRY = json.loads((ROOT / "registry" / "formats.json").read_text())


# Never read the real ~/.config/peel: conversions must run with default settings.
ISOLATED_CONFIG = tempfile.mkdtemp(prefix="peel-test-config-")


def peel(*args, check=True):
    proc = subprocess.run([str(PEEL), *map(str, args)], capture_output=True, text=True, timeout=600,
                          env=dict(os.environ, XDG_CONFIG_HOME=ISOLATED_CONFIG))
    if check and proc.returncode != 0:
        raise AssertionError(f"peel {' '.join(map(str, args))} failed:\n{proc.stderr}")
    return proc


def sh(*argv):
    subprocess.run(argv, check=True, capture_output=True, timeout=120)


def probe(path):
    """Container format name per ffprobe, or the ImageMagick format."""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=format_name",
                          "-of", "csv=p=0", f"file:{path}"], capture_output=True, text=True)
    return out.stdout.strip()


def identify(path):
    with open(path, "rb") as fin:
        out = subprocess.run(["magick", "identify", "-format", "%m\n", "-"], stdin=fin,
                             capture_output=True, text=True)
    return out.stdout.split("\n")[0].strip()


HAVE = {tool: bool(shutil.which(tool)) for tool in
        ("soffice", "pdftoppm", "pdftotext", "pandoc", "bsdtar", "7z")}

FODP = """<?xml version="1.0" encoding="UTF-8"?>
<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0"
 xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
 office:version="1.3" office:mimetype="application/vnd.oasis.opendocument.presentation">
<office:body><office:presentation>
%s
</office:presentation></office:body></office:document>"""
SLIDE = """<draw:page draw:name="page%d"><draw:frame svg:x="2cm" svg:y="2cm" svg:width="10cm" svg:height="3cm">
<draw:text-box><text:p>Slide number %d</text:p></draw:text-box></draw:frame></draw:page>"""


def office(src, filter_name, outdir, infilter=None):
    """Reference LibreOffice conversion used only to build fixtures."""
    profile = tempfile.mkdtemp(prefix="peel-test-profile-")
    try:
        argv = ["soffice", "--headless", "--norestore", f"-env:UserInstallation=file://{profile}"]
        if infilter:
            argv.append(f"--infilter={infilter}")
        sh(*argv, "--convert-to", filter_name, "--outdir", str(outdir), str(src))
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def clean_dir(path):
    return not any(p.name.startswith(".") for p in Path(path).iterdir())


class Fixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="peel-test-"))
        cls.base_png = cls.tmp / "base.png"
        cls.base_mp4 = cls.tmp / "base.mp4"
        cls.base_wav = cls.tmp / "base.wav"
        cls.base_svg = cls.tmp / "base.svg"
        sh("magick", "-size", "65x47", "gradient:orange-blue", f"PNG:{cls.base_png}")
        sh("ffmpeg", "-nostdin", "-y", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc=size=66x48:rate=10:duration=1",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
           "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", f"file:{cls.base_mp4}")
        sh("ffmpeg", "-nostdin", "-y", "-loglevel", "error",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=1", f"file:{cls.base_wav}")
        sh("magick", "-size", "65x47", "gradient:red-blue", f"GIF:{cls.tmp / 'still.gif'}")
        sh("ffmpeg", "-nostdin", "-y", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10:duration=1", f"file:{cls.tmp / 'anim.gif'}")
        cls.base_svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="30">'
                                '<rect width="40" height="30" fill="#e8833a"/></svg>')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def fresh(self, src, name):
        """Copy a fixture into its own directory under a new name."""
        d = Path(tempfile.mkdtemp(dir=self.tmp))
        dst = d / name
        shutil.copy(src, dst)
        return dst


class OfficeFixtures(Fixtures):
    """Documents, spreadsheets, slides, a two-page PDF and archives, built at runtime."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not HAVE["soffice"]:
            return
        t = cls.tmp
        (t / "base.txt").write_text("Hello peel\nsecond line\n")
        (t / "base.csv").write_text("a,b,c\n1,2,3\n")
        (t / "base.fodp").write_text(FODP % (SLIDE % (1, 1) + SLIDE % (2, 2)))
        office(t / "base.txt", "docx", t)
        office(t / "base.csv", "xlsx", t)
        office(t / "base.fodp", "pptx", t)
        office(t / "base.fodp", "pdf", t)  # two slides -> two pages
        cls.base_txt, cls.base_csv = t / "base.txt", t / "base.csv"
        cls.base_docx, cls.base_xlsx = t / "base.docx", t / "base.xlsx"
        cls.base_pptx, cls.base_pdf = t / "base.pptx", t / "base.pdf"
        cls.base_zip, cls.base_tgz = t / "base.zip", t / "base.tar.gz"
        with zipfile.ZipFile(cls.base_zip, "w") as z:
            z.writestr("dir/one.txt", "one")
            z.writestr("two.txt", "two")
        with tarfile.open(cls.base_tgz, "w:gz") as tar:
            tar.add(cls.base_txt, arcname="dir/one.txt")
            tar.add(cls.base_csv, arcname="two.csv")


class Targets(Fixtures):
    def test_png_targets(self):
        out = json.loads(peel("targets", "--json", self.base_png).stdout)
        exts = [t["ext"] for t in out["convert"]]
        self.assertIn("webp", exts)
        self.assertNotIn("png", exts)
        self.assertNotIn("mp4", exts)

    def test_gif_offers_video_and_image_but_no_audio(self):
        exts = peel("targets", self.fresh(self.base_png, "a.gif")).stdout.split()
        self.assertIn("mp4", exts)
        self.assertIn("png", exts)
        self.assertNotIn("mp3", exts)

    def test_mixed_batch_is_intersection(self):
        jpg = self.fresh(self.base_png, "a.jpg")
        exts = peel("targets", self.base_png, jpg).stdout.split()
        self.assertIn("webp", exts)
        self.assertIn("png", exts)  # the jpg still needs converting
        self.assertEqual(peel("targets", self.base_png, self.base_wav).stdout.split(), [])

    def test_svg_is_input_only(self):
        exts = peel("targets", self.base_svg).stdout.split()
        self.assertEqual(exts, ["png", "pdf", "jpg", "webp"])
        self.assertNotEqual(peel("convert", "--to", "svg", self.base_png, check=False).returncode, 0)


class Convert(Fixtures):
    def test_png_to_webp_next_to_source(self):
        src = self.fresh(self.base_png, "photo.png")
        out = Path(peel("convert", "--to", "webp", src).stdout.strip())
        self.assertEqual(out, src.with_suffix(".webp"))
        self.assertEqual(identify(out), "WEBP")
        self.assertTrue(src.exists())

    def test_never_overwrites(self):
        src = self.fresh(self.base_png, "photo.png")
        first = Path(peel("convert", "--to", "jpg", src).stdout.strip())
        second = Path(peel("convert", "--to", "jpg", src).stdout.strip())
        self.assertEqual(first.name, "photo.jpg")
        self.assertEqual(second.name, "photo (1).jpg")
        self.assertEqual(sorted(p.name for p in src.parent.iterdir()),
                         ["photo (1).jpg", "photo.jpg", "photo.png"])  # no temp files left

    def test_video_to_gif_and_audio(self):
        src = self.fresh(self.base_mp4, "clip.mp4")
        gif = Path(peel("convert", "--to", "gif", src).stdout.strip())
        self.assertEqual(probe(gif), "gif")
        mp3 = Path(peel("convert", "--to", "mp3", src).stdout.strip())
        self.assertEqual(probe(mp3), "mp3")

    def test_odd_dimensions_to_mp4(self):
        src = self.fresh(self.base_png, "odd.gif")  # 65x47
        out = Path(peel("convert", "--to", "mp4", src).stdout.strip())
        self.assertIn("mp4", probe(out))

    def test_gif_to_webm(self):
        still = self.fresh(self.tmp / "still.gif", "still.gif")
        anim = self.fresh(self.tmp / "anim.gif", "anim.gif")
        for src in (still, anim):
            with self.subTest(src=src.name):
                out = Path(peel("convert", "--to", "webm", src).stdout.strip())
                self.assertEqual(out.suffix, ".webm")
                self.assertIn("webm", probe(out))

    def test_progress_events(self):
        src = self.fresh(self.base_mp4, "clip.mp4")
        lines = peel("convert", "--to", "webm", "--progress", src).stdout.splitlines()
        events = [json.loads(l)["event"] for l in lines]
        self.assertEqual(events[0], "start")
        self.assertEqual(events[-2:], ["done", "finished"])

    def test_file_uri_with_spaces_and_percent(self):
        src = self.fresh(self.base_png, "my 100% photo.png")
        uri = "file://" + urllib.parse.quote(str(src))
        out = Path(peel("convert", "--to", "jpg", uri).stdout.strip())
        self.assertEqual(out.name, "my 100% photo.jpg")

    def test_batch_with_one_bad_file(self):
        good = self.fresh(self.base_png, "good.png")
        bad = good.parent / "bad.png"
        bad.write_text("not an image")
        proc = peel("convert", "--to", "jpg", "--progress", good, bad, check=False)
        self.assertEqual(proc.returncode, 1)
        last = json.loads(proc.stdout.splitlines()[-1])
        self.assertEqual((last["ok"], last["failed"]), (1, 1))
        self.assertFalse(any(".peel-" in p.name for p in good.parent.iterdir()))

    def test_same_format_is_skipped(self):
        src = self.fresh(self.base_png, "same.png")
        lines = peel("convert", "--to", "png", "--progress", src).stdout.splitlines()
        self.assertEqual(json.loads(lines[-1])["skipped"], 1)


@unittest.skipUnless(HAVE["soffice"], "LibreOffice not installed")
class Documents(OfficeFixtures):
    def test_targets(self):
        exts = peel("targets", self.base_docx).stdout.split()
        for want in ("pdf", "odt", "txt", "html"):
            self.assertIn(want, exts)
        self.assertEqual("md" in exts and "epub" in exts, HAVE["pandoc"])

    def test_docx_to_pdf_and_txt(self):
        src = self.fresh(self.base_docx, "report.docx")
        pdf = Path(peel("convert", "--to", "pdf", src).stdout.strip())
        self.assertEqual(pdf, src.with_suffix(".pdf"))
        self.assertEqual(pdf.read_bytes()[:4], b"%PDF")
        txt = Path(peel("convert", "--to", "txt", src).stdout.strip())
        self.assertEqual(txt.read_bytes().splitlines()[0], b"Hello peel")  # no BOM
        self.assertTrue(clean_dir(src.parent))

    def test_txt_to_odt_and_html(self):
        src = self.fresh(self.base_txt, "note.txt")
        odt = Path(peel("convert", "--to", "odt", src).stdout.strip())
        self.assertTrue(zipfile.is_zipfile(odt))
        html = Path(peel("convert", "--to", "html", src).stdout.strip())
        self.assertIn("Hello peel", html.read_text())

    @unittest.skipUnless(HAVE["pandoc"], "pandoc not installed")
    def test_pandoc_targets(self):
        src = self.fresh(self.base_docx, "p.docx")
        md = Path(peel("convert", "--to", "md", src).stdout.strip())
        self.assertIn("Hello peel", md.read_text())
        epub = Path(peel("convert", "--to", "epub", md).stdout.strip())
        self.assertTrue(zipfile.is_zipfile(epub))

    def test_hostile_name_is_inert(self):
        name = "$(touch PWNED_SUB) -x;y|z.docx"
        src = self.fresh(self.base_docx, name)
        out = Path(peel("convert", "--to", "pdf", "--", src).stdout.strip())
        self.assertEqual(out.name, Path(name).stem + ".pdf")
        self.assertEqual(out.read_bytes()[:4], b"%PDF")
        self.assertEqual([p.name for p in src.parent.iterdir() if p.name.startswith("PWNED")], [])
        self.assertTrue(clean_dir(src.parent))

    def test_never_overwrites(self):
        src = self.fresh(self.base_docx, "same.docx")
        peel("convert", "--to", "pdf", src)
        second = Path(peel("convert", "--to", "pdf", src).stdout.strip())
        self.assertEqual(second.name, "same (1).pdf")

    def test_no_tools_no_targets(self):
        src = self.fresh(self.base_docx, "x.docx")
        env = {"PATH": "/nonexistent"}
        out = subprocess.run([sys.executable, "-I", str(PEEL), "targets", str(src)],
                             capture_output=True, text=True, env=env)
        self.assertEqual(out.stdout.split(), [])


@unittest.skipUnless(HAVE["soffice"], "LibreOffice not installed")
class Spreadsheets(OfficeFixtures):
    def test_xlsx_to_csv_tsv_pdf(self):
        src = self.fresh(self.base_xlsx, "sheet.xlsx")
        csv = Path(peel("convert", "--to", "csv", src).stdout.strip())
        self.assertEqual(csv.read_text().splitlines(), ["a,b,c", "1,2,3"])
        tsv = Path(peel("convert", "--to", "tsv", csv).stdout.strip())
        self.assertEqual(tsv.read_text().splitlines(), ["a\tb\tc", "1\t2\t3"])
        pdf = Path(peel("convert", "--to", "pdf", src).stdout.strip())
        self.assertEqual(pdf.read_bytes()[:4], b"%PDF")

    def test_csv_to_ods(self):
        src = self.fresh(self.base_csv, "data.csv")
        ods = Path(peel("convert", "--to", "ods", src).stdout.strip())
        self.assertTrue(zipfile.is_zipfile(ods))


@unittest.skipUnless(HAVE["soffice"] and HAVE["pdftoppm"], "LibreOffice and poppler needed")
class Slides(OfficeFixtures):
    def test_pptx_to_pdf_and_odp(self):
        src = self.fresh(self.base_pptx, "deck.pptx")
        self.assertEqual(Path(peel("convert", "--to", "pdf", src).stdout.strip()).read_bytes()[:4], b"%PDF")
        self.assertTrue(zipfile.is_zipfile(Path(peel("convert", "--to", "odp", src).stdout.strip())))

    def test_pptx_to_png_all_slides(self):
        src = self.fresh(self.base_pptx, "deck.pptx")
        lines = peel("convert", "--to", "png", "--progress", src).stdout.splitlines()
        done = json.loads(lines[-2])
        self.assertEqual([Path(o).name for o in done["outputs"]], ["deck-1.png", "deck-2.png"])
        self.assertEqual(done["output"], done["outputs"][0])
        self.assertEqual(identify(done["output"]), "PNG")
        self.assertTrue(clean_dir(src.parent))


@unittest.skipUnless(HAVE["soffice"] and HAVE["pdftoppm"] and HAVE["pdftotext"], "LibreOffice and poppler needed")
class Pdfs(OfficeFixtures):
    def test_docx_only_through_pdf2docx(self):
        # LibreOffice's PDF import is only text boxes, so DOCX is offered just
        # when pdf2docx is installed, and ODT never.
        exts = peel("targets", self.base_pdf).stdout.split()
        expected = ["png", "jpg", "txt"] + (["docx"] if shutil.which("pdf2docx") else [])
        self.assertEqual(exts, expected)

    def test_pdf_to_png_pages(self):
        src = self.fresh(self.base_pdf, "doc.pdf")
        outs = peel("convert", "--to", "png", src).stdout.split("\n")[:-1]
        self.assertEqual([Path(o).name for o in outs], ["doc-1.png", "doc-2.png"])
        again = peel("convert", "--to", "png", src).stdout.split("\n")[:-1]
        self.assertEqual([Path(o).name for o in again], ["doc-1 (1).png", "doc-2 (1).png"])
        jpg = peel("convert", "--to", "jpg", src).stdout.split("\n")[:-1]
        self.assertEqual([identify(j) for j in jpg], ["JPEG", "JPEG"])

    def test_pdf_to_txt(self):
        src = self.fresh(self.base_pdf, "doc.pdf")
        txt = Path(peel("convert", "--to", "txt", src).stdout.strip())
        self.assertIn("Slide number 2", txt.read_text())
        self.assertTrue(clean_dir(src.parent))

    def test_dash_names(self):
        src = self.fresh(self.base_pdf, "-r 5 x.pdf")
        out = Path(peel("convert", "--to", "txt", "--", src).stdout.strip())
        self.assertEqual(out.name, "-r 5 x.txt")


@unittest.skipUnless(HAVE["bsdtar"] and HAVE["soffice"], "bsdtar needed")
class Archives(OfficeFixtures):
    def names(self, path):
        if path.name.endswith(".zip"):
            return sorted(n for n in zipfile.ZipFile(path).namelist() if not n.endswith("/"))
        with tarfile.open(path) as tar:
            return sorted(m.name.removeprefix("./") for m in tar.getmembers() if m.isfile())

    def test_zip_to_targz_and_back(self):
        src = self.fresh(self.base_zip, "pack.zip")
        tgz = Path(peel("convert", "--to", "tar.gz", src).stdout.strip())
        self.assertEqual(tgz.name, "pack.tar.gz")
        self.assertEqual(self.names(tgz), ["dir/one.txt", "two.txt"])
        back = self.fresh(tgz, "arch.tar.gz")
        zipped = Path(peel("convert", "--to", "zip", back).stdout.strip())
        self.assertEqual(zipped.name, "arch.zip")  # both dots dropped
        self.assertEqual(self.names(zipped), ["dir/one.txt", "two.txt"])
        self.assertEqual(peel("convert", "--to", "tgz", back, "--progress").stdout.splitlines()[-2][:9], '{"event":')
        self.assertTrue(clean_dir(src.parent))

    @unittest.skipUnless(HAVE["7z"], "7z not installed")
    def test_targz_to_7z_and_tar(self):
        src = self.fresh(self.base_tgz, "bundle.tgz")
        z7 = Path(peel("convert", "--to", "7z", src).stdout.strip())
        self.assertEqual(z7.name, "bundle.7z")
        listing = subprocess.run(["7z", "l", "-ba", str(z7)], capture_output=True, text=True).stdout
        self.assertIn("one.txt", listing)
        tar = Path(peel("convert", "--to", "tar", z7).stdout.strip())
        self.assertEqual(self.names(tar), ["dir/one.txt", "two.csv"])

    def test_path_traversal_is_refused(self):
        outer = Path(tempfile.mkdtemp(dir=self.tmp))
        d = outer / "sub"
        d.mkdir()
        src = d / "evil.zip"
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("../evil.txt", "pwn")
            z.writestr("ok.txt", "ok")
        proc = peel("convert", "--to", "tar.gz", src, check=False)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse((outer / "evil.txt").exists())
        self.assertFalse((d / "evil.txt").exists())
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["evil.zip"])
        self.assertEqual(sorted(p.name for p in outer.iterdir()), ["sub"])

    def test_symlink_escape_is_refused(self):
        d = Path(tempfile.mkdtemp(dir=self.tmp))
        src = d / "link.tar"
        with tarfile.open(src, "w") as tar:
            info = tarfile.TarInfo("escape")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc"
            tar.addfile(info)
        self.assertEqual(peel("convert", "--to", "zip", src, check=False).returncode, 1)
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["link.tar"])


class HostileNames(Fixtures):
    NAMES = [
        "-rf.png",
        "label:pwned.png",
        "|touch PWNED_PIPE.png",
        "a[0].png",
        "$(touch PWNED_SUB).png",
        "x;touch PWNED_SEMI.png",
        "%d%s.png",
    ]

    def test_names_are_inert(self):
        for name in self.NAMES:
            with self.subTest(name=name):
                src = self.fresh(self.base_png, name)
                out = Path(peel("convert", "--to", "webp", "--", src).stdout.strip())
                self.assertEqual(out.name, Path(name).stem + ".webp")
                self.assertEqual(identify(out), "WEBP")
                # An injected `touch PWNED_*` would create a file starting with PWNED.
                leftovers = [p.name for p in src.parent.iterdir() if p.name.startswith("PWNED")]
                self.assertEqual(leftovers, [])

    def test_video_names_are_inert(self):
        src = self.fresh(self.base_mp4, "%03d|concat:x.mp4")
        out = Path(peel("convert", "--to", "mkv", "--", src).stdout.strip())
        self.assertIn("matroska", probe(out))


LEGACY = {"doc": ("base.docx", "MS Word 97"), "rtf": ("base.docx", "Rich Text Format"),
          "xls": ("base.xlsx", "MS Excel 97"), "ppt": ("base.pptx", "MS PowerPoint 97")}
PAGE_BASES = {"document": "base_docx", "spreadsheet": "base_xlsx", "slides": "base_pptx",
              "archive": "base_zip", "pdf": "base_pdf"}


@unittest.skipUnless(os.environ.get("PEEL_FULL"), "set PEEL_FULL=1 for the full matrix")
class FullMatrix(OfficeFixtures):
    def seed(self, key, fmt):
        """A sample file of this format, or None when no tool here can make one."""
        kinds = fmt["kinds"]
        if kinds[0] in PAGE_BASES:
            if not HAVE["soffice"]:
                return None
            base = getattr(self, PAGE_BASES[kinds[0]])
            if base.name.endswith("." + key):
                return self.fresh(base, f"seed.{key}")
            if key in LEGACY:
                d = Path(tempfile.mkdtemp(dir=self.tmp))
                office(self.tmp / LEGACY[key][0], f"{key}:{LEGACY[key][1]}", d)
                return d / f"base.{key}"
            if key in ("tar.xz", "tar.bz2"):
                path = Path(tempfile.mkdtemp(dir=self.tmp)) / f"seed.{key}"
                with tarfile.open(path, "w:" + key.split(".")[1]) as tar:
                    tar.add(self.base_txt, arcname="one.txt")
                return path
            copy = self.fresh(base, f"seed.{base.suffix[1:]}")
            if key not in peel("targets", copy).stdout.split():
                return None
            return Path(peel("convert", "--to", key, copy).stdout.strip().splitlines()[0])
        base = self.base_mp4 if "video" in kinds else \
            self.base_wav if "audio" in kinds else self.base_png
        seed = self.fresh(base, f"seed.{base.suffix[1:]}")
        if seed.suffix[1:] == key:
            return seed
        return Path(peel("convert", "--to", key, seed).stdout.strip())

    def test_every_pair(self):
        sources = {}
        for key, fmt in REGISTRY["formats"].items():
            if key in ("svg", "jxl", "aac"):
                continue
            src = self.seed(key, fmt)
            if src:
                sources[key] = src
        sources["svg"] = self.base_svg
        for key, src in sources.items():
            for target in peel("targets", src).stdout.split():
                with self.subTest(src=key, to=target):
                    copy = self.fresh(src, src.name)
                    out = Path(peel("convert", "--to", target, copy).stdout.splitlines()[0])
                    self.assertGreater(out.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
