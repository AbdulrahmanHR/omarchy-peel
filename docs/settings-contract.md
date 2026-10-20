# Settings contract (config.json ↔ `peel config` ↔ Panel)

The file is `$XDG_CONFIG_HOME/peel/config.json`, default `~/.config/peel/config.json`. A missing file or field means the default.

```json
{
  "version": 1,
  "keys": { "convert": "Shift_L", "tools": "Control_L", "actions": "Alt_L" },
  "quality": "balanced",
  "output": { "location": "beside", "folder": "" },
  "advanced": { "video.crf": 20 }
}
```

`advanced` is a flat map from a dotted field key to a value. An absent key means "use the preset's value".

## `peel config --json`

```json
{
  "config": { "...": "merged config as above, advanced only holding overrides" },
  "effective": { "image.quality": 85, "video.crf": 20, "...": "every field: override ?? preset" },
  "options": {
    "keys": ["Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Super_L", "Super_R", "off"],
    "quality": [
      { "id": "high", "label": "High", "description": "Best quality, bigger files" },
      { "id": "balanced", "label": "Balanced", "description": "Good quality, sensible size" },
      { "id": "small", "label": "Small", "description": "Smaller files for sharing" }
    ],
    "advanced": [
      { "key": "image.quality", "group": "Images", "label": "Quality", "type": "integer",
        "min": 1, "max": 100, "step": 5, "unit": "",
        "presets": { "high": 92, "balanced": 85, "small": 70 } },
      { "key": "video.maxHeight", "group": "Video", "label": "Max resolution", "type": "enum",
        "choices": [ { "value": 0, "label": "Original" }, { "value": 2160, "label": "4K" }, { "value": 1080, "label": "1080p" } ],
        "presets": { "high": 0, "balanced": 0, "small": 1080 } },
      { "key": "metadata.keep", "group": "General", "label": "Keep metadata", "type": "boolean",
        "presets": { "high": true, "balanced": true, "small": false } }
    ],
    "output": { "location": [ { "value": "beside", "label": "Next to original" }, { "value": "folder", "label": "Folder" } ] }
  },
  "path": "/home/.../peel/config.json"
}
```

Field types are `integer` (min, max, step, unit), `enum` (choices of `{value, label}`) and `boolean`. Every field has `presets` with a value for each of high, balanced and small.

## `peel config set NAME VALUE`

| NAME | VALUE |
|---|---|
| `keys.<wheel>` | one of `options.keys`; no two wheels may share a key, except `off` |
| `quality` | `high` \| `balanced` \| `small` |
| `advanced.<field key>` | an integer in range, an enum value, `true`/`false`, or `default` to remove the override |
| `output.location` | `beside` \| `folder` |
| `output.folder` | an absolute path to an existing, writable directory |

- A bad value exits 1 with a one-line message on stderr.
- Every write is atomic: a temp file, then `os.replace`.

## Fields (v1)

| key | group | type | high / balanced / small |
|---|---|---|---|
| image.quality | Images | integer 1–100 | 92 / 85 / 70 |
| image.maxSide | Images | enum 0 (Original), 3840, 2560, 1920, 1280 | 0 / 0 / 2560 |
| video.crf | Video | integer 14–40 (x264 CRF; VP9 uses crf+9) | 18 / 23 / 28 |
| video.maxHeight | Video | enum 0 (Original), 2160, 1440, 1080, 720, 480 | 0 / 0 / 1080 |
| video.speed | Video | enum veryfast, faster, medium, slow, slower (x264 preset) | slow / medium / faster |
| audio.bitrate | Audio | enum 96, 128, 160, 192, 256, 320 (kbps, lossy outputs) | 256 / 192 / 128 |
| gif.fps | GIF | integer 5–30 | 15 / 12 / 10 |
| gif.width | GIF | enum 0 (Original), 1280, 960, 720, 480, 320 | 960 / 720 / 480 |
| pdf.dpi | PDF | enum 72, 150, 200, 300, 600 (PDF/slides → images) | 300 / 300 / 150 |
| metadata.keep | General | boolean | true / true / false |
