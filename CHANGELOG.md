# Changelog

All notable changes to this project will be documented in this file.

## v0.2.1 - 2026-04-13

### Changed

- Heartbeat scheduling now runs at a nominal `300s` interval with bounded `±90s` jitter.
- Targets within the same heartbeat round are shuffled and lightly spread out instead of always probing in the same sequence.
- The dashboard status copy now shows the nominal heartbeat cadence and jitter behavior.
- README, `.env.example`, and the NAS handoff document were aligned with the live heartbeat policy.

## v0.2.0 - 2026-04-11

### Added

- Server-rendered speedtest schedule summary on the homepage.
- Visible app version in the dashboard header.
- Handoff document for the live NAS deployment workflow.

### Changed

- Default formal speedtest windows changed to `05:00,16:00`.
- Default heartbeat interval changed to `120s`.
- Default heartbeat targets reduced to `223.5.5.5,119.29.29.29,1.1.1.1`.
- Dashboard loading changed from all-at-once requests to section-based loading with partial fallback.
- Seven-day heartbeat view now prefers `1h` buckets and a denser lattice layout for better panorama visibility.
- Heartbeat target summary now uses grouped SQL aggregation instead of per-target history scans.
- Speedtest timeline keeps failed samples in time order and shows a single-sample summary when only one successful point exists.
- README, `.env.example`, and deployment handoff docs were aligned with the live NAS profile.

### Fixed

- Dashboard sections no longer collapse together when one API request fails.
- Frontend schedule fallback text now matches the live default schedule.
- Speedtest error storage keeps the first meaningful CLI output line instead of only exit status text.

## v0.1.0 - 2026-04-02

### Added

- Initial Flask dashboard for NAS internet monitoring.
- SQLite-backed storage for heartbeat and formal speedtest history.
- Multi-target heartbeat probing, Bark notifications, CSV export, and manual speedtest trigger.
