# Preview provenance

The root `preview.png` shows the real hosted `Panel.qml` on Omarchy 4.0.4-1,
with the deterministic fictional values in `status.json`. It is a screenshot,
not a generated mockup, and is not evidence of hardware control.

To reproduce it on a test desktop:

1. Use a disposable Omarchy session, or back up `shell.json` and ensure that
   no existing `community.omafans` plugin would be replaced.
2. Copy the root manifest, QML files and Python files into a temporary plugin
   folder named `community.omafans` under the user's Omarchy plugins directory.
3. In that temporary copy only, replace `fanctl.py` with a script that prints
   the exact JSON in `demo/status.json`. This helper performs no hardware or
   network operations. Do not install or start the privileged daemon.
4. Rescan, enable `community.omafans`, and verify
   `omarchy-shell community.omafans.service status` returns the fixture values.
5. Open the popup in an empty workspace and use `grim -g` with the popup's
   coordinates to capture only the panel. Inspect the image for other desktop
   content or identifying information before replacing the preview.
6. Close and disable the temporary plugin, restore the saved shell config,
   remove the temporary copy, rescan, and restore the workspace and cursor.
   Keep the backup if any restoration step cannot be verified.

The original widget and system controller remain independent of this fixture.
The committed runtime never selects demo data through an environment variable,
request field or privileged command.
