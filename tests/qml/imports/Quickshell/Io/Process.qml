import QtQml
QtObject {
  property var command: []
  property bool running: false
  property QtObject stdout: null
  property bool killed: false
  signal exited(int exitCode)
  function signal(number) { killed = true; running = false }
}
