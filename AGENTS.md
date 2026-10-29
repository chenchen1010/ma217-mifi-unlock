# Working on this repository

- Read README and docs/REPRODUCE.md before touching a connected device.
- No subagents without the human user's approval.
- Keep raw backups, identifiers, calibration data, diagnostic streams and local evidence under ignored artifacts/. Never publish them.
- Only one hardware/firmware profile is verified. Do not weaken hashes or silently generalize offsets to other versions.
- Write only the aligned 0x260000..0x320000 range; no factory reset, identity edits or whole-chip erase.
- Keep recovery and original backup intact. Execute the real OBMI erase-wrapper model, not a mock that assumes request length equals erased length.
- Rebuild and decoder checks are offline evidence. Claim actual success only from readback, normal boot, active external SIM and interface-bound Internet checks.
- Report human unplug/restart events separately from device instability. Do not inflate partial observation into completed duration.
- The user can authorize device operations in the session; do not ask for duplicate permission once scope is clear.
