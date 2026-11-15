# Windows setup and recovery

[简体中文](INSTALL.md) · [Home](../README.en.md)

## Install

Start with Windows 11 x64, Codex and your own installation of Jianying Pro.
Download and extract this repository, open PowerShell in its root, then run:

```powershell
powershell -NoProfile -File .\install.ps1
```

The default skill location is your `.agents/skills/jianying-draft-collab`.
An existing legacy `.codex/skills` installation is maintained in place to avoid
duplicates. Tools default to `%LOCALAPPDATA%\JianyingDraftCollab`. Setup prints
the actual skill/runtime locations and check results.

```powershell
powershell -NoProfile -File .\install.ps1 -RuntimeRoot 'C:\VideoTools\JianyingDraftCollab' -SkillRoot 'C:\MySkills\jianying-draft-collab'
```

The managed setup includes fixed Python builds, separate video/music environments,
full FFmpeg, FluidSynth, a pinned music renderer and selected VCSL/VSCO banks.
Expect GB-scale initial downloads; the locked inventory determines exact size and
space checks. Reserve additional room for footage and rendering. No author drive
or global Python installation is required. Choose a shorter root if a music path
length check requests it.

Installed tools are only one part of readiness. Native draft operations, cloud
services and the host browser are verified separately for the actual task.

## Checks and first sample

```powershell
$runtime = Join-Path $env:LOCALAPPDATA 'JianyingDraftCollab'
& "$runtime\run.ps1" env doctor --task install --details
& "$runtime\run.ps1" env smoke --local-only --output "$runtime\checks\local-first"
& "$runtime\run.ps1" env preflight --task music
& "$runtime\run.ps1" draft doctor
& "$runtime\run.ps1" draft probe --output "$runtime\checks\native-first"
& "$runtime\run.ps1" env smoke --output "$runtime\checks\full-first"
```

Use a new output directory for each smoke/probe. Doctor is read-only and offline.
The local-only sample actually renders music and video, and its evidence covers
only those local capabilities. Native probe creates an isolated test draft,
edits it and reopens it without registering a user project.

For a changed editor interface, inspect doctor output and ask Codex to follow the
skill's local compatibility workflow. Verify the required operations in copies
before caching the adapter on that device. Do not upgrade or downgrade the editor
as the default compatibility workaround.

## Agent Plan and existing audio

Edit the actual runtime's `.env` with your own `VOLC_AGENT_API_KEY`, and confirm
the model, endpoint and voice from its template. Process variables override this
file; credentials from unrelated projects are not loaded.

Present configuration is `configured_unverified`. A separate
`env cloud-smoke --output NEW_DIR` performs real TTS/ASR/vision requests and may
incur service charges. Run it within the task's authorization and preserve request
and pending records. Resolve uncertain outcomes before resubmitting.

Existing narration and aligned captions can be imported locally. Music and media
processing need no cloud key. Only the services needed by the current task gate
production; unrelated services do not block closeout or local audio work.

## Chrome image pages

Connect the intended Chrome profile through the Codex desktop app's Computer Use
settings and official extension. Mention `@Chrome` in the current chat and sign
in to ChatGPT yourself. Follow the extension's instructions when local-file
uploads require access.

Verify connection, login, project access, Create image and original downloads
separately. A readable public page does not prove image generation. Resume by
checking the conversation and downloads before retrying an uncertain request.
New explanatory image pages use Create image; subtitles remain editable text tracks.

## Updates, cache and rollback

```powershell
# Verify and deploy managed code from a new source checkout
powershell -NoProfile -File .\install.ps1
# Explicitly repair missing environments, programs or sound banks
powershell -NoProfile -File .\install.ps1 -Repair
# Read-only installation probe
powershell -NoProfile -File .\install.ps1 -ProbeOnly
# Restore the previous managed installation
powershell -NoProfile -File .\install.ps1 -Rollback
```

Updates preserve `.env`, local configuration, projects and user-added files.
Unexpected managed-file changes are reported as conflicts. Review and merge
local edits before replacing them. Backups stay outside skill discovery folders.

Use `-ArchiveCache` for a chosen download cache and `-Offline` to require complete,
verified cached assets. Interrupted downloads are not treated as success. Re-running
setup validates completed data before resuming. Rebuild environments from locks;
do not transfer an author's venv as a portable distribution.

## Diagnostic states

| State | Next action |
|---|---|
| Missing tools or banks | Explicit Repair; inspect space, source and checksum |
| Native capabilities unverified | Isolated probe, then device-local adaptation |
| Adapter fingerprint changed | Revalidate affected operations before writes |
| Cloud configured but unverified | Check your service and authorize cloud-smoke |
| Browser unavailable | Restore the host connection/account; retain the image queue |
| Editor is running | Keep the verified new draft and register after natural exit |

Use the [VM checklist](windows-vm-test.md) for recipient testing. Keep original
footage, private drafts and credentials out of public reports.
