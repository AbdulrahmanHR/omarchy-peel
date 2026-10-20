"""Security hardening tests for bin/peel and bin/peel-tool.

    python3 -I -m unittest discover -s tests -p 'test_hardening*' -v
"""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.dom.minidom
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PEEL = ROOT / "bin" / "peel"
TOOL = ROOT / "bin" / "peel-tool"


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def run(script, *args, config):
    return subprocess.run([str(script), *map(str, args)], capture_output=True, text=True, timeout=600,
                          env=dict(os.environ, XDG_CONFIG_HOME=str(config)))


def sh(*argv):
    subprocess.run(argv, check=True, capture_output=True, timeout=120)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="peel-hard-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.config = self.tmp / "config"
        self.config.mkdir()
        self.work = self.tmp / "work"
        self.work.mkdir()

    def listing(self, d):
        return sorted(p.name for p in Path(d).iterdir())

    def png(self, path):
        sh("magick", "-size", "20x20", "gradient:orange-blue", f"PNG:{path}")


class DemuxerTrust(Base):
    def splice_fixture(self):
        sh("ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
           "sine=frequency=440:duration=1", f"file:{self.work / 'secret.wav'}")
        clip = self.work / "clip.mp4"
        clip.write_text("ffconcat version 1.0\nfile secret.wav\n")
        return clip

    def test_peel_refuses_concat_disguised_as_mp4(self):
        clip = self.splice_fixture()
        before = self.listing(self.work)
        proc = run(PEEL, "convert", "--to", "webm", clip, config=self.config)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("unsafe media container", proc.stderr)
        self.assertEqual(self.listing(self.work), before)

    def test_peel_tool_refuses_concat_disguised_as_mp4(self):
        clip = self.splice_fixture()
        before = self.listing(self.work)
        for tool_id in ("compress", "extract-audio", "snapshot", "strip-metadata"):
            proc = run(TOOL, "run", "--tool", tool_id, "--", clip, config=self.config)
            self.assertEqual(proc.returncode, 1, tool_id)
            self.assertIn("unsafe media container", proc.stderr)
        self.assertEqual(self.listing(self.work), before)

    def test_real_media_still_works(self):
        wav = self.work / "ok.wav"
        sh("ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
           "sine=frequency=440:duration=1", f"file:{wav}")
        proc = run(PEEL, "convert", "--to", "mp3", wav, config=self.config)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class ArchiveBomb(Base):
    def setUp(self):
        super().setUp()
        self.peel = load(PEEL, "peel_bomb")

    def make_zip(self, entries, size):
        src = self.work / "bomb.zip"
        with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
            for i in range(entries):
                with z.open(f"f{i}.bin", "w", force_zip64=True) as fh:
                    for _ in range(size // (1 << 20)):
                        fh.write(bytes(1 << 20))
        return src

    def test_too_many_entries(self):
        src = self.make_zip(10, 0)
        self.peel.ARCHIVE_MAX_ENTRIES = 5
        stage = self.work / "stage"
        stage.mkdir()
        with self.assertRaisesRegex(self.peel.PeelError, "too many entries"):
            self.peel.extract_archive(src, "zip", stage)
        self.assertEqual(list(stage.iterdir()), [])

    def test_total_size_over_ratio_limit(self):
        src = self.make_zip(1, 8 << 20)  # ~8 MiB of zeros, a few KiB compressed
        self.peel.ARCHIVE_ALLOWANCE = 1 << 20
        stage = self.work / "stage"
        stage.mkdir()
        with self.assertRaisesRegex(self.peel.PeelError, "would unpack"):
            self.peel.extract_archive(src, "zip", stage)
        self.assertEqual(list(stage.iterdir()), [])

    def test_cli_refuses_real_bomb(self):
        src = self.make_zip(1, 1100 << 20)  # just over the 1 GiB allowance
        self.assertLess(src.stat().st_size, 5 << 20)
        proc = run(PEEL, "convert", "--to", "tar.gz", src, config=self.config)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("would unpack", proc.stderr)
        self.assertEqual(self.listing(self.work), ["bomb.zip"])

    def test_normal_archive_passes(self):
        src = self.make_zip(2, 2 << 20)
        proc = run(PEEL, "convert", "--to", "tar", src, config=self.config)
        self.assertEqual(proc.returncode, 0, proc.stderr)


@unittest.skipUnless(shutil.which("soffice"), "soffice not installed")
class MacroProfile(Base):
    def test_profile_helper_writes_lockdown(self):
        peel = load(PEEL, "peel_profile")
        profile = self.work / "profile"
        profile.mkdir()
        peel.write_office_profile(profile)
        xcu = (profile / "user" / "registrymodifications.xcu").read_text()
        xml.dom.minidom.parseString(xcu)
        self.assertRegex(xcu, r'MacroSecurityLevel"[^>]*><value>3</value>')
        self.assertRegex(xcu, r'DisableMacrosExecution"[^>]*><value>true</value>')
        self.assertIn("/org.openoffice.Office.Common/Security/Scripting", xcu)

    def test_conversion_seeds_profile(self):
        peel = load(PEEL, "peel_profile2")
        seen = []
        real = peel.write_office_profile
        peel.write_office_profile = lambda profile: (real(profile), seen.append(profile))
        src = self.work / "a.txt"
        src.write_text("hello")
        peel.convert_soffice(src, "txt", "odt", self.work)
        self.assertEqual(len(seen), 1)
        self.assertTrue((seen[0] / "user" / "registrymodifications.xcu").is_file())


class SymlinkedInputs(Base):
    def links(self):
        a, b = self.tmp / "A", self.tmp / "B"
        a.mkdir()
        b.mkdir()
        self.png(b / "real.png")
        (a / "link.png").symlink_to("../B/real.png")
        return a, b

    def test_peel_output_beside_link(self):
        a, b = self.links()
        proc = run(PEEL, "convert", "--to", "webp", a / "link.png", config=self.config)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), str(a / "link.webp"))
        self.assertEqual(self.listing(a), ["link.png", "link.webp"])
        self.assertEqual(self.listing(b), ["real.png"])

    def test_peel_tool_output_beside_link(self):
        a, b = self.links()
        proc = run(TOOL, "run", "--tool", "to-grayscale", "--", a / "link.png", config=self.config)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), str(a / "link (gray).png"))
        self.assertEqual(self.listing(b), ["real.png"])

    def test_dangling_or_directory_link_refused(self):
        (self.work / "dead.png").symlink_to("nowhere.png")
        (self.work / "dir.png").symlink_to(self.tmp)
        for name in ("dead.png", "dir.png"):
            self.assertEqual(run(PEEL, "convert", "--to", "webp", self.work / name,
                                 config=self.config).returncode, 1)


class ToolOutputFolder(Base):
    def setUp(self):
        super().setUp()
        self.src = self.work / "pic.png"
        self.png(self.src)
        self.dest = self.tmp / "dest"
        self.dest.mkdir()

    def set_config(self, location, folder):
        (self.config / "peel").mkdir(exist_ok=True)
        (self.config / "peel" / "config.json").write_text(
            json.dumps({"output": {"location": location, "folder": folder}}))

    def test_folder_is_honoured(self):
        self.set_config("folder", str(self.dest))
        proc = run(TOOL, "run", "--tool", "to-grayscale", "--", self.src, config=self.config)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.listing(self.dest), ["pic (gray).png"])
        self.assertEqual(self.listing(self.work), ["pic.png"])

    def test_merge_goes_to_folder(self):
        self.set_config("folder", str(self.dest))
        pdfs = []
        for n in (1, 2):
            pdf = self.work / f"p{n}.pdf"
            sh("magick", str(self.src), str(pdf))
            pdfs.append(pdf)
        proc = run(TOOL, "run", "--tool", "merge-pdf", "--", *pdfs, config=self.config)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.listing(self.dest), ["p1 (merged).pdf"])
        self.assertEqual(self.listing(self.work), ["p1.pdf", "p2.pdf", "pic.png"])

    def test_missing_folder_warns_once_and_falls_back(self):
        self.set_config("folder", str(self.tmp / "gone"))
        proc = run(TOOL, "run", "--tool", "to-grayscale", "--progress", "--", self.src, self.src,
                   config=self.config)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        events = [json.loads(l) for l in proc.stdout.splitlines()]
        self.assertEqual(len([e for e in events if e["event"] == "warning"]), 1)
        self.assertEqual(self.listing(self.work), ["pic (gray) (1).png", "pic (gray).png", "pic.png"])

    def test_missing_folder_warns_on_stderr_without_progress(self):
        self.set_config("folder", str(self.tmp / "gone"))
        proc = run(TOOL, "run", "--tool", "to-grayscale", "--", self.src, config=self.config)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("saving next to the originals", proc.stderr)


if __name__ == "__main__":
    unittest.main()
