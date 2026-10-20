import QtQuick
import QtQuick.Shapes

// Radial format picker. Standalone: no Omarchy / qs.Commons dependencies.
// Segment 0 is centred at 12 o'clock, segments run clockwise.
Item {
    id: root

    property var segments: []
    property string title: "Convert"
    property var modes: []
    property string currentMode: "convert"
    property int hoveredIndex: -1
    property real outerRadius: 200
    property real innerRadius: 88
    property color accent: "#4a9eff"
    // Text and outlines drawn on the accent: fixed dark, so they stay readable
    // on light themes too (theme background on blue is ~2.5:1 there).
    property color accentInk: "#0b0f14"
    property color background: "#1e1e2e"
    property color foreground: "#cdd6f4"
    property color dim: "#6c7086"
    property string fontFamily: ""

    signal activated(int index)

    readonly property int count: segments ? segments.length : 0
    readonly property real stepDeg: count > 0 ? 360 / count : 360
    readonly property real gapDeg: count > 1 ? 2.5 : 0
    // The ring sits in the top square; the tab bar hangs below it.
    readonly property real cx: width / 2
    readonly property real cy: width / 2
    readonly property real tabBarHeight: 64
    implicitHeight: width + tabBarHeight
    readonly property real ringMid: (outerRadius + innerRadius) / 2
    readonly property real labelSize: {
        const base = 15;
        if (count <= 8) return base;
        return Math.max(11, Math.round(base * 8 / count));
    }

    function indexAt(x, y) {
        if (count <= 0) return -1;
        const dx = x - cx;
        const dy = y - cy;
        const r = Math.sqrt(dx * dx + dy * dy);
        if (r < innerRadius || r > outerRadius + 40) return -1;
        // angle clockwise from 12 o'clock, 0..360
        let a = Math.atan2(dx, -dy) * 180 / Math.PI;
        if (a < 0) a += 360;
        // segment i is centred at i*stepDeg, so shift by half a step
        let idx = Math.floor((a + stepDeg / 2) / stepDeg);
        if (idx >= count) idx = 0;
        return idx;
    }

    function setPointer(x, y) {
        hoveredIndex = indexAt(x, y);
    }

    function step(delta) {
        if (count <= 0) return;
        if (hoveredIndex < 0) {
            hoveredIndex = 0;
            return;
        }
        hoveredIndex = ((hoveredIndex + delta) % count + count) % count;
    }

    function activate() {
        if (hoveredIndex >= 0 && hoveredIndex < count)
            activated(hoveredIndex);
    }

    // Segment ring
    Repeater {
        model: root.count

        delegate: Shape {
            id: seg
            required property int index
            readonly property bool hovered: root.hoveredIndex === index
            readonly property real startA: -90 + index * root.stepDeg - root.stepDeg / 2 + root.gapDeg / 2
            readonly property real sweepA: root.stepDeg - root.gapDeg
            readonly property real endRad: (startA + sweepA) * Math.PI / 180

            // The ring's square, so the hover scale grows about the ring centre
            // and not the centre of the whole item (which includes the tab bar).
            width: root.width
            height: root.width
            preferredRendererType: Shape.CurveRenderer
            scale: hovered ? 1.07 : 1.0
            Behavior on scale { NumberAnimation { duration: 90; easing.type: Easing.OutQuad } }

            ShapePath {
                strokeWidth: -1
                fillColor: seg.hovered ? root.accent : Qt.rgba(root.background.r, root.background.g, root.background.b, 0.88)
                Behavior on fillColor { ColorAnimation { duration: 90 } }

                PathAngleArc {
                    centerX: root.cx; centerY: root.cy
                    radiusX: root.outerRadius; radiusY: root.outerRadius
                    startAngle: seg.startA
                    sweepAngle: seg.sweepA
                }
                PathLine {
                    x: root.cx + root.innerRadius * Math.cos(seg.endRad)
                    y: root.cy + root.innerRadius * Math.sin(seg.endRad)
                }
                PathAngleArc {
                    centerX: root.cx; centerY: root.cy
                    radiusX: root.innerRadius; radiusY: root.innerRadius
                    startAngle: seg.startA + seg.sweepA
                    sweepAngle: -seg.sweepA
                }
            }
        }
    }

    // Segment labels
    Repeater {
        model: root.count

        delegate: Text {
            id: lbl
            required property int index
            readonly property bool hovered: root.hoveredIndex === index
            readonly property real ang: (-90 + index * root.stepDeg) * Math.PI / 180
            readonly property real rr: root.ringMid * (hovered ? 1.07 : 1.0)

            x: root.cx + rr * Math.cos(ang) - width / 2
            y: root.cy + rr * Math.sin(ang) - height / 2
            // Wrap long labels ("Extract audio") onto two lines rather than
            // cutting them; the width is what fits inside one segment.
            width: Math.max(40, Math.min(root.outerRadius - root.innerRadius - 16,
                                         2 * root.ringMid * Math.sin(Math.PI / Math.max(2, root.count)) - 10))
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignHCenter
            lineHeight: 0.95
            text: root.segments[index] ? (root.segments[index].label ?? root.segments[index].id ?? "") : ""
            color: hovered ? root.accentInk : root.foreground
            font.family: root.fontFamily
            font.pixelSize: root.labelSize
            font.bold: hovered
        }
    }

    // Centre disc
    Rectangle {
        width: root.innerRadius * 2 - 14
        height: width
        radius: width / 2
        x: root.cx - width / 2
        y: root.cy - height / 2
        color: Qt.rgba(root.background.r, root.background.g, root.background.b, 0.94)
        border.width: 1
        border.color: Qt.rgba(root.dim.r, root.dim.g, root.dim.b, 0.5)

        Column {
            anchors.centerIn: parent
            spacing: 4
            width: parent.width - 16

            readonly property var hovered: root.hoveredIndex >= 0 ? root.segments[root.hoveredIndex] : null

            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                text: parent.hovered ? (parent.hovered.label ?? parent.hovered.id ?? "") : root.title
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: parent.hovered ? 20 : 16
                font.bold: true
            }

            // What the hovered segment does, or how to cancel.
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                maximumLineCount: 4
                elide: Text.ElideRight
                text: parent.hovered ? (parent.hovered.description ?? "") : root.idleHint
                color: root.foreground
                opacity: 0.75
                font.family: root.fontFamily
                font.pixelSize: 12
                visible: text.length > 0
            }
        }
    }

    property string idleHint: "Drop on a segment\nDrop here to cancel"

    // --- tab bar --------------------------------------------------------------

    readonly property real tabWidth: modes && modes.length ? Math.min(140, (width - 16) / modes.length) : 0
    readonly property real tabsX: (width - tabWidth * (modes ? modes.length : 0)) / 2
    readonly property real tabsY: cy + outerRadius + 16

    // Index into modes of the tab under (x, y), or -1.
    function modeAt(x, y) {
        // One wheel draws no tab bar, so there is nothing to hit below the ring.
        if (!modes || modes.length < 2 || y < tabsY || y > tabsY + 34) return -1
        const i = Math.floor((x - tabsX) / tabWidth)
        return i >= 0 && i < modes.length ? i : -1
    }

    // Each tab is drawn 6 px narrower than its hit cell, centred in it.
    Row {
        x: root.tabsX + 3
        y: root.tabsY
        spacing: 6
        visible: root.modes && root.modes.length > 1

        Repeater {
            model: root.modes ? root.modes.length : 0
            delegate: Rectangle {
                required property int index
                readonly property var m: root.modes[index]
                readonly property bool current: m && m.id === root.currentMode
                width: root.tabWidth - 6
                height: 34
                radius: 17
                color: current ? root.accent : Qt.rgba(root.background.r, root.background.g, root.background.b, 0.94)
                border.width: 1
                border.color: current ? root.accent : Qt.rgba(root.dim.r, root.dim.g, root.dim.b, 0.6)

                Row {
                    anchors.centerIn: parent
                    spacing: 6
                    // The key that opens this wheel, as a small keycap
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: keyText.implicitWidth + 10
                        height: 18
                        radius: 4
                        color: "transparent"
                        border.width: 1
                        border.color: current ? root.accentInk : root.dim
                        Text {
                            id: keyText
                            anchors.centerIn: parent
                            text: m ? m.key : ""
                            color: current ? root.accentInk : root.foreground
                            font.family: root.fontFamily
                            font.pixelSize: 11
                        }
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: m ? m.label : ""
                        color: current ? root.accentInk : root.foreground
                        font.family: root.fontFamily
                        font.pixelSize: 13
                        font.bold: current
                    }
                }
            }
        }
    }

    Text {
        x: 0
        width: root.width
        y: root.tabsY + 40
        horizontalAlignment: Text.AlignHCenter
        visible: root.modes && root.modes.length > 1
        text: "Tap the key or hover a tab to switch"
        color: root.foreground
        opacity: 0.7
        font.family: root.fontFamily
        font.pixelSize: 12
    }
}
