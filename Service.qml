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
  property string helperError: ""
  property string autoError: ""
  readonly property string error: autoError || helperError
  property string notice: ""
  property var cpuTemperature: null
  readonly property bool busy: activeVerb !== ""
  readonly property string helperPath: decodeURIComponent(Qt.resolvedUrl("omafans.py").toString().replace(/^file:\/\//, ""))
  readonly property var pythonCommand: ["/usr/bin/python3", "-I", "-S", helperPath]
  property string pendingPayload: ""
  property bool pendingAuto: false
  property string activeVerb: ""
  property bool activeAuto: false
  property bool autoAwaitingConfirmation: false
  readonly property bool controlPending: pendingPayload !== ""
  property bool timedOut: false

  function unavailable(message) {
    available = false
    serviceUp = false
    controlEnabled = false
    rpm = null
    percent = null
    temperature = null
    cpuTemperature = null
    helperError = message
  }

  function startHelper(args) {
    timedOut = false
    activeVerb = args.length > 0 ? args[0] : ""
    var command = []
    for (var i = 0; i < pythonCommand.length; i++) command.push(pythonCommand[i])
    for (var j = 0; j < args.length; j++) command.push(args[j])
    helper.command = command
    helper.running = true
  }

  function refresh() {
    if (busy) return
    startHelper([autoAwaitingConfirmation ? "status" : "heartbeat"])
  }

  function startSet(data, auto) {
    activeAuto = auto
    startHelper(["set", data])
  }

  function setControl(payload) {
    var data = JSON.stringify(payload)
    if (!data || data.length > 2048) return false
    var auto = !!payload && payload.mode === "auto"
    if (auto) {
      autoAwaitingConfirmation = true
    } else if (autoAwaitingConfirmation) {
      return false
    }
    if (busy) {
      pendingPayload = data
      pendingAuto = auto
    } else {
      startSet(data, auto)
    }
    return true
  }

  function autoConfirmed(parsed, exitCode) {
    if (!parsed || exitCode !== 0 || parsed.ok !== true || parsed.service !== true
        || parsed.control_enabled !== true || parsed.mode !== "auto") return false
    if (parsed.firmware_auto !== undefined) return parsed.firmware_auto === true
    // Older daemons signal verified firmware Auto in a successful Auto set
    // reply with no fan duty, fallback notice or overheat error.
    return activeAuto && parsed.percent === null && parsed.notice === "" && parsed.error === ""
  }

  function completeHelper(raw, exitCode) {
    if (!busy) return
    // The QtTest process stub can be completed without first clearing running.
    if (helper.running) helper.running = false
    var parsed = applyStatus(raw, exitCode)
    if (autoAwaitingConfirmation && (activeAuto || activeVerb === "status")) {
      if (autoConfirmed(parsed, exitCode)) {
        autoAwaitingConfirmation = false
        autoError = ""
        notice = notice || "Firmware Auto confirmed"
        pendingPayload = ""
        pendingAuto = false
      } else if (activeAuto && !timedOut) {
        var detail = helperError || notice
        autoError = "Firmware Auto unconfirmed" + (detail ? ": " + detail.slice(0, 223) : "")
      }
    }
    activeVerb = ""
    activeAuto = false
    if (pendingPayload !== "") {
      var queued = pendingPayload
      var queuedAuto = pendingAuto
      pendingPayload = ""
      pendingAuto = false
      startSet(queued, queuedAuto)
    }
  }

  function timeoutHelper() {
    if (!busy || timedOut) return
    timedOut = true
    if (!pendingAuto) pendingPayload = ""
    unavailable("OmaFans helper timed out")
    if (activeAuto) autoError = "Firmware Auto unconfirmed: helper timed out"
    if (helper.running) helper.signal(9)
    else completeHelper("", 1)
  }

  function applyStatus(raw, exitCode) {
    if (timedOut) return null
    var parsed = null
    try { parsed = JSON.parse(String(raw)) } catch (e) { parsed = null }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      unavailable("OmaFans helper returned invalid status")
      return null
    }
    available = parsed.available === true
    serviceUp = parsed.service === true
    controlEnabled = parsed.control_enabled === true
    mode = ["auto", "manual", "curve"].indexOf(parsed.mode) >= 0 ? parsed.mode : "auto"
    rpm = typeof parsed.rpm === "number" && isFinite(parsed.rpm) ? parsed.rpm : null
    percent = typeof parsed.percent === "number" && isFinite(parsed.percent) ? parsed.percent : null
    temperature = typeof parsed.temperature === "number" && isFinite(parsed.temperature) ? parsed.temperature : null
    cpuTemperature = typeof parsed.cpu_temperature === "number" && isFinite(parsed.cpu_temperature) ? parsed.cpu_temperature : null
    if (typeof parsed.manual_percent === "number" && isFinite(parsed.manual_percent))
      manualPercent = Math.max(30, Math.min(100, Math.round(parsed.manual_percent)))
    if (Array.isArray(parsed.curve) && parsed.curve.length === 5) curve = parsed.curve
    helperError = typeof parsed.error === "string" ? parsed.error.slice(0, 250) : ""
    if (exitCode !== 0 && helperError === "") helperError = "OmaFans request failed"
    notice = typeof parsed.notice === "string" ? parsed.notice.slice(0, 250) : ""
    return parsed
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
    running: root.busy
    onTriggered: root.timeoutHelper()
  }
  Process {
    id: helper
    stdout: StdioCollector { id: output; waitForEnd: true }
    onExited: function(exitCode) { root.completeHelper(output.text, exitCode) }
  }
  IpcHandler {
    target: "community.omafans.service"
    function status(): string {
      return JSON.stringify({ available: root.available, service: root.serviceUp,
        control_enabled: root.controlEnabled, mode: root.mode, rpm: root.rpm,
        percent: root.percent, temperature: root.temperature,
        cpu_temperature: root.cpuTemperature,
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
