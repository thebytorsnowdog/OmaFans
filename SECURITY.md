# Security

OmaFans 0.1.x is experimental. Report a vulnerability using **Security → Report
a vulnerability** in this repository. Please do not publish exploit details or
personal hardware diagnostics in an ordinary issue. If private reporting is
unavailable, open an issue requesting a private reporting channel without
including sensitive details. There is no guaranteed response SLA.

## Trust boundaries

The QML plugin runs inside the user's Omarchy shell. That environment and the
selected desktop account are trusted to request fan control. Only the separately
installed, root-owned daemon writes hardware. systemd starts its standalone
Python file with `-I`; it imports only the standard library and cannot read
home directories under the supplied service sandbox.

IPC uses a local Unix socket with mode 0600, owned by the configured desktop
account inside a root-owned directory that prevents socket replacement. The
daemon additionally checks the kernel's `SO_PEERCRED` UID before reading data,
even if that trusted account changes its socket permissions.
The client checks that the server's peer UID is root. There is no network
protocol and no request can supply a command, pathname, UID or executable.

Messages have a 4096-byte limit, an eight-level nesting limit and a total
250-millisecond receive deadline. Only `status`, `heartbeat` and `set` exist.
Settings have strict types, ranges and curve ordering; duplicate JSON keys and
non-finite numbers are rejected. The control loop checks hardware on its own
schedule, independently of request traffic. A fault latches control off and
stops repetitive fallback writes so the kernel watchdog can expire.

The daemon does not read control state from user-writable files. Its private
root-owned configuration is checked for ownership, file type, mode, hardlinks,
size and final-component symlinks. The parent directory is protected by the
installer. Privileged setup uses fixed destination paths, protected ancestor
directories, atomic replacement, and fixed `systemctl` argument arrays.

## Scope and residual risks

- The authorized desktop account can intentionally control its own fan. This
  is not a defense against a malicious authorized user or root.
- Linux/firmware watchdog behavior and cooling vary by ThinkPad model. A sensor
  value does not prove adequate cooling, and only the first ThinkPad thermal
  input drives the override. Other controllers must not run concurrently.
- A local authorized client can consume bounded IPC work. The Unix accept
  queue and request deadline limit individual requests; this is not a general
  resource-isolation or availability guarantee.
- Hardware write failures can defeat software recovery. The daemon reports
  failure instead of claiming the fallback worked. It does not bypass the
  firmware, disable thermal protections or offer fan-off/disengaged modes.
- This repository has automated tests and a source review, not an independent
  professional security audit or hardware safety certification.

## Static-analysis exceptions

Bandit has two narrow, reviewed annotations: `B404` for importing subprocess
in the explicit installer, `B603` for its fixed `/usr/bin/systemctl` argument
arrays. These are deliberate
capabilities with the boundaries described above. They are not blanket rule
exclusions; other instances remain checked. Omarchy's advisory scanner also
reports process execution, output collection, installation and service
management as capabilities requiring review.
