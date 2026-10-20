import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Peel bar widget: a convert icon (with live progress while a job runs) and a
// small keyboard-driven panel with the wheel keys and the recent jobs.
// State comes from Service.qml, fetched through the scoped shell facade.
Panel {
  id: root
  // Peel's own accent, the same blue as the wheel
  readonly property color peelBlue: "#4a9eff"
  moduleName: "io.github.abdulrahmanhr.peel"
  ipcTarget: "io.github.abdulrahmanhr.peel"

  readonly property string pluginId: "io.github.abdulrahmanhr.peel"

  // Injected by the shell for plugin entry points; falls back to the bar's.
  property var shell: null
  readonly property var shellApi: root.shell ? root.shell : (root.bar ? root.bar.shell : null)
  readonly property var peel: shellApi && typeof shellApi.serviceFor === "function"
    ? shellApi.serviceFor(pluginId) : null

  // Cursor model shared by keyboard and mouse:
  //   convert, tools, actions   key choice rows; selectedIndex is the option
  //   recent                    history list; selectedIndex is the item
  property string focusSection: "convert"
  property int selectedIndex: 0
  property bool cursorActive: false
  //   quality, output, folder, advanced, adv:<field key>, resetall   settings rows

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  readonly property var wheels: [
    { id: "convert", title: "CONVERT" },
    { id: "tools", title: "TOOLS" },
    { id: "actions", title: "ACTIONS" }
  ]
  readonly property var keyOptions: peel && peel.keyOptions ? peel.keyOptions : []
  readonly property var keys: peel && peel.config && peel.config.keys ? peel.config.keys : ({})
  readonly property var recent: peel && peel.history ? peel.history.slice(0, 5) : []
  readonly property int pendingCount: peel ? peel.pendingCount : 0
  readonly property var activeJob: peel ? peel.activeJob : null
  readonly property bool busy: pendingCount > 0
  readonly property int activePct: activeJob ? Math.round(activeJob.pct) : 0

  function keyLabel(key) {
    var k = String(key)
    if (k === "off") return "Off"
    var m = /^(Shift|Control|Alt|Super)_([LR])$/.exec(k)
    if (!m) return k
    var name = m[1] === "Control" ? "Ctrl" : m[1]
    return (m[2] === "L" ? "L " : "R ") + name
  }

  function usedElsewhere(wheel, key) {
    if (key === "off") return false
    for (var i = 0; i < wheels.length; i++) {
      var other = wheels[i].id
      if (other !== wheel && keys[other] === key) return true
    }
    return false
  }

  function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s") }

  function dirname(path) {
    var p = String(path)
    var i = p.lastIndexOf("/")
    return i > 0 ? p.substring(0, i) : "/"
  }

  function basename(path) {
    var p = String(path)
    return p.substring(p.lastIndexOf("/") + 1)
  }

  function jobText(job) {
    return plural(job.files ? job.files.length : 0, "file") + " → " + job.label
  }

  readonly property string iconGlyph: "󰓡"
  readonly property string barText: busy ? iconGlyph + " " + activePct + "%" : iconGlyph
  readonly property color barIconColor: peel ? barForeground : Qt.darker(barForeground, 1.55)
  readonly property string barTooltip: {
    if (!peel) return "Peel service is not running"
    if (!busy) return "Peel"
    var line = activeJob
      ? "Converting " + plural(activeJob.files.length, "file") + " to " + activeJob.label + " — " + activePct + "%"
      : plural(pendingCount, "job") + " queued"
    return "Peel\n" + line
  }

  readonly property string idleHint: "Drag a file, hold the button, tap " + keyLabel(keys.convert || "Shift_L")
  readonly property string heroMeta: {
    if (!peel) return "Peel service is not running"
    if (peel.bindsError !== "") return peel.bindsError
    if (busy) return activeJob ? "Converting " + jobText(activeJob) : plural(pendingCount, "job") + " queued"
    return idleHint
  }
  readonly property bool heroIsError: peel && peel.bindsError !== ""

  // ---------- Settings (from `peel config --json`, guarded: all may be {}) ----------
  readonly property var cfg: peel && peel.config ? peel.config : ({})
  readonly property var opts: peel && peel.options ? peel.options : ({})
  readonly property var qualityOptions: opts.quality ? opts.quality : []
  readonly property var advancedFields: opts.advanced ? opts.advanced : []
  readonly property var locationOptions: opts.output && opts.output.location ? opts.output.location : []
  readonly property string quality: cfg.quality ? String(cfg.quality) : "balanced"
  readonly property var overrides: cfg.advanced ? cfg.advanced : ({})
  readonly property string location: cfg.output && cfg.output.location ? String(cfg.output.location) : "beside"
  readonly property string folder: cfg.output && cfg.output.folder ? String(cfg.output.folder) : ""
  readonly property bool folderMode: location === "folder"
  readonly property var overriddenKeys: Object.keys(overrides)
  readonly property string qualityDescription: {
    for (var i = 0; i < qualityOptions.length; i++)
      if (qualityOptions[i].id === quality) return qualityOptions[i].description || ""
    return ""
  }

  // In-memory only.
  property bool advancedOpen: false

  // Fields grouped in option order: [{ name, fields: [...] }]
  readonly property var advancedGroups: {
    var groups = [], byName = {}
    for (var i = 0; i < advancedFields.length; i++) {
      var f = advancedFields[i]
      var g = f.group || "General"
      if (!(g in byName)) { byName[g] = { name: g, fields: [] }; groups.push(byName[g]) }
      byName[g].fields.push(f)
    }
    return groups
  }

  function isOverridden(field) {
    return Object.prototype.hasOwnProperty.call(overrides, field.key)
  }

  function effectiveValue(field) {
    if (isOverridden(field)) return overrides[field.key]
    return field.presets ? field.presets[quality] : undefined
  }

  function choiceIndex(field, value) {
    var c = field.choices || []
    for (var i = 0; i < c.length; i++) if (String(c[i].value) === String(value)) return i
    return 0
  }

  function isChips(field) { return field.type === "enum" && (field.choices || []).length <= 4 }
  function isCycle(field) { return field.type === "enum" && (field.choices || []).length > 4 }

  function displayValue(field) {
    var v = effectiveValue(field)
    if (v === undefined) return ""
    if (field.type === "enum") {
      var c = field.choices || []
      return c.length ? String(c[choiceIndex(field, v)].label) : String(v)
    }
    return String(v) + (field.unit ? " " + field.unit : "")
  }

  function setField(field, value) {
    if (peel) peel.setConfig("advanced." + field.key, String(value))
  }

  function resetField(field) {
    if (peel && isOverridden(field)) peel.setConfig("advanced." + field.key, "default")
  }

  function stepField(field, dir) {
    var v = Number(effectiveValue(field))
    var step = field.step || 1
    var next = Math.max(field.min, Math.min(field.max, v + dir * step))
    if (next !== v) setField(field, next)
  }

  function cycleField(field, dir) {
    var c = field.choices || []
    if (!c.length) return
    var i = (choiceIndex(field, effectiveValue(field)) + dir + c.length) % c.length
    setField(field, c[i].value)
  }

  function fieldByKey(key) {
    for (var i = 0; i < advancedFields.length; i++) if (advancedFields[i].key === key) return advancedFields[i]
    return null
  }

  // Reset all: setConfig ignores calls while one runs, so a timer re-issues the
  // first override that is still present until none are left.
  property bool resetting: false
  Timer {
    id: resetTimer
    interval: 150
    repeat: true
    running: root.resetting
    onTriggered: {
      if (!root.peel || root.peel.bindsError !== "" || root.overriddenKeys.length === 0) {
        root.resetting = false
        return
      }
      root.peel.setConfig("advanced." + root.overriddenKeys[0], "default")
    }
  }

  function resetAll() {
    if (peel && overriddenKeys.length > 0) resetting = true
  }

  function chooseFolder() {
    if (!folderProc.running) folderProc.running = true
  }

  Process {
    id: folderProc
    command: ["omarchy-file-select", "--directory", "--title", "Peel output folder"]
    stdout: StdioCollector {
      onStreamFinished: {
        var line = String(text).split("\n")[0].trim()
        if (line.indexOf("file://") === 0) line = decodeURIComponent(line.substring(7))
        if (line.charAt(0) === "/" && root.peel) root.peel.setConfig("output.folder", line)
      }
    }
  }

  function chooseLocation(value) {
    if (!peel) return
    if (value !== location) peel.setConfig("output.location", value)
    if (value === "folder" && folder === "") chooseFolder()
  }

  // Sections the cursor can visit, in order; hidden rows are not listed.
  readonly property var sections: {
    if (!peel) return []
    var list = ["convert", "tools", "actions", "quality", "output"]
    if (folderMode) list.push("folder")
    list.push("advanced")
    if (advancedOpen) {
      for (var i = 0; i < advancedFields.length; i++) list.push("adv:" + advancedFields[i].key)
      if (overriddenKeys.length > 0) list.push("resetall")
    }
    list.push("recent")
    return list
  }
  onSectionsChanged: {
    if (sections.length && sections.indexOf(focusSection) < 0) {
      focusSection = "advanced"
      selectedIndex = 0
    }
  }

  function sectionField(section) {
    return section.indexOf("adv:") === 0 ? fieldByKey(section.substring(4)) : null
  }

  function sectionCount(section) {
    if (section === "recent") return recent.length
    if (section === "quality") return qualityOptions.length
    if (section === "output") return locationOptions.length
    if (section === "folder" || section === "advanced" || section === "resetall") return 1
    var f = sectionField(section)
    if (f) return isChips(f) ? (f.choices || []).length : 1
    return keyOptions.length
  }

  function landingIndex(section) {
    if (section === "recent") return 0
    if (section === "quality") {
      for (var i = 0; i < qualityOptions.length; i++) if (qualityOptions[i].id === quality) return i
      return 0
    }
    if (section === "output") {
      for (var j = 0; j < locationOptions.length; j++) if (locationOptions[j].value === location) return j
      return 0
    }
    var f = sectionField(section)
    if (f) return isChips(f) ? choiceIndex(f, effectiveValue(f)) : 0
    if (section === "folder" || section === "advanced" || section === "resetall") return 0
    return Math.max(0, keyOptions.indexOf(keys[section]))
  }

  function cursorAt(section, index) {
    return root.cursorActive && root.focusSection === section && root.selectedIndex === index
  }

  function setCursor(section, index) {
    cursorActive = true
    focusSection = section
    selectedIndex = index
  }

  function moveCursor(dx, dy) {
    cursorActive = true
    if (dy !== 0) {
      var next = Math.max(0, Math.min(sections.length - 1, sections.indexOf(focusSection) + dy))
      if (sections[next] === "recent" && recent.length === 0) return
      if (sections[next] !== focusSection) {
        focusSection = sections[next]
        selectedIndex = landingIndex(focusSection)
      }
      return
    }
    var f = sectionField(focusSection)
    if (f && !isChips(f)) {
      if (f.type === "integer") stepField(f, dx)
      else if (f.type === "boolean") setField(f, dx > 0)
      else cycleField(f, dx)
      return
    }
    var count = sectionCount(focusSection)
    if (count > 0) selectedIndex = Math.max(0, Math.min(count - 1, selectedIndex + dx))
  }

  function chooseKey(wheel, key) {
    if (!peel || usedElsewhere(wheel, key)) return
    peel.setKey(wheel, key)
  }

  function openItem(item) {
    if (!item || item.state !== "done" || !item.outputs || item.outputs.length === 0) return
    Quickshell.execDetached(["xdg-open", dirname(item.outputs[0])])
    root.close()
  }

  function activateCursor() {
    var s = focusSection
    var f = sectionField(s)
    if (s === "recent") {
      openItem(recent[selectedIndex])
    } else if (s === "quality") {
      if (peel && selectedIndex < qualityOptions.length) peel.setConfig("quality", qualityOptions[selectedIndex].id)
    } else if (s === "output") {
      if (selectedIndex < locationOptions.length) chooseLocation(locationOptions[selectedIndex].value)
    } else if (s === "folder") {
      chooseFolder()
    } else if (s === "advanced") {
      advancedOpen = !advancedOpen
    } else if (s === "resetall") {
      resetAll()
    } else if (f) {
      if (isChips(f)) setField(f, f.choices[selectedIndex].value)
      else if (f.type === "boolean") setField(f, !effectiveValue(f))
      else if (f.type === "integer") resetField(f)
      else cycleField(f, 1)
    } else if (selectedIndex >= 0 && selectedIndex < keyOptions.length) {
      chooseKey(focusSection, keyOptions[selectedIndex])
    }
  }

  function scrollItemIntoView(item) {
    if (!panelFlick || !item) return
    Qt.callLater(function() {
      if (!item) return
      var margin = Style.space(6)
      var top = item.mapToItem(panelFlick.contentItem, 0, 0).y
      var bottom = top + item.height
      var maxY = Math.max(0, panelFlick.contentHeight - panelFlick.height)
      if (top < panelFlick.contentY + margin) panelFlick.contentY = Math.max(0, top - margin)
      else if (bottom > panelFlick.contentY + panelFlick.height - margin)
        panelFlick.contentY = Math.min(maxY, bottom + margin - panelFlick.height)
    })
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onOpenedChanged: {
    if (!opened) return
    cursorActive = false
    focusSection = "convert"
    selectedIndex = landingIndex("convert")
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.barText
    foreground: root.barIconColor
    tooltipText: root.barTooltip
    onPressed: function(buttonCode) { root.toggle() }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(440))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(560))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) {
        if (!root.cursorActive) {
          root.cursorActive = true
          return
        }
        root.moveCursor(dx, dy)
      }
      onActivateRequested: { if (root.cursorActive) root.activateCursor() }
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Flickable {
        id: panelFlick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

      Column {
        id: column
        x: 1
        width: panelFlick.width - 2
        spacing: Style.space(12)

        // ---------- Hero ----------
        PanelHero {
          id: hero
          width: parent.width
          title: "Peel"
          meta: root.heroMeta
          foreground: root.foreground
          fontFamily: root.fontFamily
          iconOpacity: root.peel ? 1.0 : 0.5
          iconComponent: Component {
            Text {
              textFormat: Text.PlainText
              text: root.iconGlyph
              color: root.peel ? root.foreground : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.display
            }
          }
        }

        Rectangle {
          visible: root.busy
          width: parent.width
          height: Style.space(6)
          radius: height / 2
          color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.15)

          Rectangle {
            width: parent.width * Math.max(0, Math.min(100, root.activePct)) / 100
            height: parent.height
            radius: parent.radius
            color: root.foreground
            Behavior on width { NumberAnimation { duration: 150 } }
          }
        }

        Text {
          visible: root.heroIsError
          textFormat: Text.PlainText
          width: parent.width
          text: root.heroIsError ? "Key binds failed: " + root.peel.bindsError : ""
          color: root.urgent
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }

        // ---------- Keys ----------
        PanelSeparator {
          visible: root.peel !== null
          foreground: root.foreground
        }

        Repeater {
          model: root.peel ? root.wheels : []

          Column {
            id: wheelGroup
            required property var modelData
            width: column.width
            spacing: Style.space(8)
            readonly property string wheel: modelData.id

            PanelSectionHeader {
              text: wheelGroup.modelData.title + " KEY"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Flow {
              width: parent.width
              spacing: Style.space(6)

              Repeater {
                model: root.keyOptions

                Button {
                  required property var modelData
                  required property int index
                  readonly property bool taken: root.usedElsewhere(wheelGroup.wheel, String(modelData))

                  text: root.keyLabel(modelData)
                  fontSize: Style.font.bodySmall
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  horizontalPadding: Style.spacing.sm
                  verticalPadding: Style.spacing.controlPaddingY
                  bordered: true
                  opacity: taken ? 0.35 : 1.0
                  active: root.keys[wheelGroup.wheel] === String(modelData)
                  hasCursor: root.cursorAt(wheelGroup.wheel, index)
                  onClicked: root.chooseKey(wheelGroup.wheel, String(modelData))
                  onHovered: function(isHovered) {
                    if (isHovered) root.setCursor(wheelGroup.wheel, index)
                  }
                }
              }
            }
          }
        }

        // ---------- Quality ----------
        PanelSeparator {
          visible: root.peel !== null
          foreground: root.foreground
        }

        PanelSectionHeader {
          visible: root.peel !== null
          text: "QUALITY"
          foreground: root.foreground
          fontFamily: root.fontFamily
        }

        Flow {
          visible: root.peel !== null
          width: parent.width
          spacing: Style.space(6)

          Repeater {
            model: root.qualityOptions

            Button {
              required property var modelData
              required property int index
              text: String(modelData.label)
              fontSize: Style.font.bodySmall
              foreground: root.foreground
              fontFamily: root.fontFamily
              horizontalPadding: Style.spacing.sm
              verticalPadding: Style.spacing.controlPaddingY
              bordered: true
              active: modelData.id === root.quality
              hasCursor: root.cursorAt("quality", index)
              onClicked: if (root.peel) root.peel.setConfig("quality", modelData.id)
              onHovered: function(isHovered) { if (isHovered) root.setCursor("quality", index) }
            }
          }
        }

        Text {
          visible: root.peel !== null && root.qualityDescription !== ""
          textFormat: Text.PlainText
          width: parent.width
          text: root.qualityDescription
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }

        // ---------- Save to ----------
        PanelSectionHeader {
          visible: root.peel !== null && root.locationOptions.length > 0
          text: "SAVE TO"
          foreground: root.foreground
          fontFamily: root.fontFamily
        }

        Flow {
          visible: root.peel !== null && root.locationOptions.length > 0
          width: parent.width
          spacing: Style.space(6)

          Repeater {
            model: root.locationOptions

            Button {
              required property var modelData
              required property int index
              text: String(modelData.label)
              fontSize: Style.font.bodySmall
              foreground: root.foreground
              fontFamily: root.fontFamily
              horizontalPadding: Style.spacing.sm
              verticalPadding: Style.spacing.controlPaddingY
              bordered: true
              active: modelData.value === root.location
              hasCursor: root.cursorAt("output", index)
              onClicked: root.chooseLocation(modelData.value)
              onHovered: function(isHovered) { if (isHovered) root.setCursor("output", index) }
            }
          }
        }

        CursorSurface {
          id: folderRow
          visible: root.peel !== null && root.folderMode
          width: column.width
          hasCursor: root.cursorAt("folder", 0)
          onHasCursorChanged: if (hasCursor) root.scrollItemIntoView(folderRow)
          foreground: root.foreground
          implicitHeight: folderContent.implicitHeight + Style.spacing.rowPaddingX

          RowLayout {
            id: folderContent
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: Style.space(10)
            anchors.rightMargin: Style.space(10)
            spacing: Style.space(8)

            Text {
              textFormat: Text.PlainText
              Layout.fillWidth: true
              text: root.folder !== "" ? root.folder : "No folder chosen"
              color: root.folder !== "" ? root.foreground : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              elide: Text.ElideMiddle
            }

            Text {
              textFormat: Text.PlainText
              text: folderProc.running ? "Choosing…" : "Choose…"
              color: root.peelBlue
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }
          }

          MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onEntered: root.setCursor("folder", 0)
            onClicked: root.chooseFolder()
          }
        }

        Text {
          visible: root.peel !== null && root.peel.bindsError !== "" && !root.heroIsError
          textFormat: Text.PlainText
          width: parent.width
          text: root.peel ? root.peel.bindsError : ""
          color: root.urgent
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }

        // ---------- Advanced ----------
        DisclosureRow {
          visible: root.peel !== null && root.advancedFields.length > 0
          width: column.width
          section: "advanced"
          title: "Advanced"
          caption: root.overriddenKeys.length > 0 ? root.overriddenKeys.length + " customised" : "Fine-tune each format"
          expanded: root.advancedOpen
          onActivated: root.advancedOpen = !root.advancedOpen
        }

        Column {
          visible: root.peel !== null && root.advancedOpen
          width: column.width
          spacing: Style.space(6)

          Repeater {
            model: root.advancedOpen ? root.advancedGroups : []

            Column {
              id: advGroup
              required property var modelData
              width: column.width
              spacing: Style.space(4)

              SmallHeader { text: advGroup.modelData.name }

              Repeater {
                model: advGroup.modelData.fields
                FieldRow {
                  required property var modelData
                  field: modelData
                  width: column.width
                }
              }
            }
          }

          ActionRowLite {
            visible: root.overriddenKeys.length > 0
            width: column.width
            section: "resetall"
            title: root.resetting ? "Resetting…" : "Reset all to preset"
          }
        }

        // ---------- Recent ----------
        PanelSeparator {
          visible: root.peel !== null
          foreground: root.foreground
        }

        PanelSectionHeader {
          visible: root.peel !== null
          text: "RECENT"
          foreground: root.foreground
          fontFamily: root.fontFamily
        }

        Text {
          visible: root.peel !== null && root.recent.length === 0
          textFormat: Text.PlainText
          width: parent.width
          text: "Nothing converted yet"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }

        Column {
          width: parent.width
          spacing: Style.space(6)

          Repeater {
            model: root.recent

            CursorSurface {
              id: recentRow
              required property var modelData
              required property int index
              readonly property bool failed: modelData.state === "failed"
              width: column.width
              hasCursor: root.cursorAt("recent", index)
              foreground: root.foreground
              implicitHeight: recentContent.implicitHeight + Style.spacing.rowPaddingX

              ColumnLayout {
                id: recentContent
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Style.space(10)
                anchors.rightMargin: Style.space(10)
                spacing: Style.space(1)

                Text {
                  textFormat: Text.PlainText
                  Layout.fillWidth: true
                  text: root.jobText(recentRow.modelData)
                  color: recentRow.failed ? root.urgent : root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  elide: Text.ElideRight
                }

                Text {
                  textFormat: Text.PlainText
                  Layout.fillWidth: true
                  text: recentRow.failed
                    ? (recentRow.modelData.error || "Conversion failed")
                    : (recentRow.modelData.outputs && recentRow.modelData.outputs.length
                        ? root.basename(recentRow.modelData.outputs[0]) : "")
                  visible: text !== ""
                  color: recentRow.failed ? root.urgent : root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  elide: Text.ElideMiddle
                }
              }

              MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: recentRow.failed ? Qt.ArrowCursor : Qt.PointingHandCursor
                onEntered: root.setCursor("recent", recentRow.index)
                onClicked: root.openItem(recentRow.modelData)
              }
            }
          }
        }
      }
      }
    }
  }

  // Dim, uppercase-free label for small headings inside a settings block.
  component SmallHeader: Text {
    textFormat: Text.PlainText
    color: root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.bold: true
    topPadding: Style.space(4)
  }

  // Small clickable glyph (stepper arrows, reset).
  component GlyphButton: Text {
    id: glyphButton
    signal clicked()
    property bool enabledLook: true
    textFormat: Text.PlainText
    color: root.foreground
    opacity: enabledLook ? (glyphMouse.containsMouse ? 1.0 : 0.75) : 0.25
    font.family: root.fontFamily
    font.pixelSize: Style.font.body
    leftPadding: Style.space(4)
    rightPadding: Style.space(4)
    MouseArea {
      id: glyphMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: if (glyphButton.enabledLook) glyphButton.clicked()
    }
  }

  // Disclosure row: chevron, title, caption.
  component DisclosureRow: CursorSurface {
    id: disc
    property string section: ""
    property string title: ""
    property string caption: ""
    property bool expanded: false
    signal activated()

    hasCursor: root.cursorAt(disc.section, 0)
    onHasCursorChanged: if (disc.hasCursor) root.scrollItemIntoView(disc)
    foreground: root.foreground
    implicitHeight: discContent.implicitHeight + Style.spacing.rowPaddingX

    RowLayout {
      id: discContent
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(8)

      Text {
        textFormat: Text.PlainText
        text: disc.expanded ? "▾" : "▸"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }
      Text {
        textFormat: Text.PlainText
        text: disc.title
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }
      Text {
        textFormat: Text.PlainText
        Layout.fillWidth: true
        text: disc.caption
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: root.setCursor(disc.section, 0)
      onClicked: disc.activated()
    }
  }

  // One advanced field: label left, control right, reset when overridden.
  component FieldRow: CursorSurface {
    id: fr
    required property var field
    readonly property string section: "adv:" + field.key
    readonly property bool overridden: root.isOverridden(field)
    readonly property var value: root.effectiveValue(field)
    readonly property color valueColor: overridden ? root.peelBlue : root.dim

    hasCursor: root.focusSection === section && root.cursorActive
    onHasCursorChanged: if (fr.hasCursor) root.scrollItemIntoView(fr)
    foreground: root.foreground
    implicitHeight: Math.max(frLabel.implicitHeight, frControls.implicitHeight) + Style.spacing.rowPaddingX

    RowLayout {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(8)
      spacing: Style.space(8)

      Text {
        id: frLabel
        textFormat: Text.PlainText
        Layout.fillWidth: true
        text: fr.field.label
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        elide: Text.ElideRight
      }

      RowLayout {
        id: frControls
        spacing: Style.space(4)

        // integer stepper
        GlyphButton {
          visible: fr.field.type === "integer"
          text: "−"
          enabledLook: Number(fr.value) > fr.field.min
          onClicked: { root.setCursor(fr.section, 0); root.stepField(fr.field, -1) }
        }
        Text {
          visible: fr.field.type === "integer"
          textFormat: Text.PlainText
          text: root.displayValue(fr.field)
          color: fr.valueColor
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          horizontalAlignment: Text.AlignHCenter
          Layout.minimumWidth: Style.space(44)
        }
        GlyphButton {
          visible: fr.field.type === "integer"
          text: "+"
          enabledLook: Number(fr.value) < fr.field.max
          onClicked: { root.setCursor(fr.section, 0); root.stepField(fr.field, 1) }
        }

        // enum, few choices: chips
        Repeater {
          model: root.isChips(fr.field) ? fr.field.choices : []
          Button {
            required property var modelData
            required property int index
            text: String(modelData.label)
            fontSize: Style.font.bodySmall
            foreground: root.foreground
            fontFamily: root.fontFamily
            horizontalPadding: Style.spacing.sm
            verticalPadding: Style.spacing.controlPaddingY
            bordered: true
            active: String(modelData.value) === String(fr.value)
            hasCursor: root.cursorAt(fr.section, index)
            onClicked: root.setField(fr.field, modelData.value)
            onHovered: function(isHovered) { if (isHovered) root.setCursor(fr.section, index) }
          }
        }

        // enum, many choices: cycle
        GlyphButton {
          visible: root.isCycle(fr.field)
          text: "◂"
          onClicked: { root.setCursor(fr.section, 0); root.cycleField(fr.field, -1) }
        }
        Text {
          visible: root.isCycle(fr.field)
          textFormat: Text.PlainText
          text: root.displayValue(fr.field)
          color: fr.valueColor
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          horizontalAlignment: Text.AlignHCenter
          Layout.minimumWidth: Style.space(60)
        }
        GlyphButton {
          visible: root.isCycle(fr.field)
          text: "▸"
          onClicked: { root.setCursor(fr.section, 0); root.cycleField(fr.field, 1) }
        }

        // boolean
        ToggleSwitch {
          visible: fr.field.type === "boolean"
          checked: fr.value === true
          interactive: false
          foreground: root.foreground
          opacity: fr.overridden ? 1.0 : 0.6
        }

        // reset (keeps its width so rows line up)
        GlyphButton {
          text: "↺"
          opacity: fr.overridden ? 0.9 : 0.0
          enabledLook: fr.overridden
          color: root.peelBlue
          onClicked: root.resetField(fr.field)
        }
      }
    }

    MouseArea {
      anchors.fill: parent
      z: -1
      hoverEnabled: true
      onEntered: root.setCursor(fr.section, root.isChips(fr.field) ? root.landingIndex(fr.section) : 0)
      onClicked: {
        if (fr.field.type === "boolean") root.setField(fr.field, !fr.value)
      }
    }
  }

  component ActionRowLite: CursorSurface {
    id: arl
    property string section: ""
    property string title: ""
    hasCursor: root.cursorAt(arl.section, 0)
    onHasCursorChanged: if (arl.hasCursor) root.scrollItemIntoView(arl)
    foreground: root.foreground
    implicitHeight: arlText.implicitHeight + Style.spacing.rowPaddingX
    Text {
      id: arlText
      anchors.verticalCenter: parent.verticalCenter
      anchors.left: parent.left
      anchors.leftMargin: Style.space(10)
      textFormat: Text.PlainText
      text: "↺  " + arl.title
      color: root.peelBlue
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
    }
    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: root.setCursor(arl.section, 0)
      onClicked: root.resetAll()
    }
  }
}
