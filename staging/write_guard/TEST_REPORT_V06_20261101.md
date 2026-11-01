# IRONMAN Write Guard v0.6 — execution report, 2026-11-01

Status: CANDIDATE, uninstalled; **not** an authenticated end-to-end Google write.

- Source baseline: v0.5 from current Project conversation package.
- Fixed: signed approval path was supported by the core authorizer, but the
  on-host configuration loader could not construct it; now it loads approved
  grants and HMAC trust material from separate owner-only files. Incoming HTTP
  cannot change trusted policy or supply credentials.
- Hardened: trusted configuration/private authorization files are required to
  be owned by the running process and have no group/world permissions or
  final-path symlinks. Operators must secure directory traversal and service
  user/secret-store independently before deployment.
- Added: read-only identity/document probe with no document text in output.
- Automated tests: 86/86 PASS in offline/local environments; Python compile
  checks passed. Includes signed-configuration mutations, wrong key/signature,
  private-file permission checks, read-only Google availability classification.
- Not performed: actual Google Cloud IAM provisioning, provider-authenticated
  Write Guard => Docs write, ChatGPT => Write Guard HTTPS connector invocation,
  live process crash recovery, forced routing/no-bypass, production deployment.

**Engineering decision:** do not deploy to a public listener or disable
existing Google Drive writes until identity and HTTPS plugin registration are
available, a disposable-document full-path canary passes, and rollback is
verified. Knowledge V1 remains canonical, V2 remains staging.
