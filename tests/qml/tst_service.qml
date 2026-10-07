import QtQuick
import QtTest
import "../.." as Plugin

TestCase {
  name: "OmaFansService"
  Component { id: factory; Plugin.Service {} }
  property var service: null
  function init() { service = createTemporaryObject(factory, this) }
  function test_success_status() {
    service.applyStatus(JSON.stringify({ available: true, service: true,
      control_enabled: true, mode: "manual", rpm: 2400, percent: 43,
      temperature: 55, manual_percent: 30 }), 0)
    compare(service.available, true)
    compare(service.controlEnabled, true)
    compare(service.rpm, 2400)
    compare(service.manualPercent, 30)
    compare(service.mode, "manual")
  }
  function test_bad_response_clears_stale_control() {
    service.controlEnabled = true
    service.rpm = 2000
    service.applyStatus("not json", 1)
    compare(service.controlEnabled, false)
    compare(service.rpm, null)
    verify(service.error.length > 0)
  }
  function test_sensor_recovery_reenables_controls_and_clears_old_error() {
    service.applyStatus(JSON.stringify({ available: true, service: true,
      control_enabled: false, mode: "auto", temperature: 63,
      error: "Temperature sensor unavailable" }), 1)
    compare(service.controlEnabled, false)
    verify(service.error.length > 0)
    service.applyStatus(JSON.stringify({ available: true, service: true,
      control_enabled: true, mode: "auto", temperature: 64, error: "" }), 0)
    compare(service.controlEnabled, true)
    compare(service.temperature, 64)
    compare(service.mode, "auto")
    compare(service.error, "")
  }
  function test_array_response_rejected() {
    service.applyStatus("[]", 0)
    compare(service.serviceUp, false)
    verify(service.error.length > 0)
  }
  function test_offline_monitoring() {
    service.applyStatus(JSON.stringify({ available: true, service: false,
      control_enabled: false, rpm: 2000, notice: "monitoring only" }), 0)
    compare(service.available, true)
    compare(service.controlEnabled, false)
    compare(service.notice, "monitoring only")
  }
  function test_nonzero_exit_is_visible() {
    service.applyStatus("{}", 1)
    compare(service.error, "OmaFans request failed")
  }
  function test_polling_and_setting_cannot_overlap() {
    service.refresh()
    compare(service.busy, true)
    compare(service.setControl({ mode: "manual" }), false)
  }
  function test_timeout_does_not_accept_late_success() {
    service.timedOut = true
    service.unavailable("timed out")
    service.applyStatus('{"control_enabled":true,"service":true}', 0)
    compare(service.controlEnabled, false)
    compare(service.error, "timed out")
  }
  function test_error_text_bounded() {
    service.applyStatus(JSON.stringify({error:"x".repeat(1000)}), 1)
    compare(service.error.length, 250)
  }
}
