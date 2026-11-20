import QtQuick
import QtTest
import "../.." as Plugin

TestCase {
  name: "OmaFansAutoRecovery"
  Component { id: factory; Plugin.Service {} }
  property var service: null

  function init() { service = createTemporaryObject(factory, this) }

  function status(overrides) {
    var reply = { ok: true, available: true, service: true, control_enabled: true,
      mode: "auto", firmware_auto: true, percent: null, notice: "", error: "" }
    for (var key in overrides) reply[key] = overrides[key]
    return JSON.stringify(reply)
  }

  function test_queued_auto_takes_priority_and_survives_timer() {
    service.refresh()
    compare(service.activeVerb, "heartbeat")
    verify(service.setControl({ mode: "curve" }))
    verify(service.setControl({ mode: "auto" }))
    compare(service.pendingPayload, '{"mode":"auto"}')
    compare(service.setControl({ mode: "manual", manual_percent: 50 }), false)
    compare(service.setControl({ manual_percent: 55 }), false)

    tryCompare(service, "timedOut", true, 6500)
    verify(service.controlPending)
    verify(service.autoAwaitingConfirmation)
    service.refresh()
    compare(service.activeVerb, "heartbeat") // The cancelled process has yet to exit.
    service.completeHelper(status({}), 0)
    compare(service.activeVerb, "set")
    verify(service.activeAuto)
    verify(service.autoAwaitingConfirmation)
    compare(service.controlPending, false)

    service.completeHelper(status({}), 0)
    compare(service.autoAwaitingConfirmation, false)
    compare(service.error, "")
    compare(service.notice, "Firmware Auto confirmed")
    service.refresh()
    compare(service.activeVerb, "heartbeat")
  }

  function test_timed_out_auto_ignores_late_reply_and_polls_without_renewal() {
    verify(service.setControl({ mode: "auto" }))
    service.timeoutHelper()
    service.completeHelper(status({}), 0)
    compare(service.error, "Firmware Auto unconfirmed: helper timed out")
    service.refresh()
    compare(service.activeVerb, "status")
    service.completeHelper(status({ mode: "manual", firmware_auto: false, percent: 58 }), 0)
    compare(service.error, "Firmware Auto unconfirmed: helper timed out")
    verify(service.autoAwaitingConfirmation)
    service.refresh()
    compare(service.activeVerb, "status")
    service.completeHelper(status({}), 0)
    compare(service.autoAwaitingConfirmation, false)
    compare(service.error, "")
    service.refresh()
    compare(service.activeVerb, "heartbeat")
  }

  function test_failed_auto_blocks_renewal_and_allows_an_explicit_retry() {
    verify(service.setControl({ mode: "auto" }))
    service.completeHelper(status({ ok: false, control_enabled: false,
      error: "watchdog disarm failed" }), 1)
    compare(service.error, "Firmware Auto unconfirmed: watchdog disarm failed")
    service.refresh()
    compare(service.activeVerb, "status")
    verify(service.setControl({ mode: "auto" }))
    service.completeHelper(status({ firmware_auto: false, percent: 100 }), 0)
    compare(service.activeVerb, "set")
    service.completeHelper(status({}), 0)
    compare(service.autoAwaitingConfirmation, false)
    compare(service.error, "")
    verify(service.setControl({ mode: "curve" }))
  }

  function test_successful_emergency_speed_fallback_is_not_firmware_auto() {
    verify(service.setControl({ mode: "auto" }))
    service.completeHelper(status({ firmware_auto: false, percent: 100,
      notice: "highest normal speed confirmed" }), 0)
    verify(service.autoAwaitingConfirmation)
    compare(service.error, "Firmware Auto unconfirmed: highest normal speed confirmed")
    service.refresh()
    compare(service.activeVerb, "status")
  }

  function test_legacy_daemon_confirms_auto_through_the_set_reply() {
    var legacy = status({ firmware_auto: undefined })
    verify(service.setControl({ mode: "auto" }))
    service.completeHelper("{}", 1)
    service.refresh()
    compare(service.activeVerb, "status")
    service.completeHelper(legacy, 0)
    verify(service.autoAwaitingConfirmation)
    verify(service.setControl({ mode: "auto" }))
    service.completeHelper(legacy, 0)
    compare(service.autoAwaitingConfirmation, false)
    compare(service.notice, "Firmware Auto confirmed")
  }
}
