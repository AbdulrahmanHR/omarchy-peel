import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io

// Peel's always-loaded half: Hyprland binds, the drag catcher and the job queue.
//
// bin/peel-binds adds non-consuming binds at run time (nothing goes into the
// user's config) that post custom events: "peel lmb down|up" for the left
// button and "peel arm <wheel>" for each wheel's key. Only a key tap while the
// button is held arms the catcher, so typing never maps anything.
//
// Every command is an argv array; the only values that reach one are wheel
// and format ids from peel itself and paths from a drop.
Item {
  id: root

  property var shell: null
  property var manifest: null

  readonly property string pluginFolder: decodeURIComponent(
    String(Qt.resolvedUrl(".")).replace(/^file:\/\//, "").replace(/\/$/, ""))
  readonly property string peelBin: pluginFolder + "/bin/peel"
  readonly property string bindsBin: pluginFolder + "/bin/peel-binds"
  readonly property string toolBin: pluginFolder + "/bin/peel-tool"

  // --- config ---------------------------------------------------------------

  property var config: ({ keys: { convert: "Shift_L", tools: "Control_L", actions: "Alt_L" } })
  property var keyOptions: []
  // Everything `peel config --json` describes: key choices, quality presets,
  // advanced fields (with each preset's value) and output locations.
  property var options: ({})
  property string configPath: ""
  property string bindsError: ""

  function reloadConfig() {
    if (!configProc.running) configProc.running = true
  }

  function setKey(wheel, key) {
    setConfig("keys." + wheel, key)
  }

  // name: "quality", "advanced.video.crf", "output.location", ...; value is a
  // string as the CLI takes it ("default" clears an advanced override).
  // peel validates; a rejected value lands in bindsError for the panel.
  function setConfig(name, value) {
    // Queued, not dropped: stepping a value quickly in the panel sends several
    // sets while one is still running. A later set of the same name wins.
    configQueue = configQueue.filter(item => item.name !== String(name))
      .concat([{ name: String(name), value: String(value) }])
    nextConfigSet()
  }

  property var configQueue: []

  function nextConfigSet() {
    if (setKeyProc.running || !configQueue.length) return
    var item = configQueue[0]
    configQueue = configQueue.slice(1)
    setKeyProc.command = [root.peelBin, "config", "set", item.name, item.value]
    setKeyProc.running = true
  }

  Process {
    id: configProc
    command: [root.peelBin, "config", "--json"]
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var data = JSON.parse(text)
          root.config = data.config
          root.keyOptions = data.options.keys
          root.options = data.options
          root.configPath = data.path
        } catch (e) {
          console.warn("peel: cannot read config: " + e)
        }
        root.registerBinds()
      }
    }
  }

  Process {
    id: setKeyProc
    stderr: StdioCollector { id: setKeyErr }
    onExited: (code) => {
      root.bindsError = code === 0 ? "" : setKeyErr.text.trim()
      if (root.configQueue.length) root.nextConfigSet()
      else root.reloadConfig()
    }
  }

  FileView {
    path: root.configPath
    watchChanges: root.configPath !== ""
    printErrors: false
    onFileChanged: root.reloadConfig()
  }

  // --- binds ----------------------------------------------------------------

  function registerBinds() {
    if (bindsProc.running) { bindsAgain = true; return }
    bindsProc.running = true
  }
  property bool bindsAgain: false

  Process {
    id: bindsProc
    command: [root.bindsBin, "register"]
    stderr: StdioCollector { id: bindsErr }
    onExited: (code) => {
      root.bindsError = code === 0 ? "" : (bindsErr.text.trim() || "Could not add Peel's key binds")
      if (code !== 0) console.warn("peel: " + root.bindsError)
      if (root.bindsAgain) { root.bindsAgain = false; root.registerBinds() }
    }
  }

  // A config reload drops run-time binds; add them back once it settles.
  Timer {
    id: rebindTimer
    interval: 600
    onTriggered: root.registerBinds()
  }

  Component.onCompleted: reloadConfig()
  Component.onDestruction: Quickshell.execDetached([root.bindsBin, "unregister"])

  // --- arming -----------------------------------------------------------------

  property bool lmbDown: false

  Connections {
    target: Hyprland
    function onRawEvent(event) {
      if (!event) return
      var name = String(event.name)
      if (name === "configreloaded") { rebindTimer.restart(); return }
      if (name !== "custom") return
      var parts = String(event.data).split(" ")
      if (parts[0] !== "peel") return
      if (parts[1] === "lmb") {
        root.lmbDown = parts[2] === "down"
        if (!root.lmbDown) catcher.buttonReleased()
      } else if (parts[1] === "arm" && root.lmbDown) {
        catcher.arm(parts[2])
      }
    }
  }

  Catcher {
    id: catcher
    service: root
  }

  // --- keyboard path ------------------------------------------------------------

  // Files copied in a file manager, then a shortcut:
  //   omarchy-shell peel wheel convert      (qs ipc call peel wheel convert)
  IpcHandler {
    target: "peel"
    function wheel(mode: string): string {
      root.openFromClipboard(mode)
      return "ok"
    }
  }

  property string pendingMode: "convert"

  function openFromClipboard(mode) {
    pendingMode = mode || "convert"
    if (!clipProc.running) clipProc.running = true
  }

  function clipboardPaths(text) {
    var out = []
    var lines = String(text).split(/\r?\n/)
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim()
      if (!line || line.charAt(0) === "#") continue
      if (line.indexOf("file://") === 0) line = decodeURIComponent(line.substring(7).replace(/^localhost/, ""))
      if (line.charAt(0) === "/" && out.indexOf(line) < 0) out.push(line)
    }
    return out
  }

  // text/uri-list first (GTK file managers), then plain paths, one per line.
  // wl-paste or hyprctl hanging must not leave the keyboard path dead.
  Timer {
    id: clipGuard
    interval: 3000
    running: clipProc.running || cursorProc.running
    onTriggered: { clipProc.running = false; cursorProc.running = false }
  }

  Process {
    id: clipProc
    command: ["sh", "-c", "wl-paste --no-newline --type text/uri-list 2>/dev/null || wl-paste --no-newline 2>/dev/null"]
    stdout: StdioCollector {
      onStreamFinished: {
        var paths = root.clipboardPaths(text)
        if (!paths.length) {
          Quickshell.execDetached(["notify-send", "-a", "Peel", "--", "Nothing to convert", "Copy files in the file manager first."])
          return
        }
        cursorProc.paths = paths
        cursorProc.running = true
      }
    }
  }

  Process {
    id: cursorProc
    property var paths: []
    command: ["hyprctl", "cursorpos", "-j"]
    stdout: StdioCollector {
      onStreamFinished: {
        var pos = { x: 0, y: 0 }
        try { pos = JSON.parse(text) } catch (e) {}
        catcher.openKeyboard(root.pendingMode, cursorProc.paths, pos.x, pos.y)
      }
    }
  }

  // --- jobs -------------------------------------------------------------------

  // Queue of { id, wheel, target, label, files, state, pct, done, failed, outputs, error }.
  property var jobs: []
  property int nextJobId: 1
  readonly property var activeJob: jobs.length && jobs[0].state === "running" ? jobs[0] : null
  readonly property int pendingCount: jobs.filter(j => j.state === "queued" || j.state === "running").length
  property var history: []

  // What the dropped files can become (wheel "convert", from peel) or have
  // done to them (wheel "tools", from peel-tool): callback([{ id, label }]).
  function targetsFor(wheel, paths, callback) {
    var command = wheel === "tools"
      ? [root.toolBin, "targets", "--json", "--"].concat(paths)
      : [root.peelBin, "targets", "--json", "--"].concat(paths)
    var proc = targetsComponent.createObject(root, { command: command, listKey: wheel === "tools" ? "tools" : "convert", callback: callback })
    proc.running = true
  }

  Component {
    id: targetsComponent
    Process {
      id: tp
      property string listKey: "convert"
      property var callback: null
      property bool delivered: false

      // Exactly one callback, then gone: on output, on exit without output,
      // or after 8 s if the process never started or hangs.
      function finish(list) {
        if (delivered) return
        delivered = true
        running = false
        if (callback) callback(list)
        destroy()
      }

      stdout: StdioCollector {
        onStreamFinished: {
          var list = []
          try {
            list = (JSON.parse(text)[tp.listKey] || []).map(t => ({
              id: t.ext || t.id,
              label: t.label,
              description: tp.listKey === "tools"
                ? (root.toolDescriptions[t.id] || "")
                : "Save a " + t.label + " copy" + (root.config.output && root.config.output.location === "folder" && root.config.output.folder
                                                    ? " in your Peel folder" : " next to the original")
            }))
          } catch (e) {}
          tp.finish(list)
        }
      }
      // tp is null by then if output already delivered and destroyed it.
      onExited: Qt.callLater(() => { if (tp) tp.finish([]) })
      property Timer guard: Timer { interval: 8000; running: true; onTriggered: tp.finish([]) }
    }
  }

  function enqueue(wheel, target, label, paths) {
    var job = { id: nextJobId++, wheel: wheel, target: target, label: label, files: paths,
                state: "queued", pct: 0, index: 0, done: 0, failed: 0, outputs: [], error: "" }
    jobs = jobs.concat([job])
    pump()
  }

  function updateJob(id, change) {
    jobs = jobs.map(j => j.id === id ? Object.assign({}, j, change) : j)
  }

  function pump() {
    if (jobProc.running || !jobs.length || jobs[0].state === "running") return
    var job = jobs[0]
    updateJob(job.id, { state: "running" })
    jobProc.jobId = job.id
    jobProc.command = job.wheel === "tools"
      ? [root.toolBin, "run", "--tool", job.target, "--progress", "--notify", "--"].concat(job.files)
      : [root.peelBin, "convert", "--to", job.target, "--progress", "--notify", "--"].concat(job.files)
    jobProc.running = true
  }

  Process {
    id: jobProc
    property int jobId: 0
    stdout: SplitParser {
      onRead: (line) => {
        var ev
        try { ev = JSON.parse(line) } catch (e) { return }
        var job = root.jobs.find(j => j.id === jobProc.jobId)
        if (!job) return
        if (ev.event === "start") root.updateJob(job.id, { index: ev.index, pct: 0 })
        else if (ev.event === "progress") root.updateJob(job.id, { pct: ev.pct })
        else if (ev.event === "done") root.updateJob(job.id, { done: job.done + 1, outputs: job.outputs.concat([ev.output]) })
        else if (ev.event === "error") root.updateJob(job.id, { failed: job.failed + 1, error: ev.message })
      }
    }
    onExited: {
      var job = root.jobs.find(j => j.id === jobProc.jobId)
      if (job) {
        root.history = [Object.assign({}, job, { state: job.failed ? "failed" : "done", pct: 100 })]
          .concat(root.history).slice(0, 20)
        root.jobs = root.jobs.filter(j => j.id !== job.id)
      }
      root.pump()
    }
  }

  // --- actions ------------------------------------------------------------------

  readonly property var toolDescriptions: ({
    "compress": "Smaller file, same format",
    "strip-metadata": "Removes hidden details: GPS location, camera, author, dates",
    "resize-half": "Half the width and height",
    "rotate": "Turn 90° clockwise",
    "to-grayscale": "Black and white copy",
    "trim-silence": "Cut the silence at the start and end",
    "extract-audio": "Save the soundtrack as M4A",
    "snapshot": "Save one frame as a PNG",
    "merge-pdf": "Join the PDFs into one, in order",
    "split-pdf": "One PDF per page"
  })

  readonly property var actionSegments: [
    { id: "copy-path", label: "Copy path", description: "Copy the file's path as text" },
    { id: "copy-file", label: "Copy file", description: "Copy the file to paste in another app" },
    { id: "terminal", label: "Terminal", description: "Open a terminal in its folder" },
    { id: "localsend", label: "LocalSend", description: "Send to a nearby device" },
    { id: "open", label: "Open", description: "Open with the default app" }
  ]

  function runAction(id, paths) {
    if (!paths.length) return
    var dir = paths[0].substring(0, paths[0].lastIndexOf("/")) || "/"
    if (id === "copy-path") Quickshell.execDetached(["wl-copy", "--", paths.join("\n")])
    else if (id === "copy-file")
      Quickshell.execDetached(["wl-copy", "--type", "text/uri-list", "--",
                               paths.map(p => "file://" + p.split("/").map(encodeURIComponent).join("/")).join("\r\n")])
    else if (id === "terminal") Quickshell.execDetached(["setsid", "uwsm-app", "--", "xdg-terminal-exec", "--dir=" + dir])
    else if (id === "localsend") Quickshell.execDetached(["setsid", "uwsm-app", "--", "localsend", "--headless", "send"].concat(paths))
    else if (id === "open") Quickshell.execDetached(["xdg-open", paths[0]])
  }
}
