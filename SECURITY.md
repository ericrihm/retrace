# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Yes       |

Older versions receive no security patches. Please upgrade to the latest 0.1.x release.

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email **support@cobaltsystems.io** with:

- A description of the vulnerability
- Steps to reproduce (command, input file, or code snippet)
- Expected vs. actual behavior
- Any relevant environment details (OS, Python version, re:trace version)

Encrypt sensitive reports with our PGP key if needed (available on request).

## Response Timeline

| Milestone           | Target       |
| ------------------- | ------------ |
| Acknowledgment      | 48 hours     |
| Triage and severity | 5 days       |
| Fix or mitigation   | 7 days       |
| Public disclosure   | Coordinated  |

We follow responsible disclosure. If you need more time before public disclosure, let us know in your report.

## Scope

**In scope:**

- The re:trace CLI and Python library (`src/retrace/`)
- Parsing and analysis pipelines (component detection, trace extraction, BOM generation)
- Dependency vulnerabilities that affect re:trace users

**Out of scope:**

- The boards, devices, or firmware being analyzed — re:trace is a passive analysis tool
- Third-party services or APIs not bundled with re:trace
- Issues that require physical access to the machine running re:trace

## Credits

We appreciate responsible disclosure and will acknowledge reporters in the release notes (unless you prefer anonymity).
