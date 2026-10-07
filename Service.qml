import QtQuick
import Quickshell.Io

Item {
  id: root
  property var shell: null
  property var manifest: null
  property string omarchyPath: ""
  property bool available: false
  property bool serviceUp: false
  property bool controlEnabled: false
  property string mode: "auto"
  property var rpm: null
  property var percent: null
  property var temperature: null
  property int manualPercent: 60
  property var curve: [[40, 30], [55, 40], [65, 60], [75, 80], [85, 100]]
  property string error: ""
  property string notice: ""
  readonly property bool busy: helper.running
  readonly property string helperPath: decodeURIComponent(Qt.resolvedUrl("fanctl.py").toString().replace(/^file:\/\//, ""))
  property bool timedOut: false

  function unavailable(message) {
    available = false
    serviceUp = false
    controlEnabled = false
    rpm = null
    percent = null
    temperature = null
    error = message
  }

  function refresh() {
    if (helper.running) return
    timedOut = false
    helper.command = ["/usr/bin/python3", helperPath, "heartbeat"]
    helper.running = true
  }

  function setControl(payload) {
    if (helper.running) return false
    var data = JSON.stringify(payload)
    if (!data || data.length > 2048) return false
    timedOut = false
    helper.command = ["/usr/bin/python3", helperPath, "set", data]
    helper.running = true
    return true
  }

  function applyStatus(raw, exitCode) {
    if (timedOut) return
    var parsed = null
    try { parsed = JSON.parse(String(raw)) } catch (e) { parsed = null }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      unavailable("OmaFans helper returned invalid status")
      return
    }
    available = parsed.available === true
    serviceUp = parsed.service === true
    controlEnabled = parsed.control_enabled === true
    mode = ["auto", "manual", "curve"].indexOf(parsed.mode) >= 0 ? parsed.mode : "auto"
    rpm = typeof parsed.rpm === "number" && isFinite(parsed.rpm) ? parsed.rpm : null
    percent = typeof parsed.percent === "number" && isFinite(parsed.percent) ? parsed.percent : null
    temperature = typeof parsed.temperature === "number" && isFinite(parsed.temperature) ? parsed.temperature : null
    if (typeof parsed.manual_percent === "number" && isFinite(parsed.manual_percent))
      manualPercent = Math.max(30, Math.min(100, Math.round(parsed.manual_percent)))
    if (Array.isArray(parsed.curve) && parsed.curve.length === 5) curve = parsed.curve
    error = typeof parsed.error === "string" ? parsed.error.slice(0, 250) : ""
    if (exitCode !== 0 && error === "") error = "OmaFans request failed"
    notice = typeof parsed.notice === "string" ? parsed.notice.slice(0, 250) : ""
  }

  Timer {
    interval: 3000
    repeat: true
    running: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }
  Timer {
    interval: 5000
    running: helper.running
    onTriggered: {
      root.timedOut = true
      helper.signal(9)
      root.unavailable("OmaFans helper timed out")
    }
  }
  Process {
    id: helper
    stdout: StdioCollector { id: output; waitForEnd: true }
    onExited: function(exitCode) { root.applyStatus(output.text, exitCode) }
  }
  IpcHandler {
    target: "community.omafans.service"
    function status(): string {
      return JSON.stringify({ available: root.available, service: root.serviceUp,
        control_enabled: root.controlEnabled, mode: root.mode, rpm: root.rpm,
        percent: root.percent, temperature: root.temperature,
        manual_percent: root.manualPercent, curve: root.curve,
        error: root.error, notice: root.notice })
    }
    function refresh(): void { root.refresh() }
    function set(payload: string): string {
      if (payload.length > 2048) return "rejected"
      try { return root.setControl(JSON.parse(payload)) ? "queued" : "rejected" }
      catch (e) { return "rejected" }
    }
  }
}
