import QtQuick

// Options card for a tool with settings (Split pages, Rotate, Compress, ...).
// Standalone like Wheel.qml: no qs.Commons here; Catcher passes the colours in.
//
// Contract: docs/tool-options.md. The card is driven by field definitions
// (`peel config --json` options.tools) and talks to the service only for
// `peel-tool info` (page count) and `peel-tool check` (live summary / error).
//
// Catcher calls begin(...) to open it and end() to close it, and listens for
// runRequested(opts, saved) / cancelRequested().
//   opts:  { key: "value" } for every visible field (pages left out when empty)
//   saved: { key: value } for the remember:true fields when "Remember these
//          settings" is ticked, otherwise {}
Item {
    id: card

    property var service: null

    property color accent: "#4a9eff"
    // Text and outlines on the accent: fixed dark, as in Wheel.qml.
    property color accentInk: "#0b0f14"
    property color background: "#1e1e2e"
    property color foreground: "#cdd6f4"
    property color dim: "#6c7086"
    property color warn: "#e8a64a"
    property string fontFamily: ""

    // Set by begin()
    property string toolId: ""
    property string toolLabel: ""
    property var paths: []
    property var fields: []
    property var values: ({})

    property bool remember: false
    // Focus stops: 0..n-1 are the fields, then Remember, Cancel, Run.
    property int focusStop: 0

    property int pageCount: 0
    property var fileKinds: []
    property int outputs: 0
    // Enter pressed while a check is pending: run when it comes back ok.
    property bool submitQueued: false
    property bool pending: false
    property bool checkOk: false
    property string summary: ""
    property string error: ""
    property int checkGen: 0
    property int infoGen: 0

    signal runRequested(var opts, var saved)
    signal cancelRequested()

    readonly property int fieldCount: fields.length
    readonly property int rememberStop: fieldCount
    readonly property int cancelStop: fieldCount + 1
    readonly property int runStop: fieldCount + 2
    readonly property int filesStop: fieldCount + 3

    // The files in the order Run will pass them, with their per-file pages text
    // (keyed by path, so it stays with its file when rows move) and page counts.
    property var order: []
    property var perFileText: ({})
    property var pageByPath: ({})
    property int selectedRow: 0
    property bool rowEditing: false
    // Cap for the whole card (Catcher sets about 80% of the screen); 0 = none.
    property real maxHeight: 0
    readonly property bool hasFiles: {
        for (var i = 0; i < fields.length; i++)
            if (fields[i].perFile === true && isShown(fields[i])) return order.length > 0
        return false
    }
    readonly property real listHeight: Math.min(order.length * 32, 192,
        Math.max(64, maxHeight > 0 ? maxHeight - 420 : 192))
    readonly property bool canRun: !pending && checkOk
    readonly property color line: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.14)
    readonly property color chipFill: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.10)

    width: 360
    height: content.implicitHeight + 32
    visible: false
    focus: true

    readonly property string fileName: {
        if (paths.length === 1) return String(paths[0]).split("/").pop()
        return paths.length + " files"
    }
    readonly property string subtitle: pageCount > 0
        ? fileName + "  ·  " + pageCount + (pageCount === 1 ? " page" : " pages")
        : fileName

    // --- lifecycle ------------------------------------------------------------

    function begin(id, label, filePaths, fieldList, effective) {
        toolId = id
        toolLabel = label
        paths = filePaths
        fields = fieldList
        order = filePaths.slice()
        perFileText = ({})
        pageByPath = ({})
        selectedRow = 0
        rowEditing = false
        var v = {}
        for (var i = 0; i < fieldList.length; i++) {
            var f = fieldList[i]
            var saved = effective ? effective[f.key] : undefined
            v[f.key] = saved !== undefined && saved !== null ? saved : f["default"]
        }
        values = v
        remember = false
        pageCount = 0
        fileKinds = []
        outputs = 0
        submitQueued = false
        summary = ""
        error = ""
        checkOk = false
        pending = true
        checkGen++
        infoGen++
        var firstStop = visibleStops()[0]
        focusStop = firstStop !== undefined ? firstStop : runStop
        visible = true
        applyFocus()
        loadInfo()
        debounce.restart()
    }

    function end() {
        checkGen++
        infoGen++
        debounce.stop()
        visible = false
        paths = []
        fields = []
        values = ({})
        pageInputs = ({})
        submitQueued = false
        fileKinds = []
        order = []
        perFileText = ({})
        pageByPath = ({})
        rowEditing = false
    }

    function loadInfo() {
        if (!service) return
        var gen = infoGen
        service.infoFor(paths, function(info) {
            if (gen !== card.infoGen) return
            var total = 0
            var files = info && info.files ? info.files : []
            for (var i = 0; i < files.length; i++)
                if (typeof files[i].pages === "number") total += files[i].pages
            card.pageCount = total
            var kinds = []
            for (var j = 0; j < files.length; j++) kinds.push(String(files[j].kind || ""))
            card.fileKinds = kinds
            var counts = {}
            for (var m = 0; m < files.length; m++)
                if (typeof files[m].pages === "number") counts[String(files[m].path)] = files[m].pages
            card.pageByPath = counts
            card.clampAt()
            // Fields limited to some kinds appear (or not) now.
            card.refreshStops()
            card.scheduleCheck()
        })
    }

    // --- values -----------------------------------------------------------------

    function isShown(f) {
        if (f.kinds && f.kinds.length) {
            if (!fileKinds.length) return false
            for (var k = 0; k < fileKinds.length; k++)
                if (f.kinds.indexOf(fileKinds[k]) < 0) return false
        }
        var w = f.showWhen
        if (!w) return true
        var current = String(values[w.key])
        var list = w.in || []
        for (var i = 0; i < list.length; i++)
            if (String(list[i]) === current) return true
        return false
    }

    // A normal row: shown and not a per-file field (those live in the file list).
    function isRow(f) {
        return isShown(f) && f.perFile !== true
    }

    function setValue(key, value) {
        var next = Object.assign({}, values)
        next[key] = value
        values = next
        submitQueued = false
        refreshStops()
        scheduleCheck()
    }

    // A field may have just appeared or vanished.
    function refreshStops() {
        var stops = visibleStops()
        if (stops.indexOf(focusStop) < 0) focusStop = stops[0] !== undefined ? stops[0] : runStop
    }

    function isOn(v) {
        return v === true || v === "true"
    }

    function currentOpts() {
        var opts = {}
        for (var i = 0; i < fields.length; i++) {
            var f = fields[i]
            if (!isShown(f)) continue
            if (f.perFile === true) {
                // merge-pdf.pages.<i>: 1-based, in the current order, only when non-empty
                for (var j = 0; j < order.length; j++) {
                    var text = String(perFileText[order[j]] || "").trim()
                    if (text !== "") opts[f.key + "." + (j + 1)] = text
                }
                continue
            }
            var v = values[f.key]
            if (f.type === "pages" && String(v).trim() === "") continue
            opts[f.key] = String(v)
        }
        return opts
    }

    function scheduleCheck() {
        checkGen++
        pending = true
        debounce.restart()
    }

    function runCheck() {
        if (!service || !visible) return
        var gen = checkGen
        service.checkTool(toolId, currentOpts(), order, function(result) {
            if (gen !== card.checkGen) return
            card.pending = false
            card.outputs = result && typeof result.outputs === "number" ? result.outputs : 0
            card.checkOk = !!(result && result.ok)
            card.error = result && result.error ? String(result.error) : ""
            card.summary = result && result.summary ? String(result.summary) : ""
            var go = card.submitQueued
            card.submitQueued = false
            if (go && card.checkOk) card.submit()
        })
    }

    Timer { id: debounce; interval: 200; onTriggered: card.runCheck() }

    function choiceLabel(f, value) {
        var list = f.choices || []
        for (var i = 0; i < list.length; i++)
            if (String(list[i].value) === String(value)) return String(list[i].label)
        return String(value)
    }

    function cycle(f, delta) {
        var list = f.choices || []
        if (!list.length) return
        var at = 0
        for (var i = 0; i < list.length; i++)
            if (String(list[i].value) === String(values[f.key])) at = i
        setValue(f.key, list[((at + delta) % list.length + list.length) % list.length].value)
    }

    // The "After page" limit is the first file's page count once known.
    function fieldMax(f) {
        var hi = f.max !== undefined ? f.max : 1e9
        if (f.key === "merge-pdf.at" && order.length) {
            var n = pageByPath[order[0]]
            if (typeof n === "number") hi = Math.min(hi, n)
        }
        return hi
    }

    function clampAt() {
        for (var i = 0; i < fields.length; i++) {
            var f = fields[i]
            if (f.key !== "merge-pdf.at") continue
            var hi = fieldMax(f)
            if (Number(values[f.key]) > hi) setValue(f.key, hi)
        }
    }

    // --- file list ----------------------------------------------------------

    function setOrder(list, selectPath) {
        order = list
        var at = selectPath !== undefined ? list.indexOf(selectPath) : selectedRow
        selectedRow = Math.max(0, Math.min(list.length - 1, at))
        submitQueued = false
        clampAt()
        scheduleCheck()
        refocusRow()
    }

    function moveFile(from, to) {
        if (to < 0 || to >= order.length || from === to) return
        var list = order.slice()
        var item = list.splice(from, 1)[0]
        list.splice(to, 0, item)
        setOrder(list, item)
    }

    // "file2" before "file10".
    function naturalCompare(a, b) {
        var pa = a.match(/(\d+|\D+)/g) || []
        var pb = b.match(/(\d+|\D+)/g) || []
        for (var i = 0; i < Math.min(pa.length, pb.length); i++) {
            var x = pa[i], y = pb[i]
            if (x === y) continue
            var nx = /^\d/.test(x), ny = /^\d/.test(y)
            if (nx && ny) { var d = Number(x) - Number(y); if (d !== 0) return d }
            return x < y ? -1 : 1
        }
        return pa.length - pb.length
    }

    function sortByName() {
        var keep = order[selectedRow]
        var list = order.slice().sort(function(a, b) {
            return card.naturalCompare(String(a).split("/").pop().toLowerCase(),
                                       String(b).split("/").pop().toLowerCase())
        })
        setOrder(list, keep)
    }

    function reverseOrder() {
        setOrder(order.slice().reverse(), order[selectedRow])
    }

    function selectRow(i) {
        selectedRow = Math.max(0, Math.min(order.length - 1, i))
        refocusRow()
    }

    function setFileText(path, text) {
        var next = Object.assign({}, perFileText)
        next[path] = text
        perFileText = next
        submitQueued = false
        scheduleCheck()
    }

    // After a move or a selection change: scroll to the row, and keep the caret
    // in its pages box if that is where the user was.
    function refocusRow() {
        Qt.callLater(function() {
            if (!card.visible) return
            if (card.rowEditing) card.focusRowInput()
            else card.forceActiveFocus()
        })
    }

    property var fileList: null

    function focusRowInput() {
        if (!fileList) return
        fileList.positionViewAtIndex(selectedRow, ListView.Contain)
        var item = fileList.itemAtIndex(selectedRow)
        if (item && item.input) item.input.forceActiveFocus()
    }

    function stepInt(f, delta) {
        var step = f.step || 1
        var lo = f.min !== undefined ? f.min : -1e9
        var hi = fieldMax(f)
        var next = Math.max(lo, Math.min(hi, Number(values[f.key]) + delta * step))
        if (next !== Number(values[f.key])) setValue(f.key, next)
    }

    function submit() {
        if (pending) { submitQueued = true; return }
        if (!canRun) return
        var saved = {}
        if (remember) {
            for (var i = 0; i < fields.length; i++)
                if (fields[i].remember === true) saved[fields[i].key] = values[fields[i].key]
        }
        runRequested(currentOpts(), saved)
    }

    // --- focus and keys ---------------------------------------------------------

    // Pages text boxes by field index.
    property var pageInputs: ({})

    function visibleStops() {
        var out = []
        if (hasFiles) out.push(filesStop)
        for (var i = 0; i < fields.length; i++) if (isRow(fields[i])) out.push(i)
        out.push(rememberStop, cancelStop, runStop)
        return out
    }

    function moveStop(dir) {
        var stops = visibleStops()
        var at = stops.indexOf(focusStop)
        focusStop = stops[((at < 0 ? 0 : at) + dir + stops.length) % stops.length]
    }

    function setStop(stop) {
        focusStop = stop
        applyFocus()
    }

    function applyFocus() {
        if (focusStop === filesStop && rowEditing) { focusRowInput(); return }
        var f = focusStop < fields.length ? fields[focusStop] : null
        var input = f && f.type === "pages" ? pageInputs[focusStop] : null
        if (input) input.forceActiveFocus()
        else card.forceActiveFocus()
    }

    onFocusStopChanged: { rowEditing = false; applyFocus() }

    // inText: the pages box has focus, so Left/Right/Space belong to it.
    function handleKey(event, inText) {
        var key = event.key
        if (key === Qt.Key_Escape) { cancelRequested(); return true }
        var back = key === Qt.Key_Backtab || (key === Qt.Key_Tab && (event.modifiers & Qt.ShiftModifier))
        if (focusStop === filesStop) {
            // The file list: Up/Down select, Alt/Ctrl+Up/Down move the file,
            // Tab enters the row's pages box and the next Tab leaves the list.
            if (key === Qt.Key_Up || key === Qt.Key_Down) {
                var d = key === Qt.Key_Down ? 1 : -1
                if (event.modifiers & (Qt.AltModifier | Qt.ControlModifier)) moveFile(selectedRow, selectedRow + d)
                else selectRow(selectedRow + d)
                return true
            }
            if (back) {
                if (rowEditing) { rowEditing = false; applyFocus() } else moveStop(-1)
                return true
            }
            if (key === Qt.Key_Tab) {
                if (rowEditing) moveStop(1)
                else { rowEditing = true; focusRowInput() }
                return true
            }
            if (!inText && key === Qt.Key_A) { sortByName(); return true }
            if (!inText && key === Qt.Key_R) { reverseOrder(); return true }
        }
        if (back) { moveStop(-1); return true }
        if (key === Qt.Key_Tab || key === Qt.Key_Down) { moveStop(1); return true }
        if (key === Qt.Key_Up) { moveStop(-1); return true }
        if (key === Qt.Key_Return || key === Qt.Key_Enter) {
            if (focusStop === cancelStop) cancelRequested()
            else submit()
            return true
        }
        if (inText) return false
        var f = focusStop < fields.length ? fields[focusStop] : null
        if (key === Qt.Key_Left || key === Qt.Key_Right) {
            var delta = key === Qt.Key_Right ? 1 : -1
            if (!f) return true
            if (f.type === "enum") cycle(f, delta)
            else if (f.type === "integer") stepInt(f, delta)
            else if (f.type === "boolean") setValue(f.key, delta > 0)
            return true
        }
        if (key === Qt.Key_Space) {
            if (f && f.type === "boolean") setValue(f.key, !isOn(values[f.key]))
            else if (focusStop === rememberStop) remember = !remember
            else if (focusStop === cancelStop) cancelRequested()
            else if (focusStop === runStop) submit()
            return true
        }
        return false
    }

    Keys.onPressed: (event) => { event.accepted = card.handleKey(event, false) }

    // --- look -------------------------------------------------------------------

    component Ring: Rectangle {
        property bool on: false
        anchors.fill: parent
        anchors.margins: -4
        radius: 10
        color: "transparent"
        border.width: on ? 2 : 0
        border.color: card.accent
    }

    Rectangle {
        anchors.fill: parent
        radius: 18
        color: card.background
        border.width: 1
        border.color: card.line
    }

    // Swallows clicks on the card's own blank areas (Catcher cancels on a click outside).
    MouseArea { anchors.fill: parent; onClicked: card.applyFocus() }

    Column {
        id: content
        x: 16
        y: 16
        width: parent.width - 32
        spacing: 12

        Column {
            width: parent.width
            spacing: 2
            Text {
                width: parent.width
                text: card.toolLabel
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: card.foreground
                font.family: card.fontFamily
                font.pixelSize: 18
                font.bold: true
            }
            Text {
                width: parent.width
                text: card.subtitle
                textFormat: Text.PlainText
                elide: Text.ElideMiddle
                color: card.dim
                font.family: card.fontFamily
                font.pixelSize: 13
            }
        }

        // Files (merge): order, and which pages of each
        Column {
            visible: card.hasFiles
            width: parent.width
            spacing: 6

            Row {
                spacing: 6
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Files"
                    color: card.dim
                    font.family: card.fontFamily
                    font.pixelSize: 12
                    width: 60
                }
                Repeater {
                    model: [["Name A→Z", 0], ["Reverse", 1]]
                    delegate: Rectangle {
                        id: orderChip
                        required property var modelData
                        width: orderChipText.implicitWidth + 20
                        height: 24
                        radius: 12
                        color: card.chipFill
                        Text {
                            id: orderChipText
                            anchors.centerIn: parent
                            text: orderChip.modelData[0]
                            color: card.foreground
                            font.family: card.fontFamily
                            font.pixelSize: 12
                        }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: { card.setStop(card.filesStop); if (orderChip.modelData[1] === 0) card.sortByName(); else card.reverseOrder() }
                        }
                    }
                }
            }

            Item {
                width: parent.width
                height: card.listHeight
                Ring { on: card.focusStop === card.filesStop && !card.rowEditing; anchors.margins: -3 }

                ListView {
                    id: fileView
                    anchors.fill: parent
                    clip: true
                    model: card.order
                    boundsBehavior: Flickable.StopAtBounds
                    interactive: contentHeight > height
                    Component.onCompleted: card.fileList = fileView

                    delegate: Rectangle {
                        id: fileRow
                        required property string modelData
                        required property int index
                        readonly property bool current: card.selectedRow === index
                        property alias input: fileInput
                        width: fileView.width - (fileView.interactive ? 6 : 0)
                        height: 32
                        radius: 8
                        color: current ? card.chipFill : "transparent"
                        border.width: current && card.focusStop === card.filesStop ? 1 : 0
                        border.color: card.accent

                        MouseArea {
                            anchors.fill: parent
                            onClicked: { card.selectedRow = fileRow.index; card.setStop(card.filesStop) }
                        }
                        Text {
                            id: posText
                            x: 6
                            width: 18
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            text: String(fileRow.index + 1)
                            color: card.dim
                            font.family: card.fontFamily
                            font.pixelSize: 12
                        }
                        Text {
                            x: 26
                            width: parent.width - 26 - 22 - 22 - 80 - 40 - 12
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            text: fileRow.modelData.split("/").pop()
                            textFormat: Text.PlainText
                            elide: Text.ElideMiddle
                            color: card.foreground
                            font.family: card.fontFamily
                            font.pixelSize: 13
                        }
                        Text {
                            id: countText
                            anchors.right: fileBox.left
                            anchors.rightMargin: 4
                            width: 36
                            height: parent.height
                            horizontalAlignment: Text.AlignRight
                            verticalAlignment: Text.AlignVCenter
                            text: card.pageByPath[fileRow.modelData] !== undefined ? card.pageByPath[fileRow.modelData] + " p" : ""
                            color: card.dim
                            font.family: card.fontFamily
                            font.pixelSize: 12
                        }
                        Rectangle {
                            id: fileBox
                            anchors.right: upBtn.left
                            anchors.rightMargin: 4
                            anchors.verticalCenter: parent.verticalCenter
                            width: 76
                            height: 24
                            radius: 6
                            color: Qt.rgba(card.foreground.r, card.foreground.g, card.foreground.b, 0.10)
                            border.width: fileInput.activeFocus ? 2 : 0
                            border.color: card.accent
                            TextInput {
                                id: fileInput
                                anchors.fill: parent
                                anchors.leftMargin: 6
                                anchors.rightMargin: 6
                                verticalAlignment: TextInput.AlignVCenter
                                clip: true
                                maximumLength: 500
                                selectByMouse: true
                                color: card.foreground
                                selectionColor: card.accent
                                selectedTextColor: card.accentInk
                                font.family: card.fontFamily
                                font.pixelSize: 12
                                text: String(card.perFileText[fileRow.modelData] || "")
                                onTextEdited: card.setFileText(fileRow.modelData, text)
                                onActiveFocusChanged: if (activeFocus) {
                                    card.rowEditing = true
                                    card.selectedRow = fileRow.index
                                    card.focusStop = card.filesStop
                                }
                                Keys.onPressed: (event) => { event.accepted = card.handleKey(event, true) }
                                Text {
                                    anchors.fill: parent
                                    verticalAlignment: Text.AlignVCenter
                                    visible: fileInput.text.length === 0
                                    text: "All"
                                    color: card.dim
                                    font.family: card.fontFamily
                                    font.pixelSize: 12
                                }
                            }
                        }
                        Text {
                            id: upBtn
                            anchors.right: downBtn.left
                            width: 22
                            height: parent.height
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            text: "↑"
                            opacity: fileRow.index > 0 ? 1 : 0.3
                            color: card.foreground
                            font.pixelSize: 15
                            MouseArea { anchors.fill: parent; onClicked: { card.setStop(card.filesStop); card.moveFile(fileRow.index, fileRow.index - 1) } }
                        }
                        Text {
                            id: downBtn
                            anchors.right: parent.right
                            width: 22
                            height: parent.height
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            text: "↓"
                            opacity: fileRow.index < card.order.length - 1 ? 1 : 0.3
                            color: card.foreground
                            font.pixelSize: 15
                            MouseArea { anchors.fill: parent; onClicked: { card.setStop(card.filesStop); card.moveFile(fileRow.index, fileRow.index + 1) } }
                        }
                    }

                    // Scroll position, when the list is longer than its box
                    Rectangle {
                        visible: fileView.interactive
                        x: fileView.width - 4
                        width: 3
                        radius: 1.5
                        color: card.dim
                        opacity: 0.6
                        y: fileView.visibleArea.yPosition * fileView.height
                        height: Math.max(12, fileView.visibleArea.heightRatio * fileView.height)
                    }
                }
            }
        }

        Repeater {
            model: card.fields

            delegate: Column {
                id: row
                required property var modelData
                required property int index

                readonly property var field: modelData
                readonly property string kind: {
                    if (field.type === "enum") return (field.choices || []).length <= 6 ? "chips" : "cycle"
                    return field.type
                }
                readonly property bool stopped: card.focusStop === index

                visible: card.isRow(field)
                width: parent.width
                spacing: 6

                Text {
                    text: row.field.label
                    textFormat: Text.PlainText
                    color: card.dim
                    font.family: card.fontFamily
                    font.pixelSize: 12
                }

                Item {
                    id: ctl
                    width: parent.width
                    height: row.kind === "chips" ? chips.implicitHeight : 32

                    Ring { on: row.stopped && row.kind !== "chips" && row.kind !== "pages" }

                    // enum, up to 4 choices
                    Flow {
                        id: chips
                        visible: row.kind === "chips"
                        width: parent.width
                        spacing: 6
                        Repeater {
                            model: row.field.choices || []
                            delegate: Rectangle {
                                id: chip
                                required property var modelData
                                readonly property bool selected: String(modelData.value) === String(card.values[row.field.key])
                                width: chipText.implicitWidth + 24
                                height: 30
                                radius: 15
                                color: selected ? card.accent : card.chipFill
                                border.width: row.stopped && selected ? 2 : 0
                                border.color: card.foreground
                                Text {
                                    id: chipText
                                    anchors.centerIn: parent
                                    text: String(chip.modelData.label)
                                    textFormat: Text.PlainText
                                    color: chip.selected ? card.accentInk : card.foreground
                                    font.family: card.fontFamily
                                    font.pixelSize: 13
                                    font.bold: chip.selected
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    onClicked: { card.setStop(row.index); card.setValue(row.field.key, chip.modelData.value) }
                                }
                            }
                        }
                    }
                    Ring {
                        visible: row.kind === "chips"
                        on: row.stopped
                        anchors.margins: -3
                        radius: 18
                    }

                    // enum, more than 4 choices
                    Row {
                        visible: row.kind === "cycle"
                        anchors.fill: parent
                        Text {
                            width: 36; height: parent.height
                            text: "‹"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            color: card.foreground
                            font.family: card.fontFamily
                            font.pixelSize: 22
                            MouseArea { anchors.fill: parent; onClicked: { card.setStop(row.index); card.cycle(row.field, -1) } }
                        }
                        Text {
                            width: parent.width - 72; height: parent.height
                            text: card.choiceLabel(row.field, card.values[row.field.key])
                            textFormat: Text.PlainText
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            color: card.foreground
                            font.family: card.fontFamily
                            font.pixelSize: 14
                            font.bold: true
                        }
                        Text {
                            width: 36; height: parent.height
                            text: "›"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            color: card.foreground
                            font.family: card.fontFamily
                            font.pixelSize: 22
                            MouseArea { anchors.fill: parent; onClicked: { card.setStop(row.index); card.cycle(row.field, 1) } }
                        }
                    }

                    // integer
                    Row {
                        visible: row.kind === "integer"
                        anchors.fill: parent
                        Rectangle {
                            width: 36; height: parent.height; radius: 8; color: card.chipFill
                            Text {
                                anchors.centerIn: parent
                                text: "−"
                                color: card.foreground
                                font.family: card.fontFamily
                                font.pixelSize: 20
                            }
                            MouseArea { anchors.fill: parent; onClicked: { card.setStop(row.index); card.stepInt(row.field, -1) } }
                        }
                        Text {
                            width: parent.width - 72; height: parent.height
                            text: String(card.values[row.field.key]) + (row.field.unit ? " " + row.field.unit : "")
                            textFormat: Text.PlainText
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            color: card.foreground
                            font.family: card.fontFamily
                            font.pixelSize: 14
                            font.bold: true
                        }
                        Rectangle {
                            width: 36; height: parent.height; radius: 8; color: card.chipFill
                            Text {
                                anchors.centerIn: parent
                                text: "+"
                                color: card.foreground
                                font.family: card.fontFamily
                                font.pixelSize: 20
                            }
                            MouseArea { anchors.fill: parent; onClicked: { card.setStop(row.index); card.stepInt(row.field, 1) } }
                        }
                    }

                    // boolean
                    Row {
                        visible: row.kind === "boolean"
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 10
                        Rectangle {
                            width: 42; height: 24; radius: 12
                            color: card.isOn(card.values[row.field.key]) ? card.accent : card.chipFill
                            Rectangle {
                                width: 18; height: 18; radius: 9
                                y: 3
                                x: card.isOn(card.values[row.field.key]) ? 21 : 3
                                color: card.isOn(card.values[row.field.key]) ? card.accentInk : card.foreground
                            }
                            MouseArea {
                                anchors.fill: parent
                                onClicked: { card.setStop(row.index); card.setValue(row.field.key, !card.isOn(card.values[row.field.key])) }
                            }
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: card.isOn(card.values[row.field.key]) ? "On" : "Off"
                            color: card.foreground
                            font.family: card.fontFamily
                            font.pixelSize: 13
                        }
                    }

                    // pages
                    Rectangle {
                        visible: row.kind === "pages"
                        anchors.fill: parent
                        radius: 8
                        color: card.chipFill
                        border.width: row.stopped ? 2 : 0
                        border.color: card.accent
                        TextInput {
                            id: pagesBox
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            verticalAlignment: TextInput.AlignVCenter
                            clip: true
                            maximumLength: 500
                            selectByMouse: true
                            color: card.foreground
                            selectionColor: card.accent
                            selectedTextColor: card.accentInk
                            font.family: card.fontFamily
                            font.pixelSize: 14
                            text: String(card.values[row.field.key] === undefined ? "" : card.values[row.field.key])
                            onTextEdited: card.setValue(row.field.key, text)
                            onActiveFocusChanged: if (activeFocus) card.focusStop = row.index
                            Keys.onPressed: (event) => { event.accepted = card.handleKey(event, true) }
                            Component.onCompleted: if (row.kind === "pages") {
                                var map = Object.assign({}, card.pageInputs)
                                map[row.index] = pagesBox
                                card.pageInputs = map
                            }
                            Text {
                                anchors.fill: parent
                                verticalAlignment: Text.AlignVCenter
                                visible: pagesBox.text.length === 0
                                text: row.field.placeholder || ""
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                color: card.dim
                                font.family: card.fontFamily
                                font.pixelSize: 14
                            }
                        }
                    }
                }

                // Quick picks for a pages box
                Row {
                    visible: row.kind === "pages"
                    spacing: 6
                    Repeater {
                        model: [["All", ""], ["Odd", "odd"], ["Even", "even"]]
                        delegate: Rectangle {
                            id: quick
                            required property var modelData
                            readonly property bool selected: String(card.values[row.field.key] === undefined ? "" : card.values[row.field.key]).trim().toLowerCase() === modelData[1]
                            width: quickText.implicitWidth + 20
                            height: 24
                            radius: 12
                            color: selected ? card.accent : card.chipFill
                            Text {
                                id: quickText
                                anchors.centerIn: parent
                                text: quick.modelData[0]
                                color: quick.selected ? card.accentInk : card.foreground
                                font.family: card.fontFamily
                                font.pixelSize: 12
                            }
                            MouseArea {
                                anchors.fill: parent
                                onClicked: { card.setStop(row.index); card.setValue(row.field.key, quick.modelData[1]) }
                            }
                        }
                    }
                }
            }
        }

        // Live preview of what Run would do
        Text {
            width: parent.width
            text: card.error !== "" ? card.error : (card.summary !== "" ? card.summary : (card.pending ? "Checking…" : ""))
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            maximumLineCount: 3
            elide: Text.ElideRight
            opacity: card.pending ? 0.55 : 1
            color: card.error !== "" ? card.warn : card.dim
            font.family: card.fontFamily
            font.pixelSize: 13
        }

        // Many outputs: say so before it happens
        Text {
            width: parent.width
            visible: card.outputs > 50 && card.error === ""
            text: "Makes " + card.outputs + " files"
            textFormat: Text.PlainText
            color: card.warn
            font.family: card.fontFamily
            font.pixelSize: 13
            font.bold: true
        }

        // Remember
        Item {
            width: parent.width
            height: 24
            Ring { on: card.focusStop === card.rememberStop }
            Rectangle {
                id: box
                width: 18; height: 18; radius: 5
                anchors.verticalCenter: parent.verticalCenter
                color: card.remember ? card.accent : "transparent"
                border.width: 1.5
                border.color: card.remember ? card.accent : card.dim
                Text {
                    anchors.centerIn: parent
                    visible: card.remember
                    text: "✓"
                    color: card.accentInk
                    font.pixelSize: 13
                    font.bold: true
                }
            }
            Text {
                anchors.left: box.right
                anchors.leftMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                text: "Remember these settings"
                color: card.foreground
                font.family: card.fontFamily
                font.pixelSize: 13
            }
            MouseArea {
                anchors.fill: parent
                onClicked: { card.setStop(card.rememberStop); card.remember = !card.remember }
            }
        }

        Row {
            anchors.right: parent.right
            spacing: 10

            Item {
                width: 84; height: 34
                Ring { on: card.focusStop === card.cancelStop }
                Rectangle {
                    anchors.fill: parent
                    radius: 17
                    color: card.chipFill
                    Text {
                        anchors.centerIn: parent
                        text: "Cancel"
                        color: card.foreground
                        font.family: card.fontFamily
                        font.pixelSize: 14
                    }
                }
                MouseArea { anchors.fill: parent; onClicked: card.cancelRequested() }
            }

            Item {
                width: 84; height: 34
                Ring { on: card.focusStop === card.runStop }
                Rectangle {
                    anchors.fill: parent
                    radius: 17
                    color: card.accent
                    opacity: card.canRun ? 1 : 0.35
                    Text {
                        anchors.centerIn: parent
                        text: "Run"
                        color: card.accentInk
                        font.family: card.fontFamily
                        font.pixelSize: 14
                        font.bold: true
                    }
                }
                MouseArea { anchors.fill: parent; onClicked: card.submit() }
            }
        }
    }
}
