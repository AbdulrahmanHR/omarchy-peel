"""Tests for `peel config` and bin/peel-binds (fake hyprctl, temp XDG_CONFIG_HOME)."""

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PEEL = ROOT / "bin" / "peel"
BINDS = ROOT / "bin" / "peel-binds"

FAKE_HYPRCTL = r'''#!/usr/bin/env python3
import json, os, sys
d = os.environ["FAKE_DIR"]
args = sys.argv[1:]
with open(os.path.join(d, "log"), "a") as f:
    f.write(json.dumps(args) + "\n")
if args[:1] == ["eval"]:
    n = len([x for x in os.listdir(d) if x.startswith("eval-")])
    open(os.path.join(d, f"eval-{n}.lua"), "w").write(args[1])
elif args == ["configerrors"]:
    p = os.path.join(d, "configerrors")
    sys.stdout.write(open(p).read() if os.path.exists(p) else "")
elif args == ["-j", "binds"]:
    evaled = any(x.startswith("eval-") for x in os.listdir(d))
    p = os.path.join(d, "binds_after.json" if evaled and os.path.exists(os.path.join(d, "binds_after.json")) else "binds_before.json")
    sys.stdout.write(open(p).read() if os.path.exists(p) else "[]")
'''


def bind(key, non_consuming=True, modmask=0):
    return {"key": key, "modmask": modmask, "non_consuming": non_consuming}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.cfg = t / "xdg"
        self.fake = t / "fake"
        self.fake.mkdir()
        bindir = t / "bin"
        bindir.mkdir()
        h = bindir / "hyprctl"
        h.write_text(FAKE_HYPRCTL)
        h.chmod(h.stat().st_mode | stat.S_IXUSR)
        self.env = dict(os.environ, XDG_CONFIG_HOME=str(self.cfg), FAKE_DIR=str(self.fake),
                        PATH=f"{bindir}:{os.environ['PATH']}")
        self.env.pop("PEEL_BIN", None)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cmd(self, script, *args):
        return subprocess.run([str(script), *args], capture_output=True, text=True, env=self.env, timeout=30)

    def peel(self, *args):
        return self.run_cmd(PEEL, *args)

    def write_cfg(self, text):
        (self.cfg / "peel").mkdir(parents=True, exist_ok=True)
        (self.cfg / "peel" / "config.json").write_text(text)

    def cfg_json(self):
        return json.loads(self.peel("config", "--json").stdout)


class ConfigTests(Base):
    def test_defaults_and_shape(self):
        out = self.cfg_json()
        self.assertEqual(out["config"], {"version": 1, "keys": {"convert": "Shift_L", "tools": "Control_L", "actions": "Alt_L"},
                                         "quality": "balanced", "output": {"location": "beside", "folder": ""}, "advanced": {}})
        self.assertIn("off", out["options"]["keys"])
        self.assertEqual(out["path"], str(self.cfg / "peel" / "config.json"))

    def test_partial_file_merges_defaults(self):
        self.write_cfg('{"version":1,"keys":{"tools":"Super_L"}}')
        keys = self.cfg_json()["config"]["keys"]
        self.assertEqual(keys, {"convert": "Shift_L", "tools": "Super_L", "actions": "Alt_L"})

    def test_invalid_files_fall_back_with_warning(self):
        for text in ["{not json", "[]", '{"keys":{"convert":"Hyper_L"}}',
                     '{"keys":{"convert":"Alt_L"}}', '{"keys":{"bogus":"Shift_R"}}']:
            self.write_cfg(text)
            proc = self.peel("config", "--json")
            self.assertEqual(proc.returncode, 0, text)
            self.assertEqual(json.loads(proc.stdout)["config"]["keys"]["convert"], "Shift_L", text)
            self.assertIn("invalid config", proc.stderr, text)

    def test_set_writes_and_roundtrips(self):
        self.assertEqual(self.peel("config", "set", "keys.convert", "Super_R").returncode, 0)
        self.assertEqual(self.cfg_json()["config"]["keys"]["convert"], "Super_R")
        written = json.loads((self.cfg / "peel" / "config.json").read_text())
        self.assertEqual(written["version"], 1)

    def test_set_off_can_repeat(self):
        self.peel("config", "set", "keys.convert", "off")
        self.assertEqual(self.peel("config", "set", "keys.tools", "off").returncode, 0)

    def test_set_rejects_bad_input(self):
        proc = self.peel("config", "set", "keys.convert", "Control_L")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("tools", proc.stderr)
        self.assertEqual(self.peel("config", "set", "keys.convert", "F13").returncode, 1)
        self.assertEqual(self.peel("config", "set", "keys.nope", "Shift_R").returncode, 1)
        self.assertEqual(self.peel("config", "set", "other.convert", "Shift_R").returncode, 1)
        self.assertFalse((self.cfg / "peel" / "config.json").exists())

    def test_atomic_write_leaves_no_temp_files(self):
        self.peel("config", "set", "keys.convert", "Shift_R")
        self.peel("config", "set", "keys.convert", "Super_L")
        self.assertEqual([p.name for p in (self.cfg / "peel").iterdir()], ["config.json"])


class BindsTests(Base):
    def setUp(self):
        super().setUp()
        self.after = [bind("Shift_L"), bind("Control_L"), bind("Alt_L"), bind("mouse:272"), bind("mouse:272")]
        self.before = []

    def stage(self, before=None, after=None):
        (self.fake / "binds_before.json").write_text(json.dumps(self.before if before is None else before))
        (self.fake / "binds_after.json").write_text(json.dumps(self.after if after is None else after))

    def log(self):
        p = self.fake / "log"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def evals(self):
        return [p.read_text() for p in sorted(self.fake.glob("eval-*.lua"))]

    def test_register_default_lua(self):
        self.stage()
        proc = self.run_cmd(BINDS, "register")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lua, = self.evals()
        opts = "{ non_consuming = true, dont_inhibit = true, submap_universal = true"
        for key, wheel in [("Shift_L", "convert"), ("Control_L", "tools"), ("Alt_L", "actions")]:
            self.assertIn(f'hl.bind("{key}", hl.dsp.event("peel arm {wheel}"), {opts} }})', lua)
        # ignore_mods, or a release with a modifier still held never reports "lmb up"
        self.assertIn(f'hl.bind("mouse:272", hl.dsp.event("peel lmb down"), {opts}, ignore_mods = true }})', lua)
        self.assertIn(f'hl.bind("mouse:272", hl.dsp.event("peel lmb up"), {opts}, release = true, ignore_mods = true }})', lua)
        # Handles from before ignore_mods are retired rather than re-enabled
        self.assertIn('want["mouse:272|peel lmb up|2"] = true', lua)
        self.assertNotIn('want["mouse:272|peel lmb up"] = true', lua)
        self.assertEqual(lua.count("hl.bind("), 5)
        self.assertNotIn("unbind", lua)
        self.assertEqual(json.loads(proc.stdout)["registered"], True)

    def test_custom_keys_and_off(self):
        self.peel("config", "set", "keys.convert", "Super_R")
        self.peel("config", "set", "keys.actions", "off")
        self.stage(after=[bind("Super_R"), bind("Control_L"), bind("mouse:272")])
        proc = self.run_cmd(BINDS, "register")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lua, = self.evals()
        self.assertIn('hl.bind("Super_R", hl.dsp.event("peel arm convert")', lua)
        self.assertIn('hl.bind("Control_L", hl.dsp.event("peel arm tools")', lua)
        self.assertNotIn("peel arm actions", lua)
        self.assertNotIn("Alt_L", lua)
        self.assertNotIn("Shift_L", lua)
        self.assertEqual(lua.count("hl.bind("), 4)
        # stale handles (e.g. old Shift_L) are disabled via the want-table
        self.assertIn("set_enabled(false)", lua)

    def test_register_refuses_on_config_errors(self):
        self.stage()
        (self.fake / "configerrors").write_text("error: bad line\n")
        proc = self.run_cmd(BINDS, "register")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.evals(), [])
        self.assertTrue(all(c[0] != "eval" for c in self.log()))

    def test_unregister_when_consuming_count_changes(self):
        self.stage(before=[bind("Shift_L", non_consuming=False)],
                   after=[bind("Shift_L", non_consuming=False), bind("Shift_L"), bind("Control_L"),
                          bind("Alt_L"), bind("mouse:272")])
        # consuming count unchanged here -> fine; now make it change
        self.stage(before=[bind("Shift_L", non_consuming=False)],
                   after=[bind("Shift_L"), bind("Control_L"), bind("Alt_L"), bind("mouse:272")])
        proc = self.run_cmd(BINDS, "register")
        self.assertEqual(proc.returncode, 1)
        evals = self.evals()
        self.assertEqual(len(evals), 2)
        self.assertIn("hl.bind(", evals[0])
        self.assertNotIn("hl.bind(", evals[1])
        self.assertIn("set_enabled(false)", evals[1])

    def test_unregister_when_binds_missing(self):
        self.stage(after=[bind("Shift_L")])
        proc = self.run_cmd(BINDS, "register")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(len(self.evals()), 2)

    def test_unregister_command(self):
        self.assertEqual(self.run_cmd(BINDS, "unregister").returncode, 0)
        lua, = self.evals()
        self.assertIn("set_enabled(false)", lua)
        self.assertNotIn("hl.bind(", lua)

    def test_status(self):
        self.stage(before=[bind("Shift_L"), bind("Control_L"), bind("Alt_L"), bind("mouse:272")])
        out = json.loads(self.run_cmd(BINDS, "status").stdout)
        self.assertTrue(out["listed"])
        self.stage(before=[bind("Shift_L")])
        out = json.loads(self.run_cmd(BINDS, "status").stdout)
        self.assertFalse(out["listed"])
        self.assertEqual(out["keys"]["Shift_L"], True)
        self.assertEqual(out["keys"]["Control_L"], False)

    def test_rejects_tampered_key(self):
        fake_peel = Path(self.tmp.name) / "fakepeel"
        fake_peel.write_text('#!/bin/sh\necho \'{"config":{"keys":{"convert":"X\\")) os.execute(1) --"}},"options":{"keys":["Shift_L","off"]},"path":""}\'\n')
        fake_peel.chmod(0o755)
        self.env["PEEL_BIN"] = str(fake_peel)
        proc = self.run_cmd(BINDS, "register")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.evals(), [])


if __name__ == "__main__":
    unittest.main()
