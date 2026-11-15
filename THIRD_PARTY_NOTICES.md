# Third-party components

Original code and documentation use the root MIT license. Third-party code,
programs and recordings retain their own terms; the runtime locks pin revisions.

| Component | Source | License / handling |
|---|---|---|
| Draft builder | [GuanYixuan/pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft), `1e228479dda361e312e85f6037002346cf6dca9a` | Apache-2.0; bundled in runtime `scripts/vendor/pyJianYingDraft`, optional desktop-controller import disabled. Vendor LICENSE and BUILDER_PROVENANCE.json retained. |
| Legacy local codec | [aoguai/pyJianYingDraft](https://github.com/aoguai/pyJianYingDraft), `d85eee31c233eeab6223557552eda63005ef95e2` | Apache-2.0; original file and PROVENANCE.md retained. Presence alone does not prove editor compatibility. |
| Legacy DSP | Moessif attribution in vendor `music_synth.py` | MIT; complete vendor MUSIC_LICENSE retained. |
| Music renderer | [music-skill](https://github.com/owoevan-dev/music-skill), `424e7bd1e1f0a328adcd62552145d7172c47e450` | Downloaded during setup. MIT; optional surge_host.py is GPL-3.0-or-later. Default setup does not enable Surge; upstream notices remain with download. |
| VCSL / VSCO 2 CE | [VCSL](https://github.com/sgossner/VCSL), [VSCO 2 CE](https://github.com/sgossner/VSCO-2-CE) | CC0-1.0 recordings; selected banks downloaded and hash checked, not committed here. |
| MS Basic | [MuseScore](https://github.com/musescore/MuseScore) | MIT with named sample-author notices; preserve complete notice with copies of the bank. |
| FluidSynth | [FluidSynth](https://github.com/FluidSynth/fluidsynth) | LGPL-2.1-or-later, downloaded executable. |
| FFmpeg | [Gyan builds](https://github.com/GyanD/codexffmpeg) | GPL build, downloaded separately; LICENSE and README retained with binaries. |
| uv / CPython / Python packages | [uv](https://github.com/astral-sh/uv), [python-build-standalone](https://github.com/astral-sh/python-build-standalone), PyPI | Respective licenses remain with installed distributions. Installer uses locked sources and checksums. |

Jianying Pro is installed separately by the recipient. No proprietary editor
binaries or Windows fonts are distributed. Microsoft YaHei is detected locally.
Public sample sources and licenses are described in `docs/media/README.md`.
