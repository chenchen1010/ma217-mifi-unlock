# Working on this repository

- Entry order: README.md -> SKILL.md -> facts/SUPPORTED_DEVICE.md -> docs/REPRODUCE.md and docs/RECOVERY.md. SKILL.md owns the workflow and stop rules; do not invent a second flow in README or a chat prompt.
- A repository link starts environment inspection and read-only identification. Use the human's session authorization for later device actions; prepare concrete packages and evidence before asking for any missing write authorization.
- No subagents without the human user's approval.
- Keep raw backups, identifiers, calibration data, diagnostic streams and local evidence under ignored artifacts/. Never publish them.
- Only one hardware/firmware profile is verified. An observed hardware, firmware, bootloader, header or image-hash mismatch means INCOMPATIBLE: stop applying this patch. Missing evidence is UNKNOWN or PENDING; continue only the justified read-only steps needed to obtain it. Do not weaken hashes, remove assertions, use Python -O or silently generalize offsets.
- Write only the aligned 0x260000..0x320000 range; no factory reset, identity edits or whole-chip erase.
- Keep recovery and original backup intact. Execute the real OBMI erase-wrapper model, not a mock that assumes request length equals erased length.
- Rebuild and decoder checks are offline evidence. Claim actual success only from readback, normal boot, active external SIM and interface-bound Internet checks.
- Report human unplug/restart events separately from device instability. Do not inflate partial observation into completed duration.
- The user can authorize device operations in the session; do not ask for duplicate permission once scope is clear.
- Documentation acceptance: README begins with a short copyable prompt; platform scope is explicit; every workflow stage has local evidence and a stop path; original dumps stay private; historical/partial results cannot replace live acceptance. Keep release binary hashes and the flash algorithm unchanged for documentation-only updates.
