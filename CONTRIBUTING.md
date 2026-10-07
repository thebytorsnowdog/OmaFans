# Contributing

Thanks for helping. OmaFans controls real hardware, so changes are kept small and easy to review.

- **Hardware reports:** open an issue using the *Hardware report* template. Include the ThinkPad model, kernel version, Omarchy version, and whether monitoring or control worked.
- **Bugs:** use the *Bug report* template. Include the output of `python3 fanctl.py status`.
- **Security issues:** follow [SECURITY.md](SECURITY.md). Do not open a public issue.
- **Pull requests:** run the checks below first, and explain any change to the daemon, the service file or the installer.

```bash
python3 -m unittest discover -s tests -v
python3 scripts/check_release.py
```

Before you post logs, remove usernames, home paths, hostnames and serial numbers.
