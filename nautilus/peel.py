import json
import os
import shutil
import subprocess
import time

from gi import require_version

require_version("Nautilus", "4.1")

from gi.repository import GObject, Nautilus


PLUGIN_PEEL = os.path.expanduser(
    "~/.config/omarchy/plugins/io.github.abdulrahmanhr.peel/bin/peel"
)
CACHE_SECONDS = 5
TARGETS_TIMEOUT = 3


def find_peel():
    # Plugin install first, then the repo checkout (realpath so a symlinked
    # install still finds ../bin/peel), then whatever is on PATH.
    if os.access(PLUGIN_PEEL, os.X_OK):
        return PLUGIN_PEEL
    here = os.path.dirname(os.path.realpath(__file__))
    repo = os.path.join(here, "..", "bin", "peel")
    if os.path.isfile(repo) and os.access(repo, os.X_OK):
        return os.path.normpath(repo)
    return shutil.which("peel")


class PeelAction(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        super().__init__()
        self._cache = {}  # key -> (expires_at, [{"ext", "label"}, ...])

    def _selected_paths(self, files):
        # Local regular files only: no directories, no remote URIs.
        paths = []
        for file in files:
            if file.get_uri_scheme() != "file" or file.is_directory():
                continue
            location = file.get_location()
            path = location.get_path() if location else None
            if path and os.path.isfile(path) and path not in paths:
                paths.append(path)
        return paths

    def _targets(self, peel, paths):
        # Ask peel what every selected file can become; cached briefly so
        # reopening the menu does not respawn it.
        try:
            key = tuple((p, os.stat(p).st_mtime_ns) for p in paths)
        except OSError:
            return []
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and hit[0] > now:
            return hit[1]

        targets = []
        try:
            result = subprocess.run(
                [peel, "targets", "--json", "--", *paths],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=TARGETS_TIMEOUT,
            )
            if result.returncode == 0:
                for t in json.loads(result.stdout).get("convert", []):
                    if t.get("ext") and t.get("label"):
                        targets.append({"ext": t["ext"], "label": t["label"]})
        except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
            targets = []

        self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
        self._cache[key] = (now + CACHE_SECONDS, targets)
        return targets

    def _on_activate(self, _menu, peel, ext, paths):
        # Detached so Nautilus never blocks; peel sends its own notification.
        subprocess.Popen(
            [peel, "convert", "--to", ext, "--notify", "--", *paths],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def get_file_items(self, *args):
        files = args[0] if len(args) == 1 else args[1]
        peel = find_peel()
        if not peel:
            return []

        paths = self._selected_paths(files)
        if not paths:
            return []

        targets = self._targets(peel, paths)
        if not targets:
            return []

        top = Nautilus.MenuItem(
            name="PeelNautilus::convert",
            label="Convert to",
            icon="document-save-as",
        )
        submenu = Nautilus.Menu()
        top.set_submenu(submenu)
        for t in targets:
            item = Nautilus.MenuItem(
                name=f"PeelNautilus::convert_{t['ext']}",
                label=t["label"],
            )
            item.connect("activate", self._on_activate, peel, t["ext"], paths)
            submenu.append_item(item)
        return [top]
