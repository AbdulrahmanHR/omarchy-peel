import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
EXT = os.path.join(HERE, "..", "nautilus", "peel.py")
PEEL = os.path.normpath(os.path.join(HERE, "..", "bin", "peel"))


class FakeMenuItem:
    def __init__(self, name="", label="", tip="", icon=""):
        self.name, self.label, self.submenu, self.handlers = name, label, None, []

    def set_submenu(self, menu):
        self.submenu = menu

    def connect(self, _sig, fn, *args):
        self.handlers.append((fn, args))

    def activate(self):
        for fn, args in self.handlers:
            fn(self, *args)


class FakeMenu:
    def __init__(self):
        self.items = []

    def append_item(self, item):
        self.items.append(item)


class FakeFile:
    def __init__(self, path, scheme="file", directory=False):
        self.path, self.scheme, self.directory = path, scheme, directory

    def get_uri_scheme(self):
        return self.scheme

    def is_directory(self):
        return self.directory

    def get_location(self):
        return types.SimpleNamespace(get_path=lambda: self.path)


def load_extension():
    gi = types.ModuleType("gi")
    gi.require_version = lambda *a, **k: None
    repo = types.ModuleType("gi.repository")
    nautilus = types.SimpleNamespace(
        MenuProvider=type('MenuProvider', (), {}), MenuItem=FakeMenuItem, Menu=FakeMenu
    )
    repo.GObject = types.SimpleNamespace(GObject=type('GObject', (), {}))
    repo.Nautilus = nautilus
    gi.repository = repo
    sys.modules.update({"gi": gi, "gi.repository": repo})
    spec = importlib.util.spec_from_file_location("peel_nautilus_ext", EXT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(shutil.which("magick"), "ImageMagick required")
class NautilusExtTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.png = os.path.join(cls.tmp, "a.png")
        subprocess.run(["magick", "-size", "8x8", "xc:red", "PNG:" + cls.png], check=True)
        # Unknown extension and content that sniffs as application/octet-stream
        cls.txt = os.path.join(cls.tmp, "n.xyz")
        with open(cls.txt, "wb") as f:
            f.write(bytes(range(256)) * 4)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.mod = load_extension()
        self.mod.find_peel = lambda: PEEL
        self.ext = self.mod.PeelAction()

    def test_png_submenu(self):
        items = self.ext.get_file_items([FakeFile(self.png)])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].label, "Convert to")
        labels = [i.label for i in items[0].submenu.items]
        self.assertIn("WebP", labels)
        self.assertNotIn("PNG", labels)

    def test_legacy_signature(self):
        items = self.ext.get_file_items(None, [FakeFile(self.png)])
        self.assertEqual(len(items), 1)

    def test_no_items_for_dir_txt_remote(self):
        self.assertEqual(self.ext.get_file_items([FakeFile(self.tmp, directory=True)]), [])
        self.assertEqual(self.ext.get_file_items([FakeFile(self.txt)]), [])
        self.assertEqual(self.ext.get_file_items([FakeFile(self.png, scheme="smb")]), [])

    def test_no_peel_no_items(self):
        self.mod.find_peel = lambda: None
        self.assertEqual(self.ext.get_file_items([FakeFile(self.png)]), [])

    def test_activate_popen(self):
        items = self.ext.get_file_items([FakeFile(self.png)])
        entry = next(i for i in items[0].submenu.items if i.label == "WebP")
        calls = []
        real = subprocess.Popen
        subprocess.Popen = lambda argv, **kw: calls.append((argv, kw))
        try:
            entry.activate()
        finally:
            subprocess.Popen = real
        argv, kw = calls[0]
        self.assertEqual(argv, [PEEL, "convert", "--to", "webp", "--notify", "--", self.png])
        self.assertTrue(kw["start_new_session"])
        self.assertEqual(kw["stdin"], subprocess.DEVNULL)
        self.assertEqual(kw["stdout"], subprocess.DEVNULL)
        self.assertEqual(kw["stderr"], subprocess.DEVNULL)

    def test_cache(self):
        calls = []
        real = self.mod.subprocess.run
        self.mod.subprocess.run = lambda *a, **k: (calls.append(a), real(*a, **k))[1]
        try:
            self.ext.get_file_items([FakeFile(self.png)])
            self.ext.get_file_items([FakeFile(self.png)])
        finally:
            self.mod.subprocess.run = real
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
