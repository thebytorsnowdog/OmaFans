import QtQuick
import QtQuick.Controls
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "community.omafans"
  ipcTarget: "community.omafans"
  manageIpc: false

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  property var service: null
  function resolveService() {
    if (bar && bar.shell && typeof bar.shell.serviceFor === "function") {
      var found = bar.shell.serviceFor(moduleName)
      if (found !== service) service = found
    }
  }
  onBarChanged: resolveService()
  Timer {
    interval: 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.resolveService()
  }
  readonly property bool available: service ? service.available : false
  readonly property bool serviceUp: service ? service.serviceUp : false
  readonly property bool controlEnabled: service ? service.controlEnabled : false
  readonly property string mode: service ? service.mode : "auto"
  readonly property var rpm: service ? service.rpm : null
  readonly property var percent: service ? service.percent : null
  readonly property var temperature: service ? service.temperature : null
  readonly property string statusError: service ? service.error : ""
  readonly property string notice: service ? service.notice : ""
  readonly property bool busy: service ? service.busy : false
  readonly property bool canControl: controlEnabled && !busy
  readonly property bool autoUsable: serviceUp

  property int manualDraft: 60
  property bool manualDraftTouched: false
  property var curveDraft: [[40, 30], [55, 40], [65, 60], [75, 80], [85, 100]]
  property bool curveDraftTouched: false

  property string focusSection: "mode"
  property int selectedIndex: 0
  property bool cursorActive: false

  readonly property var visibleSections: ["mode", "manual", "curve"]

  function sectionFirstIndex(section) {
    return section === "manual" ? -1 : 0
  }

  function sectionCount(section) {
    if (section === "mode") return 3
    if (section === "manual") return 0
    if (section === "curve") return 5
    return 0
  }

  function sectionIsSingleRow(section) {
    return section === "manual"
  }

  function moveCursor(dx, dy) {
    var sections = visibleSections
    if (!sections || sections.length === 0) return
    var sIdx = sections.indexOf(focusSection)
    if (sIdx < 0) {
      focusSection = sections[0]
      selectedIndex = sectionFirstIndex(focusSection)
      return
    }
    if (dy !== 0) {
      var inSingleRow = sectionIsSingleRow(focusSection)
      var max = inSingleRow ? 0 : sectionCount(focusSection) - 1
      if (dy > 0) {
        if (!inSingleRow && selectedIndex < max) { selectedIndex = selectedIndex + 1; return }
        if (sIdx < sections.length - 1) {
          focusSection = sections[sIdx + 1]
          selectedIndex = sectionFirstIndex(focusSection)
        }
      } else {
        if (!inSingleRow && selectedIndex > 0) { selectedIndex = selectedIndex - 1; return }
        if (sIdx > 0) {
          var prev = sections[sIdx - 1]
          focusSection = prev
          selectedIndex = sectionIsSingleRow(prev) ? sectionFirstIndex(prev) : sectionCount(prev) - 1
        }
      }
      return
    }
    if (dx !== 0) {
      if (focusSection === "mode") {
        var next = Math.max(0, Math.min(2, selectedIndex + dx))
        selectedIndex = next
      } else if (focusSection === "manual") {
        if (canControl) {
          manualDraftTouched = true
          manualDraft = Math.max(30, Math.min(100, manualDraft + dx * 5))
          applyManual(manualDraft)
        }
      } else if (focusSection === "curve") {
        selectedIndex = Math.max(0, Math.min(4, selectedIndex + dx))
      }
    }
  }

  function activateCursor() {
    if (focusSection === "mode") {
      if (selectedIndex === 0) setMode("auto")
      else if (selectedIndex === 1) setMode("manual")
      else if (selectedIndex === 2) setMode("curve")
    } else if (focusSection === "curve" && canControl) {
      applyCurve()
    }
  }

  function anyFieldFocused() {
    for (var i = 0; i < root.curveFieldRefs.length; i++) {
      var pair = root.curveFieldRefs[i]
      if (pair && pair.temp && pair.temp.field && pair.temp.field.activeFocus) return true
      if (pair && pair.pct && pair.pct.field && pair.pct.field.activeFocus) return true
    }
    return false
  }

  property var curveFieldRefs: []

  function registerCurveField(index, temp, pct) {
    var next = root.curveFieldRefs.slice()
    next[index] = { temp: temp, pct: pct }
    root.curveFieldRefs = next
  }

  Component.onCompleted: seedDrafts()

  function seedDrafts() {
    if (!service) return
    if (!manualDraftTouched) manualDraft = service.manualPercent
    if (!curveDraftTouched) curveDraft = service.curve
  }

  Connections {
    target: service
    function onManualPercentChanged() {
      if (root.manualDraftTouched) return
      if (root.mode !== "manual") return
      root.manualDraft = root.service ? root.service.manualPercent : root.manualDraft
    }
    function onCurveChanged() {
      if (root.curveDraftTouched) return
      if (root.mode !== "curve") return
      if (root.service) root.curveDraft = root.service.curve
    }
  }

  function setMode(next) {
    if (!service) return
    if (next === "auto") {
      if (!autoUsable) return
      service.setControl({ mode: "auto" })
    } else if (next === "manual") {
      if (!canControl) return
      manualDraftTouched = false
      service.setControl({ mode: "manual", manual_percent: manualDraft })
    } else if (next === "curve") {
      if (!canControl) return
      curveDraftTouched = false
      service.setControl({ mode: "curve", curve: curveDraft })
    }
  }

  function applyManual(percent) {
    if (!canControl) return
    manualDraft = Math.round(Math.max(30, Math.min(100, percent)))
    service.setControl({ mode: "manual", manual_percent: manualDraft })
  }

  function curveRows() {
    var rows = []
    for (var i = 0; i < 5; i++) {
      var pair = curveDraft && curveDraft.length > i && Array.isArray(curveDraft[i]) ? curveDraft[i] : [40 + i * 11, 30 + i * 17]
      var temp = Math.round(Number(pair && pair.length > 0 ? pair[0] : 40) || 40)
      var pct = Math.round(Number(pair && pair.length > 1 ? pair[1] : 30) || 30)
      rows.push([Math.max(30, Math.min(85, temp)), Math.max(30, Math.min(100, pct))])
    }
    return rows
  }

  function applyCurve() {
    if (!canControl) return
    service.setControl({ mode: "curve", curve: curveDraft })
    curveDraftTouched = false
  }

  function curvePercentAt(curve, temp) {
    var c = Array.isArray(curve) && curve.length > 0 ? curve : root.curveDraft
    var rows = []
    for (var i = 0; i < c.length; i++) {
      if (Array.isArray(c[i]) && c[i].length >= 2) rows.push(c[i])
    }
    if (rows.length === 0) return 0
    var target = Number(rows[0][1])
    for (var j = 0; j < rows.length; j++) {
      if (temp >= Number(rows[j][0])) target = Number(rows[j][1])
    }
    return Math.max(30, Math.min(100, Math.round(target)))
  }

  function curveSummary() {
    var c = Array.isArray(root.curveDraft) ? root.curveDraft : []
    var parts = []
    for (var i = 0; i < c.length; i++) {
      if (Array.isArray(c[i]) && c[i].length >= 2) {
        parts.push(Math.round(c[i][0]) + "°C " + Math.round(c[i][1]) + "%")
      }
    }
    return parts.join("  ·  ")
  }

  function rpmText() {
    return rpm === null || rpm === undefined ? "—" : Math.round(Number(rpm)) + " RPM"
  }

  function tempText() {
    return temperature === null || temperature === undefined ? "—" : Math.round(Number(temperature)) + "°C"
  }

  function barLabel() {
    if (!serviceUp && !available) return "Fan —"
    if (mode === "manual" && percent !== null && percent !== undefined) return "Fan " + Math.round(Number(percent)) + "%"
    if (mode === "curve" && percent !== null && percent !== undefined) return "Fan " + Math.round(Number(percent)) + "%"
    return "Fan Auto"
  }

  function barTooltip() {
    var lines = [ "OmaFans · " + mode.toUpperCase() ]
    lines.push(rpmText() + " · " + tempText())
    if (percent !== null && percent !== undefined) lines.push(Math.round(Number(percent)) + "% duty")
    if (statusError !== "") lines.push(statusError)
    else if (notice !== "") lines.push(notice)
    return lines.join("\n")
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onOpenedChanged: if (opened) {
    cursorActive = false
    focusSection = "mode"
    selectedIndex = 0
    seedDrafts()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function status(): string {
      return JSON.stringify({
        available: root.available,
        service: root.serviceUp,
        control_enabled: root.controlEnabled,
        mode: root.mode,
        rpm: root.rpm,
        percent: root.percent,
        temperature: root.temperature,
        manual_percent: root.service ? root.service.manualPercent : 60,
        curve: root.service ? root.service.curve : [],
        error: root.statusError,
        notice: root.notice
      })
    }
    function set(payload: string): string {
      if (!root.service) return "no-service"
      if (payload.length > 2048) return "rejected"
      try { return root.service.setControl(JSON.parse(payload)) ? "queued" : "rejected" }
      catch (e) { return "rejected" }
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.bar && root.bar.vertical ? "󰈐" : root.barLabel()
    dimmed: !root.serviceUp && !root.available
    active: root.mode !== "auto"
    tooltipText: root.barTooltip()
    onPressed: function(b) { root.toggle() }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(420))
    contentHeight: panel.fittedContentHeight(panelColumn.implicitHeight, Style.space(560))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: anyFieldFocused()
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onMoveRequested: function(dx, dy) {
        if (!root.cursorActive) { root.cursorActive = true; return }
        root.moveCursor(dx, dy)
      }
      onActivateRequested: if (root.cursorActive) root.activateCursor()
      onTextKey: function(t) {
        if (t === "a" || t === "A") root.setMode("auto")
        else if (t === "m" || t === "M") root.setMode("manual")
        else if (t === "c" || t === "C") root.setMode("curve")
      }

      ScrollView {
        id: scrollArea
        anchors.fill: parent
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: panelColumn.implicitHeight > height ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
        Binding {
          target: scrollArea.contentItem
          property: "interactive"
          value: panelColumn.implicitHeight > scrollArea.height
        }

        Column {
          id: panelColumn
          width: scrollArea.availableWidth
          spacing: Style.space(14)

          Item {
            width: parent.width
            implicitHeight: Math.max(heroIcon.implicitHeight, heroLabels.implicitHeight)

            Text {
              id: heroIcon
              textFormat: Text.PlainText
              text: "󰈐"
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.display
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }

            Column {
              id: heroLabels
              anchors.left: heroIcon.right
              anchors.leftMargin: Style.space(14)
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Text {
                text: "OmaFans"
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
                elide: Text.ElideRight
                width: parent.width
              }

              Text {
                textFormat: Text.PlainText
                text: {
                  if (!root.serviceUp) return "HELPER UNAVAILABLE"
                  if (!root.available) return "NO FAN CONTROL"
                  return root.rpmText() + " · " + root.tempText()
                }
                color: Qt.darker(root.bar.foreground, 1.4)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                font.letterSpacing: 1.2
                elide: Text.ElideRight
                width: parent.width
              }
            }
          }

          Text {
            visible: root.statusError !== ""
            width: parent.width
            textFormat: Text.PlainText
            text: root.statusError
            color: root.urgent
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
          }

          Text {
            visible: root.statusError === "" && root.notice !== ""
            width: parent.width
            textFormat: Text.PlainText
            text: root.notice
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
          }

          Text {
            visible: root.serviceUp && !root.controlEnabled
            width: parent.width
            textFormat: Text.PlainText
            text: "Fan control is unavailable. See the OmaFans setup instructions."
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
          }

          PanelSeparator { foreground: root.bar.foreground }

          Column {
            width: parent.width
            spacing: Style.space(10)

            PanelSectionHeader {
              text: "MODE"
              foreground: root.bar.foreground
              fontFamily: root.fontFamily
            }

            Row {
              width: parent.width
              spacing: Style.spacing.sm

              Button {
                text: "Auto"
                fontSize: Style.font.caption
                foreground: root.bar.foreground
                fontFamily: root.fontFamily
                bordered: true
                active: root.mode === "auto"
                enabled: root.autoUsable
                width: (parent.width - parent.spacing * 2) / 3
                onClicked: root.setMode("auto")
              }

              Button {
                text: "Manual"
                fontSize: Style.font.caption
                foreground: root.bar.foreground
                fontFamily: root.fontFamily
                bordered: true
                active: root.mode === "manual"
                enabled: root.canControl
                width: (parent.width - parent.spacing * 2) / 3
                onClicked: root.setMode("manual")
              }

              Button {
                text: "Curve"
                fontSize: Style.font.caption
                foreground: root.bar.foreground
                fontFamily: root.fontFamily
                bordered: true
                active: root.mode === "curve"
                enabled: root.canControl
                width: (parent.width - parent.spacing * 2) / 3
                onClicked: root.setMode("curve")
              }
            }
          }

          Column {
            visible: root.serviceUp
            width: parent.width
            spacing: Style.space(6)

            Item {
              width: parent.width
              implicitHeight: Math.max(manualHeader.implicitHeight, manualPercent.implicitHeight)

              PanelSectionHeader {
                id: manualHeader
                text: "MANUAL DUTY"
                foreground: root.bar.foreground
                fontFamily: root.fontFamily
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
              }

              Text {
                id: manualPercent
                textFormat: Text.PlainText
                text: Math.round(manualSlider.dragging ? manualSlider.liveValue : root.manualDraft) + "%"
                color: Qt.darker(root.bar.foreground, 1.4)
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                anchors.right: parent.right
                anchors.rightMargin: Style.space(6)
                anchors.verticalCenter: parent.verticalCenter
              }
            }

            CursorSurface {
              width: parent.width
              height: manualSlider.implicitHeight + Style.spacing.controlGap
              hasCursor: root.cursorActive && root.focusSection === "manual" && root.selectedIndex === -1
              foreground: root.bar.foreground
              outline: true

              PanelSlider {
                id: manualSlider
                bar: root.bar
                anchors.fill: parent
                anchors.leftMargin: Style.space(6)
                anchors.rightMargin: Style.space(6)
                minimum: 30
                maximum: 100
                step: 1
                integer: true
                value: root.manualDraft
                enabled: root.canControl
                opacity: root.canControl ? 1.0 : 0.45
                onMoved: function(v) {
                  root.manualDraft = Math.round(v)
                  root.manualDraftTouched = true
                }
                onReleased: function(v) { root.applyManual(v) }
              }
            }
          }

          Column {
            visible: root.serviceUp
            width: parent.width
            spacing: Style.space(8)

            Item {
              width: parent.width
              implicitHeight: Math.max(curveHeader.implicitHeight, curveSummaryText.implicitHeight)

              PanelSectionHeader {
                id: curveHeader
                text: "TEMPERATURE CURVE"
                foreground: root.bar.foreground
                fontFamily: root.fontFamily
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
              }

              Text {
                id: curveSummaryText
                visible: root.canControl
                textFormat: Text.PlainText
                text: root.curveSummary()
                color: Qt.darker(root.bar.foreground, 1.4)
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                elide: Text.ElideRight
                width: Math.min(implicitWidth, parent.width * 0.55)
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
              }
            }

            Text {
              width: parent.width
              textFormat: Text.PlainText
              visible: root.temperature !== null && root.temperature !== undefined && root.canControl
              text: "At " + Math.round(root.temperature) + "°C this curve requests " +
                    root.curvePercentAt(root.curveDraft, root.temperature) + "%"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              wrapMode: Text.WordWrap
            }

            Repeater {
              model: 5

              CurveRow {
                width: panelColumn.width
                rowIndex: index
              }
            }

            Text {
              width: parent.width
              textFormat: Text.PlainText
              visible: root.canControl
              text: root.curveDraftTouched
                ? "Edited — press Apply curve to use it"
                : "Set fan speed for each temperature; drag the sliders"
              color: root.curveDraftTouched ? root.urgent : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              wrapMode: Text.WordWrap
            }

            Button {
              text: "Apply curve"
              fontSize: Style.font.caption
              foreground: root.bar.foreground
              fontFamily: root.fontFamily
              bordered: true
              enabled: root.canControl
              width: parent.width
              onClicked: root.applyCurve()
            }
          }

          Item {
            width: parent.width
            height: Style.space(4)
          }
        }
      }
    }
  }

  component CurveRow: Item {
    id: curveRow
    property int rowIndex: 0
    readonly property var row: root.curveRows()[rowIndex]

    width: parent ? parent.width : 0
    implicitHeight: Math.max(tempField.implicitHeight, pctSlider.implicitHeight)

    NumberField {
      id: tempField
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      label: ""
      from: 30
      to: 85
      value: curveRow.row[0]
      foreground: root.bar.foreground
      accent: Color.accent
      fontFamily: root.fontFamily
      fieldWidth: Style.space(58)
      enabled: root.canControl
      opacity: root.canControl ? 1.0 : 0.45
      onModified: function(v) {
        root.curveDraftTouched = true
        var rows = root.curveRows()
        rows[curveRow.rowIndex][0] = v
        root.curveDraft = rows
      }
    }

    Text {
      id: tempUnit
      textFormat: Text.PlainText
      text: "°C"
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      anchors.left: tempField.right
      anchors.leftMargin: Style.space(6)
      anchors.verticalCenter: tempField.verticalCenter
    }

    PanelSlider {
      id: pctSlider
      bar: root.bar
      minimum: 30
      maximum: 100
      step: 1
      integer: true
      value: curveRow.row[1]
      enabled: root.canControl
      opacity: root.canControl ? 1.0 : 0.45
      anchors.left: tempUnit.right
      anchors.leftMargin: Style.space(10)
      anchors.right: pctText.left
      anchors.rightMargin: Style.space(10)
      anchors.verticalCenter: parent.verticalCenter
      onMoved: function(v) {
        root.curveDraftTouched = true
        var rows = root.curveRows()
        rows[curveRow.rowIndex][1] = Math.round(v)
        root.curveDraft = rows
      }
    }

    Text {
      id: pctText
      textFormat: Text.PlainText
      text: (pctSlider.dragging ? pctSlider.liveValue : curveRow.row[1]) + "%"
      color: root.bar.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
      width: Style.space(36)
      horizontalAlignment: Text.AlignRight
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
    }

    Component.onCompleted: root.registerCurveField(rowIndex, tempField, null)
  }
}
