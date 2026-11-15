# 旋律型 BGM 与旁白混音

配乐围绕视频的受众、讲解密度、章节和观察空隙编写。先确定风格和主要乐器，再写一个能辨认的短主题、和声与结尾，让主题在段落之间有所变化。器乐的旋律与节奏给旁白留出空间；较长观察区间可以承接主题。钢琴、轻木琴、柔和弦乐是教学片的一个温暖室内乐选择，具体乐器、调性、速度与片长随任务确定。

## 开工与依赖

主运行目录的 `runtime-config.json` 记录 `music.python`、`music.engine`、`music.config`、`music.upstream_commit`。解释器、引擎和配置路径均支持相对运行目录的路径；执行时解析为绝对路径。不依赖作者盘符或另一个全局安装的技能。

安装器准备独立音乐 venv 与固定提交的 music-production 引擎，仅下载所选音源，默认 VCSL、VSCO。音乐引擎及采样的锁和许可随安装器维护；制片环境与音乐环境分开。日常 doctor 只读核对源文件哈希、解释器、工具和音源，真实离线 smoke 使用公开短谱渲染。依赖或文件指纹变化后重新检查。云端 Agent Plan、Chrome 登录和“创建图片”分别验收。

`video build/resume` 在收费配音前执行任务预检与谱面验证。未提供原创谱面时返回 `needs_music_plan`；音乐环境缺项时报告具体能力，补齐后开工。不得用旧鼓点生成器自动代替所需的原创编曲。

## 制作计划

`production-plan.json` 的 `music` 使用以下一种来源。数据路径相对项目目录；可执行程序和配置由本机运行配置决定。

```json
{"mode":"score","score":"engineering/music/song.json"}
```

```json
{"mode":"file","file":"assets/music/licensed-track.wav","rights":"用户提供并确认可用于本项目"}
```

```json
{"mode":"none"}
```

`file` 可提供 `sha256` 验证输入。音乐长度应与旁白样本数一致；长度不符时修订谱面、尾音或明确准备好的音频，不静默截断或变速。`none` 仍输出与时间线等长的静音 BGM，维持导入包结构。

需要仅制作或重混配乐时，使用独立入口复用现有旁白与字幕时间，不提交 TTS：

```powershell
& <runtime>/run.ps1 music create --dialogue <旁白.wav> --cues <cues.json> --score <song.json> --output <新音频目录>
```

来源三选一：`--score`、`--file`、`--no-music`。`--cues` 接受时间列表或含 `cues` 的字幕报告；`--mix-options` 接受覆盖混音参数的 JSON 文件。该命令产出音频；已有原生草稿按下述新副本流程接入，不会直接写入用户草稿。也可使用明确的运行解释器执行 `<runtime>/scripts/music.py create ...`。

原创谱面沿用固定引擎的 `music-production/v1` 格式。按安装后引擎 `references/schema.md` 编写 `clock`、`sections`、`tracks`、`notes/performance`、`mix`；每个声部选择实际安装的音源与音域。写下结构和主题，处理谱面检查提出的和声、配器与重复问题，再作完整渲染。音乐引擎负责采样乐器演奏、MIDI、分轨、总线与母带；Agent 对旋律、和声及段落作曲，不以音符数量宣称听感。

发行包包含 `examples/music-demo-score.json`：40 秒、12 小节的原创钢琴／马林巴木琴／弦乐小品。`music-smoke-score.json` 为 12 秒安装夹具。两者均无外部歌曲、MIDI 或私人实验素材。`music_fixtures.activity_fixture()` 生成的 PCM 活动是用于数值测试的声调，**不是语音**。

## 旁白避让

输入旁白为 48 kHz WAV，混音模块复制原文件为 `dialogue.wav`，不重新归一化旁白。BGM 及最终混音为 48 kHz 立体声 PCM16，长度保持不变。

教学讲解的默认配置：字幕覆盖与 20 ms PCM 活动取并集，讲话前保护 300 ms、后保护 650 ms，合并小于 1.5 秒的短空隙。观察区间音乐参考约 −30 dBFS RMS，说话时额外降低 14 dB；按实际声音能量进一步压低，使旁白活动的 500 ms 窗口以 26 dB 差距为目标，P10 至少 24 dB。恢复不超过 6 dB/s，避免句间抽动。真峰值上限 −1 dBTP。

可通过 `music.mix` 覆盖实际需要调整的参数，例如：

```json
{"mode":"score","score":"engineering/music/song.json","mix":{"target_gap_db":28,"minimum_gap_p10_db":26,"observation_rms_dbfs":-32}}
```

旧版平铺的 `voice_lufs/music_lufs/duck_db/...` 参数仅用于核验并复用原有缓存。新的制作使用上述来源与混音配置。旁白本身缺少混音峰值余量时报告具体问题；在新版本中明确处理音频，不把它当作配乐成功。

## 产物与恢复

- `original.wav`：未加入旁白避让的完整器乐母带或用户音频原件。
- `dialogue.wav`：字节保持的旁白。
- `bgm.wav`：已加入避让的完整 BGM；原生草稿按音量 1.0 使用。
- `mix.wav`：两轨相加的预览混音。使用分轨时不叠加此文件。
- `music-receipt.json`、`ducking-envelope.json`：输入／输出哈希、渲染身份、响度、差距分位数与自动化记录。
- `audition.mp3`：最多 48 秒的混音试听；完整渲染目录保留 MIDI、分轨、母带与引擎报告。

谱面、音源、旁白、字幕与混音参数参与缓存身份。相同输入复用完整结果；本地渲染被中断时只恢复身份一致且有本工具请求记录的渲染目录。已有效的旧音乐缓存按原输入指纹保留，不重作。未知文件和不匹配的恢复目录保留并报告。

配乐需要变化而原生草稿已存在时，新建项目版本并复用旁白和视频素材。对用户最后保存的草稿采用原生副本与媒体引用替换，核对片段 ID、字幕样式、时序、布局和音量；预览优先复制原导出视频流后换入混音。音频测量、后台引擎读取与用户实际听审分别记录。
