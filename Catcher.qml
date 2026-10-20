import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import qs.Commons

// The drop target that exists only while a wheel is armed.
//
// Service.qml calls arm() when a wheel key is tapped with the left button
// held. The catcher then maps a transparent fullscreen layer on the focused
// output; Hyprland hands it the drag on the next pointer motion, and the
// wheel opens where the drag first enters. No drag within a second and a
// half (the button was held for something else), the button released, or the
// drag leaving the output: it unmaps again.
//
// openKeyboard() is the other way in: files copied in a file manager and a
// shortcut. The wheel then opens at the cursor with keyboard focus: arrows
// pick, Tab switches wheel, Enter applies, Escape closes; hover and click work
// too.
//
// Drops are only ever accepted as a copy. Nautilus offers Copy and Move, and
// accepting a move would let the source delete the original.
Item {
  id: root

  property var service: null

  property bool mapped: false
  property bool dragInside: false
  property bool keyboardMode: false
  property string mode: "convert"
  property var paths: []
  property var convertSegments: []
  property var toolSegments: []
  property bool loadingTargets: false
  property bool loadingTools: false
  property bool wheelPlaced: false
  property string screenName: ""

  readonly property var segments: {
    if (mode === "convert") return convertSegments
    if (mode === "tools") return toolSegments
    if (mode === "actions") return service ? service.actionSegments : []
    return []
  }

  readonly property var modes: {
    var keys = service && service.config ? service.config.keys : {}
    var list = []
    var all = [["convert", "Convert"], ["tools", "Tools"], ["actions", "Actions"]]
    for (var i = 0; i < all.length; i++) {
      var key = keys[all[i][0]] || "off"
      if (key !== "off") list.push({ id: all[i][0], label: all[i][1], key: key.replace(/_[LR]$/, "") })
    }
    return list
  }

  readonly property string title: {
    if (mode === "convert") {
      if (loadingTargets) return "…"
      return convertSegments.length ? "Convert" : "Nothing to convert"
    }
    if (mode === "tools") {
      if (loadingTools) return "…"
      return toolSegments.length ? "Tools" : "No tools"
    }
    return "Actions"
  }

  function arm(wheel) {
    if (["convert", "tools", "actions"].indexOf(wheel) < 0) return
    mode = wheel
    if (mapped) return
    var monitor = Hyprland.focusedMonitor
    screenName = monitor ? String(monitor.name || "") : ""
    dragInside = false
    wheelPlaced = false
    paths = []
    convertSegments = []
    toolSegments = []
    wheel_.hoveredIndex = -1
    generation++
    mapped = true
    noDragTimer.restart()
  }

  function disarm() {
    noDragTimer.stop()
    releaseTimer.stop()
    exitTimer.stop()
    mapped = false
    dragInside = false
    keyboardMode = false
    dwellTab = -1
    dwellTimer.stop()
    loadingTargets = false
    loadingTools = false
    // Empty lists destroy the wheel's segment shapes while it is hidden.
    convertSegments = []
    toolSegments = []
    generation++
  }

  // Bumped on every open and close, so a slow answer for an earlier drag can
  // never fill the wheel of the current one.
  property int generation: 0

  function loadTargets() {
    if (!paths.length || !service) return
    var gen = generation
    loadingTargets = true
    loadingTools = true
    service.targetsFor("convert", paths, function(list) {
      if (gen !== root.generation) return
      root.loadingTargets = false
      root.convertSegments = list
    })
    service.targetsFor("tools", paths, function(list) {
      if (gen !== root.generation) return
      root.loadingTools = false
      root.toolSegments = list
    })
  }

  // x, y: cursor in Hyprland's global layout coordinates.
  function openKeyboard(wheel, files, x, y) {
    if (mapped && !keyboardMode) return  // a drag owns the catcher
    if (["convert", "tools", "actions"].indexOf(wheel) < 0) wheel = "convert"
    var monitor = Hyprland.focusedMonitor
    screenName = monitor ? String(monitor.name || "") : ""
    mode = wheel
    paths = files
    convertSegments = []
    toolSegments = []
    keyboardMode = true
    dragInside = false
    wheel_.hoveredIndex = -1
    generation++
    mapped = true
    // The window has no size until it maps; place against the screen instead.
    var screen = window.screen
    placeWheel(x - (monitor ? monitor.x : 0), y - (monitor ? monitor.y : 0),
               screen ? screen.width : window.width, screen ? screen.height : window.height)
    loadTargets()
    keys.forceActiveFocus()
  }

  function nextMode(delta) {
    var ids = modes.map(m => m.id)
    if (!ids.length) return
    var i = ids.indexOf(mode)
    mode = ids[(i + delta + ids.length) % ids.length]
    wheel_.hoveredIndex = -1
  }

  function apply(index) {
    var segment = index >= 0 ? segments[index] : null
    if (!segment || !paths.length) return false
    if (mode === "convert" || mode === "tools") service.enqueue(mode, segment.id, segment.label, paths)
    else if (mode === "actions") service.runAction(segment.id, paths)
    return true
  }

  // The drop arrives on release too, through Wayland rather than the event
  // socket; give it a moment before unmapping under it.
  function buttonReleased() {
    if (mapped) releaseTimer.restart()
  }

  function localPaths(urls) {
    var out = []
    for (var i = 0; i < urls.length; i++) {
      var url = String(urls[i])
      if (url.indexOf("file://") !== 0) continue
      var path = decodeURIComponent(url.substring(7).replace(/^localhost/, ""))
      if (path.charAt(0) === "/" && out.indexOf(path) < 0) out.push(path)
    }
    return out
  }

  // Centres the ring (not the whole item: the tab bar hangs below) on x, y.
  function placeWheel(x, y, width, height) {
    wheel_.x = Math.max(0, Math.min(width - wheel_.width, x - wheel_.cx))
    wheel_.y = Math.max(0, Math.min(height - wheel_.height, y - wheel_.cy))
    wheelPlaced = true
  }

  // Pointer at (x, y) in window coordinates: a tab under it switches wheel
  // after a short dwell (so sweeping across the bar does not flicker),
  // otherwise the segment under it highlights.
  property int dwellTab: -1

  function pointerAt(x, y, immediate) {
    var tab = wheel_.modeAt(x - wheel_.x, y - wheel_.y)
    if (tab >= 0) {
      wheel_.hoveredIndex = -1
      if (immediate) switchToTab(tab)
      else if (tab !== dwellTab) { dwellTab = tab; dwellTimer.restart() }
      return
    }
    dwellTab = -1
    dwellTimer.stop()
    wheel_.setPointer(x - wheel_.x, y - wheel_.y)
  }

  function switchToTab(tab) {
    var m = modes[tab]
    if (m && m.id !== mode) { mode = m.id; wheel_.hoveredIndex = -1 }
  }

  // Segment under (x, y), never one behind a tab.
  function segmentAt(x, y) {
    if (wheel_.modeAt(x - wheel_.x, y - wheel_.y) >= 0) return -1
    return wheel_.indexAt(x - wheel_.x, y - wheel_.y)
  }

  Timer { id: dwellTimer; interval: 250; onTriggered: if (root.dwellTab >= 0) root.switchToTab(root.dwellTab) }

  Timer { id: noDragTimer; interval: 1500; onTriggered: if (!root.dragInside) root.disarm() }
  Timer { id: releaseTimer; interval: 250; onTriggered: root.disarm() }
  Timer { id: exitTimer; interval: 200; onTriggered: if (!root.dragInside) root.disarm() }

  PanelWindow {
    id: window
    visible: root.mapped
    screen: {
      var screens = Quickshell.screens
      for (var i = 0; i < screens.length; i++)
        if (screens[i].name === root.screenName) return screens[i]
      return screens.length ? screens[0] : null
    }
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "peel-catcher"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: root.keyboardMode ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

    // Keyboard mode only: a click away from a segment closes, hover picks.
    MouseArea {
      anchors.fill: parent
      enabled: root.keyboardMode
      hoverEnabled: true
      onPositionChanged: (mouse) => root.pointerAt(mouse.x, mouse.y, false)
      onClicked: (mouse) => {
        var tab = wheel_.modeAt(mouse.x - wheel_.x, mouse.y - wheel_.y)
        if (tab >= 0) { root.switchToTab(tab); return }
        root.apply(root.segmentAt(mouse.x, mouse.y))
        root.disarm()
      }
    }

    Item {
      id: keys
      focus: root.keyboardMode
      Keys.onPressed: (event) => {
        if (event.key === Qt.Key_Escape) root.disarm()
        else if (event.key === Qt.Key_Left || event.key === Qt.Key_Up) wheel_.step(-1)
        else if (event.key === Qt.Key_Right || event.key === Qt.Key_Down) wheel_.step(1)
        else if (event.key === Qt.Key_Tab) root.nextMode(1)
        else if (event.key === Qt.Key_Backtab) root.nextMode(-1)
        else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
          if (root.apply(wheel_.hoveredIndex)) root.disarm()
        } else return
        event.accepted = true
      }
    }

    Wheel {
      id: wheel_
      width: (outerRadius + 48) * 2
      height: implicitHeight
      idleHint: root.keyboardMode ? "Arrows pick · Enter applies\nTab switches · Esc closes"
                                  : "Drop on a segment\nDrop here to cancel"
      visible: root.wheelPlaced
      opacity: visible ? 1 : 0
      Behavior on opacity { NumberAnimation { duration: 90 } }
      segments: root.mapped ? root.segments : []
      title: root.title
      modes: root.modes
      currentMode: root.mode
      // Omarchy's theme inside omarchy-shell; fixed colours when run standalone
      // (a plain `qs -p` config), where qs.Commons does not resolve.
      accent: "#4a9eff"  // Peel blue, whatever the theme
      background: Color.background ? Qt.rgba(Color.background.r, Color.background.g, Color.background.b, 0.92) : "#eb101315"
      foreground: Color.foreground || "#cacccc"
      dim: Color.muted || "#707880"
      fontFamily: Style.fontFamily || ""
    }

    DropArea {
      anchors.fill: parent
      keys: ["text/uri-list"]

      onEntered: (drag) => {
        root.dragInside = true
        noDragTimer.stop()
        exitTimer.stop()
        if (!root.wheelPlaced) root.placeWheel(drag.x, drag.y, width, height)
        if (!root.paths.length) {
          root.paths = root.localPaths(drag.urls)
          root.loadTargets()
        }
        if (drag.supportedActions & Qt.CopyAction) drag.accept(Qt.CopyAction)
        else drag.accepted = false
      }

      onPositionChanged: (drag) => root.pointerAt(drag.x, drag.y, false)

      onExited: {
        root.dragInside = false
        exitTimer.restart()
      }

      onDropped: (event) => {
        // A drop means the button is up, even if Hyprland's release event is late.
        if (root.service) root.service.lmbDown = false
        var index = root.segmentAt(event.x, event.y)
        // Always finish the drop as a copy, even when nothing was picked:
        // rejecting it left the drag unfinished on the Wayland side, and the
        // source kept the pointer until Escape. A copy never touches the
        // original. (Without Copy on offer, onEntered already refused the drag.)
        if (event.supportedActions & Qt.CopyAction) event.accept(Qt.CopyAction)
        else event.accepted = false
        if (index >= 0 && root.segments[index] && root.paths.length) root.apply(index)
        // Unmap after the drop handshake has gone out, not under it.
        Qt.callLater(root.disarm)
      }
    }
  }
}
