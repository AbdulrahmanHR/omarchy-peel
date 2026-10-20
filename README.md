# Peel for Omarchy

Drag a file, tap <kbd>Shift</kbd>, drop it on a format. An
[Omarchy](https://omarchy.org) 4 (Quattro) shell plugin that converts images,
audio, video, documents, spreadsheets, slides, PDFs and archives offline, next
to the original.

Peel is inspired by [Tangerine for macOS](https://tangerineformac.com). It is
an independent project and is not affiliated with Leap Studio.

## How it works

Start dragging a file in your file manager, and while you hold the mouse
button, tap a wheel key. A wheel of choices opens at the cursor; drop the file
on one.

| Wheel | Default key | What it offers |
|---|---|---|
| Convert | <kbd>Shift</kbd> | Formats the dropped files can become |
| Tools | <kbd>Ctrl</kbd> | One-click tools (compress, rotate, merge PDFs, ...) |
| Actions | <kbd>Alt</kbd> | Copy path, copy file, open a terminal, send, open |

The wheel has a tab bar under the ring that shows each wheel's key
(for example "Shift Convert · Ctrl Tools · Alt Actions"). Tap that key again, or
hover a tab for about a quarter of a second mid-drag, to switch wheel. Dropping
in the centre cancels. The accent colour is a fixed Peel blue, not your theme's.

Only a key *tap* while the left button is held does anything, so typing and
normal shortcuts are untouched. Each wheel's key can be set to the left or
right <kbd>Shift</kbd>, <kbd>Ctrl</kbd>, <kbd>Alt</kbd> or <kbd>Super</kbd>, or
to Off, in the bar panel. No two wheels can share a key.

### Without dragging

Copy files in your file manager, then open a wheel from a keyboard shortcut:

```bash
omarchy-shell peel wheel convert    # or: tools, actions
```

Peel does not bind this shortcut for you. Add your own in
`~/.config/hypr/bindings.lua`:

```lua
o.bind("SUPER + ALT + C", "Peel wheel", "omarchy-shell peel wheel convert")
```

The wheel opens at the cursor with keyboard focus: arrow keys pick,
<kbd>Tab</kbd> switches wheel, <kbd>Enter</kbd> applies, <kbd>Esc</kbd>
closes. Hover works, and clicking a tab switches wheel. If the clipboard holds no files, Peel says so
in a notification.

### Nautilus

An optional extension adds a **Convert to** submenu to the right-click menu,
with the same formats the wheel would show. It only appears for local regular
files, and runs the same `peel` the wheel uses.

```bash
mkdir -p ~/.local/share/nautilus-python/extensions
ln -s ~/.config/omarchy/plugins/io.github.abdulrahmanhr.peel/nautilus/peel.py \
      ~/.local/share/nautilus-python/extensions/peel.py
nautilus -q
```

Needs `nautilus-python`. The extension looks for `peel` in the installed plugin
folder first, then next to the extension (a repo checkout), then on `PATH`.

## Formats

The table is generated from [`registry/formats.json`](registry/formats.json).
Input-only formats can be converted *from* but not *to*.

| Kind | Engine | Converts to | Also accepted as input |
|---|---|---|---|
| Image | ImageMagick | JPG, PNG, WebP, AVIF, HEIC, TIFF, BMP, GIF, PDF | JXL |
| Vector | rsvg | PNG, PDF, JPG, WebP | SVG |
| Audio | ffmpeg | MP3, M4A, WAV, FLAC, OGG, Opus, AIFF, WMA | AAC |
| Video | ffmpeg | MP4, MOV, MKV, WebM, AVI, WMV, GIF, MP3 | |
| Document | LibreOffice, pandoc | PDF, DOCX, ODT, TXT, HTML (LibreOffice); DOCX, ODT, TXT, HTML, Markdown, EPUB (pandoc) | DOC, RTF |
| Spreadsheet | LibreOffice | XLSX, ODS, CSV, TSV, PDF | XLS |
| Slides | LibreOffice | PDF, PPTX, ODP, PNG, JPG | PPT |
| PDF | poppler, pdf2docx | PNG, JPG, TXT; DOCX (pdf2docx) | |
| Archive | bsdtar, 7z | ZIP, TAR, TAR.GZ, 7Z | TAR.XZ, TAR.BZ2, RAR |

`peel targets FILE...` prints what the given files can become, and a target
only shows up if the tool that would do the work is installed. With several
files, only formats valid for all of them are listed. A file is never offered
its own format. pandoc is optional: without it, Markdown and EPUB are simply
missing and LibreOffice covers the rest. PDF to DOCX needs the optional
`python-pdf2docx` (AUR, AGPL-3.0, run as a separate program, never through
LibreOffice); the layout may differ from the PDF, and scanned PDFs are not
supported because they have no text to convert. `peel targets --json` is what the wheel
and the Nautilus menu read.

```bash
peel targets photo.png          # jpg webp avif heic tiff bmp gif pdf
peel convert --to webp photo.png
```

## Tools and Actions

Tools (`peel-tool targets FILE...` lists the ones valid for your files):

| Tool | What it does | Works on |
|---|---|---|
| Compress | Smaller file, same format | images, video, audio, PDF |
| Remove info | Removes hidden details: GPS location, camera, author, dates; output is named `name (no info)` | images, video, audio, PDF |
| Half size | Half the width and height | images, video |
| Rotate | Turn 90° clockwise | images, video |
| Grayscale | Black and white copy | images |
| Trim silence | Cut the silence at the start and end | audio |
| Extract audio | Save the soundtrack as M4A | video |
| Snapshot | Save one frame as a PNG | video |
| Merge PDFs | Join the PDFs into one, in order | PDF |
| Split pages | One PDF per page | PDF |

Actions:

| Action | What it does |
|---|---|
| Copy path | Copy the file's path as text |
| Copy file | Copy the file to paste in another app |
| Terminal | Open a terminal in its folder |
| LocalSend | Send to a nearby device |
| Open | Open with the default app |

## Quality and output

Three presets set sensible defaults for everything at once: **High** (best
quality, bigger files), **Balanced** (the default) and **Small** (smaller files
for sharing). The bar panel also exposes each setting on its own; an override
wins over the preset and can be removed again.

| Setting | Range | High / Balanced / Small |
|---|---|---|
| Image quality | 1-100 | 92 / 85 / 70 |
| Image max size | Original, 3840, 2560, 1920, 1280 px | Original / Original / 2560 |
| Video quality (x264 CRF, lower is better) | 14-40 | 18 / 23 / 28 |
| Video max resolution | Original, 4K, 1440p, 1080p, 720p, 480p | Original / Original / 1080p |
| Video encoding speed | veryfast ... slower | slow / medium / faster |
| Audio bitrate | 96-320 kbps | 256 / 192 / 128 |
| GIF frame rate | 5-30 fps | 15 / 12 / 10 |
| GIF width | Original, 1280, 960, 720, 480, 320 px | 960 / 720 / 480 |
| PDF page image resolution | 72, 150, 200, 300, 600 dpi | 300 / 300 / 150 |
| Keep metadata | on / off | on / on / off |

Output goes **next to the original** by default, or into one folder you choose
(an absolute path to an existing, writable directory).

Settings live in `~/.config/peel/config.json`. You can also use the CLI;
the format is documented in [`docs/settings-contract.md`](docs/settings-contract.md).

```bash
peel config --json                     # merged config, effective values, options
peel config set quality small
peel config set keys.convert Shift_R
peel config set advanced.video.crf 20  # "default" removes the override
peel config set output.folder ~/Converted
```

## Safety

- Drops are accepted as **copy only**. The file manager offers Copy and Move,
  and accepting a move would let it delete your original.
- Peel **never overwrites**: if the output name is taken, it picks a new one.
- Every external program is started with an argument list, never through a
  shell. File names are never parsed as commands.
- Each conversion runs in a memory-capped `systemd-run --user` scope, so a
  hostile or broken file cannot take the machine down with it.
- Archives are checked before they are extracted: absolute paths, `..`
  components, links that leave the archive, special files and hard links are
  rejected.
- The mouse and key binds are added to Hyprland at run time, are
  non-consuming (your own bindings still fire), and are never written to your
  config. They are switched off when Peel stops.

## Requirements

- Omarchy 4 (Quattro) on Hyprland.
- Arch packages, depending on what you want to convert:

```bash
sudo pacman -S ffmpeg imagemagick librsvg libreoffice-fresh poppler \
  ghostscript qpdf 7zip libarchive libheif wl-clipboard python
```

| Package | Used for |
|---|---|
| `ffmpeg` | audio, video, GIF; most video and audio tools |
| `imagemagick`, `libheif` | images, including HEIC and AVIF |
| `librsvg` | SVG |
| `libreoffice-fresh` | documents, spreadsheets, slides |
| `poppler` | PDF to images and text |
| `ghostscript`, `qpdf` | PDF compress, merge, split, clean metadata |
| `7zip`, `libarchive` | archives |
| `wl-clipboard` | Copy path, Copy file, keyboard path |
| `python` | the `peel` and `peel-tool` programs |
| `pandoc` (optional) | Markdown and EPUB |
| `python-pdf2docx` (optional, AUR) | PDF to DOCX |
| `nautilus-python` (optional) | the Nautilus menu |
| `localsend` (optional) | the LocalSend action |

Anything missing only removes the formats that need it.

## Install

```bash
omarchy plugin add https://github.com/AbdulrahmanHR/omarchy-peel --enable
```

Omarchy asks before cloning. Plugins run as unsandboxed code inside the Omarchy
shell, so read the code before you enable it. Then add the Peel widget to the
bar in the bar settings; it shows conversions in progress and lets you change
the wheel keys, quality and output folder. The wheels work once the plugin is
enabled; the widget is how you configure them.

## Development

Tests need no Wayland session:

```bash
python3 -I -m unittest discover -s tests -v
PEEL_FULL=1 python3 -I -m unittest discover -s tests -k FullMatrix -v   # every input -> output pair, a few minutes
```

Validate the plugin manifest with `omarchy plugin validate .`.

| Path | What it is |
|---|---|
| `manifest.json`, `Service.qml`, `Panel.qml` | The plugin: service and bar widget |
| `Catcher.qml`, `Wheel.qml` | The drop target and the wheel |
| `bin/peel`, `bin/peel-tool` | Conversion and tools, usable on their own |
| `bin/peel-binds` | Registers and removes the run-time Hyprland binds |
| `registry/formats.json` | Every format, kind and engine route |
| `nautilus/peel.py` | The Nautilus extension |
| `docs/settings-contract.md` | Config file and `peel config` contract |

## Limitations

- Wayland and Hyprland only.
- The drag source must offer **Copy**; sources that only offer Move are ignored.
- PDF to DOCX is the only PDF to Office route, and scanned PDFs are not supported. Apple Pages is not supported.
- With several monitors, the wheel opens on the focused output.

## License

[MIT](LICENSE), copyright 2026 Abdulrahman Rahmouni.
