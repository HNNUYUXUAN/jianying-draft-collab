# Validation / 验证记录

Release: **0.1.0** · Date: **2026-11-15**

Evidence is scoped to the machine and command that produced it. A configured
key, installed dependency or version number is not a successful service or editor
test. / 证据仅覆盖实际执行的环境；配置存在、安装完成和版本号分别记录。

| Check / 检查 | Evidence / 证据 |
|---|---|
| Python regression | 87 tests passed with the dedicated FFmpeg path enabled, with no skips, including rejection of an unverified audio-add flag. The initial 73-test run had 3 environment-dependent skips before that path was supplied. |
| Installer behavior | 10 Windows PowerShell 5.1 checks passed: ownership/conflicts, update/rollback, configuration preservation, verified offline cache, bounded retry, HTTP Range recovery and changed-tool rejection before execution. These use local doubles, not a claim of live network throughput. |
| Fresh-directory setup | Stock Windows PowerShell 5.1 installation completed in a new C-drive directory, creating portable Python and independent core/music venvs. The key-free 12-second music/video/four-track native smoke passed. This is the maintainer's existing Windows machine, not a clean Windows VM. |
| Original music | The 40-second public piano/marimba/strings score rendered to 48 kHz stereo, 24-bit WAV, MIDI, stems and MP3. All 11 renderer technical checks passed; measured −22.00 LUFS, −3.89 dBTP, LRA 6.1. Listener approval is separate. |
| Narration-aware mix | A 12-second numerical activity fixture preserved input voice bytes. Active-window voice-minus-BGM P10/median/P90: 26.00 / 33.93 / 52.57 dB; mixed true peak −17.96 dBTP. The input is an identified synthetic tone, not human speech evidence. |
| Native protocol | Installed Jianying Pro 11.7.0.14652: isolated create, read, add video/audio/text, text content/style, audio/video volume, segment movement, timing, blueprint, removal, encrypted read and independent copy passed. Original fixture and user project index remained unchanged. A separate real independent-copy edit verified text, volume, start/duration and bold/italic/size/color/alpha; a new process reopened 4 tracks, 4 segments and 3 local media references with a matching verification receipt. This does not certify other installations or app UI playback. |
| Chrome images | Two bilingual concept illustrations generated through connected Chrome ChatGPT Create image, original downloads decoded at 1672 × 941; aspect-preserving WebP derivatives reviewed. Model identity is unknown. |
| Public CI | [Windows run 43722607443](https://github.com/HNNUYUXUAN/jianying-draft-collab/actions/runs/43722607443) passed in 3m28s on code commit `69f58f0`. Stock-only PATH setup, 87 regression tests, package checks and real local music/video rendering passed. This is a hosted Windows-2025 toolchain test, not Jianying GUI or a clean Windows 11 VM. |
| Agent Plan | Transport/cache/state regressions use mocks in this release. No new paid TTS, ASR or vision request was made for release certification. Recipients configure and verify their own account. |
| Recipient VM | **Pending user testing**, intentionally after first publication. Use [the VM checklist](windows-vm-test.md). |

## Installation and integration evidence

The pinned download set is about 916 MB plus roughly 70 MB of Python wheels.
The local setup trial downloads portable Python and creates new core/music
environments. It uses checksum-verified archive caches for the large sample
banks. An interrupted initial FFmpeg transfer was retained; its official archive
was fetched through the existing GitHub CLI/system proxy and verified before
installer reuse. This is a recovery/cache test, not proof of uninterrupted
downloads on every network.

Public preview files are copied from the actual fresh-directory smoke render.
The GIF contains 80 actual frames from that preview; it is not an editor UI mockup.
The original CI harness exposed a retained expected-failure exit code, missing
FFmpeg PATH in direct test execution and Windows 8.3 path-alias comparisons.
The harness was corrected; the same 87 tests then passed both in a local new
runtime with minimal PATH and in the public CI run linked above.

The maintained local installation and independent acceptance installation both
passed final isolated native probe and full music/video/native smoke. Existing
production `.env` bytes were preserved. Music and closeout preflight are ready.

GitHub README presentation was checked in connected Chrome in both languages,
light/dark modes, desktop widths of 1309–1440 CSS pixels and a 390 CSS-pixel phone
viewport. Header images, the actual animated sample and Mermaid diagrams loaded;
no page-level horizontal overflow was observed. Temporary emulation was reset.

## What recipients verify

Run tool checks, the key-free local sample and the isolated native probe on the
recipient device. Check playback, saving and reopening in that device's editor.
Run paid cloud acceptance only within the task's authorization. The installer
does not log into ChatGPT, install Jianying or change editor versions.

完整成片应另做完整解码、素材引用检查和人工听感审阅。源码测试不能代替接收端
剪映播放与导出，也不能将合成样例当作真实实验数据。
