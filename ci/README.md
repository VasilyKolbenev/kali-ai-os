# `ci/` — staged GitHub Actions workflows

These YAML files are GitHub Actions workflows **staged outside `.github/workflows/`
on purpose**. The push token used for this repo lacks the GitHub `workflow`
scope, so any commit that adds or edits a file under `.github/workflows/` is
rejected. Keeping them here lets the config live in the repo and be reviewed; it
just does not run yet.

## Activating a workflow

To make a workflow live, **re-home it to `.github/workflows/<name>.yml`**, either:

- via the **GitHub web UI** (create the file, paste the contents), or
- with a **push from a token/PAT that has the `workflow` scope**.

Once a copy exists under `.github/workflows/`, GitHub picks it up. (`ci/core-loop.yml`
follows this same pattern.)

All release workflows below are **`workflow_dispatch` (manual)** — they never
auto-run on push and never fail a PR. They are also **secrets-gated**: with no
secrets configured they either no-op the credentialed step (signing / upload) or
fail fast with a clear message, never with a hardcoded credential.

---

## Workflows

### `core-loop.yml`
Fast, ML-free `pytest -m core_loop` gate + informational ruff. Runs on push/PR
(already wired). No secrets. (Pre-existing — documented here for completeness.)

### `release-desktop.yml` — Windows desktop installer
Builds the KALI Premium Windows installer end to end: PyInstaller backend →
Tauri shell → InnoSetup pipeline (`scripts/build_installer_premium.bat`) → optional
Authenticode signing → uploads the `.exe` as a build artifact.

- **Runner:** `windows-latest`. **Trigger:** manual (`workflow_dispatch`).
- **Signing is optional** and mirrors `build_installer_premium.bat` (WS-5.2): if
  the cert secret is absent, signtool is skipped and an **unsigned** installer is
  produced — the job still succeeds.
- **Secrets (all optional — unsigned build without them):**
  - `KALI_SIGN_CERT` — base64 of the `.pfx` code-signing certificate (EV cert).
  - `KALI_SIGN_PASS` — certificate password (omit if the `.pfx` has none).
  - `KALI_SIGN_TR_URL` — RFC-3161 timestamp URL (defaults to DigiCert in the script).
- **Human-gate:** an **EV / OV Authenticode code-signing certificate** (purchased,
  tied to the publisher identity). Until then the workflow runs and ships an
  unsigned installer.

### `mobile-android.yml` — Google Play (AAB)
`flutter build appbundle` + a fastlane lane (`mobile/android/fastlane/Fastfile`).
Lane input: `build` (assemble AAB only, artifact uploaded) or `deploy_play`
(upload to the Play **internal** track as a draft).

- **Runner:** `ubuntu-latest`. **Trigger:** manual (`workflow_dispatch`).
- **Secrets:**
  - `ANDROID_KEYSTORE_BASE64` — base64 of the upload keystore (`.jks`).
  - `KALI_UPLOAD_STORE_PASSWORD` / `KALI_UPLOAD_KEY_ALIAS` / `KALI_UPLOAD_KEY_PASSWORD`
    — keystore creds (names match `signingConfigs.release` in
    `app/build.gradle.kts`, WS-4.5).
  - `PLAY_SERVICE_ACCOUNT_JSON` — base64 of the Play Console service-account JSON
    (needs "Release apps to testing tracks"). Required only for `deploy_play`.
- **Human-gates:** a **Google Play Console** developer account, a registered
  upload keystore, and a service-account key with release permission. `build`
  works without them (debug-signed fallback); `deploy_play` fails fast without
  the Play secrets.

### `mobile-ios.yml` — App Store Connect / TestFlight (IPA)
`flutter build ipa` + a fastlane lane (`mobile/ios/fastlane/Fastfile`). Lane
input: `build`, `pilot` (TestFlight), or `release` (upload to App Store Connect,
not auto-submitted).

- **Runner:** `macos-latest`. **Trigger:** manual (`workflow_dispatch`).
- **Secrets:**
  - `APP_STORE_CONNECT_API_KEY_ID` — App Store Connect API key id.
  - `APP_STORE_CONNECT_API_ISSUER_ID` — issuer id for that key.
  - `APP_STORE_CONNECT_API_KEY` — base64 of the `.p8` private key.
  - `APPLE_TEAM_ID` / `ITC_TEAM_ID` — team ids (optional, only if the account needs them).
- **Human-gates:** a **paid Apple Developer Program** membership, an **App Store
  Connect API key**, and provisioning/signing assets. iOS also cannot build off a
  Mac runner. Until all three exist this workflow is inert scaffolding.

---

## fastlane

The fastlane configs live at their normal mobile paths (they are **not**
workflows, so the `workflow`-scope block does not apply):

- `mobile/android/fastlane/{Fastfile,Appfile}` — lanes `build`, `deploy_play`.
- `mobile/ios/fastlane/{Fastfile,Appfile}` — lanes `build`, `pilot`, `release`.

Both read every credential from the environment (the secrets above). Decoded
secret files (keystore, service-account JSON) are written to gitignored paths at
runtime — none is ever committed.

> **Note:** the bundle / package id is `ai.kali.mobile` on both platforms (matches
> `app/build.gradle.kts` and `ios/Runner/Info.plist`).
