# Windows 安装与开工前自检

支持 Windows x64 和 Windows PowerShell 5.1。首次安装不要求已有 Python、Conda、Git、uv 或独立 FFmpeg。剪映专业版由用户从官方渠道安装，技能仅读取已安装应用；原生能力以本机版本、文件指纹和隔离验收结果为准。

默认运行目录为 `%LOCALAPPDATA%/JianyingDraftCollab`。新技能默认安装到 `%USERPROFILE%/.agents/skills/jianying-draft-collab`；检测到既有 `.codex/skills` 版本时原位维护，两个位置同时存在则要求通过 `-SkillRoot` 明确选择。真实安装路径记录于技能目录 `.installation.json` 的 `runtime_root`；读取此记录或显式参数后定位入口，不使用作者电脑盘符。

## 首次安装、重试与升级

从仓库根执行；安装只修改所选目录和进程环境，不注册 Python、不修改全局 PATH，不安装或启动浏览器，不启动、激活或关闭剪映。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Repair
```

可选参数：`-RuntimeRoot DIR`、`-SkillRoot DIR`、`-ArchiveCache DIR`、`-Offline`、`-MediaSource DIR`、`-CorePython EXE`。遵守组织执行策略，命令仅设置当前进程策略。`-ProbeOnly` 不创建或部署运行环境；普通更新保留依赖与配置，`-Repair` 才准备环境并重新核验工具。`-Rollback` 恢复上一受管源码版本，保留本地配置、素材、缓存和环境。

安装约需下载 916 MB 固定归档与约 70 MB Python wheels；包括所选钢琴／木琴／弦乐音源。保留约 6 GB 可用空间供安装、缓存和短样例使用；剪映程序、项目视频及版本备份另计。安装器显示预算、具体文件大小和进度，复用校验通过的已下载文件。自定义运行目录和缓存可位于不同卷。

下载仅使用锁定的官方 HTTPS 来源，逐项检查尺寸和 SHA-256。单次连接限时 45 秒、读取停滞限时 30 秒、单次传输最长 600 秒，最多尝试三次。读取显式代理设置；未设置时复用当前 Windows 系统代理，不记录代理地址或凭据。已绑定原始 URL 与锁定 SHA 的 partial 可通过 HTTP Range 续传；服务器忽略 Range 时保留旧 partial 并重新下载，完整校验后才发布为缓存。旧的无所有权记录 partial 保留待检查，不视为成功缓存。

`-Offline` 禁止新网络下载，需要同一个缓存中已有全部归档及 uv wheel 缓存。缺失或损坏时报告具体文件并停止；不安装替代版本。失败保留已完成环境、回执与 partial，修复具体缺项后重跑同一命令。未知目录、用户改动的受管文件、哈希不符及链接路径均保留并报告冲突，不静默覆盖。

## 锁定的本地设施

- 便携 uv 0.13.6、便携 CPython 3.11.16。core 与 music 使用独立 venv；uv 指定解释器安装锁定依赖，venv 不要求 pip。
- core 使用带全部传递依赖及 wheel 哈希的 `requirements-core.lock`；music 固定 NumPy 2.1.2，保持与音源构建版本一致。
- FFmpeg/FFprobe 8.1.2 full，包含字幕、响度、编码与解码能力，并保留上游许可证。
- 固定提交的 music-production 引擎、FluidSynth 2.6.1、MS Basic 及 VCSL／VSCO 采样。只安装本工作流使用的音源，不安装 Surge；记录锁和上游许可。
- Microsoft YaHei 来自 Windows 字体。缺失时先添加 Windows 中文补充字体，技能不分发微软字体。

来源、尺寸与 SHA 在 `environment-lock.json`、`media-toolchain.json` 和 `music-toolchain.json` 中维护。`runtime-config.json` 保存 `core`、`media`、`music`、`jianying` 的本机路径，文件内相对路径均以运行目录解析。项目文件不能指定任意可执行程序。已有兼容 Conda 可用 `-CorePython EXE` 原位复用，安装器只核验该外部环境，不向其中执行 pip sync 或删除包；缺依赖时选择独立运行目录。

## 自检与充分性门槛

```powershell
$runtime = Join-Path $env:LOCALAPPDATA 'JianyingDraftCollab'
powershell -NoProfile -ExecutionPolicy Bypass -File "$runtime\run.ps1" env doctor --details
powershell -NoProfile -ExecutionPolicy Bypass -File "$runtime\run.ps1" env preflight --task music
```

doctor/preflight 检查当前解释器和依赖版本、固定媒体工具、中文字体、采样引擎与音源、剪映适配状态，以及对应能力真实 smoke 回执的指纹和产物完整性。默认 doctor 检查完整本地能力；`--task install` 只报告 core／media／font／music 工具就绪，不能代表原生草稿已可用。`--task closeout` 仅检查 core／media 与当前指纹下已通过隔离 probe 的 native read；不要求音乐环境或渲染 smoke，回执标记 `closeout_read_and_media_checks`，最终成片的完整解码由扫尾动作另行完成。检查本身不安装、不渲染、不调用云；`--output PATH` 仅在用户指定时写检查报告。

正式 `video prepare/build/resume` 在消耗云端资源前调用按任务要求的 preflight。使用原创乐谱时需要音乐环境；明确选择已有音频或不配乐时省去采样引擎要求。已有完整旁白和字幕缓存可免除新语音配置要求。环境、代码、音源或适配指纹改变后，旧验收不能继续放行，需重新运行相应 smoke。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$runtime\run.ps1" draft doctor
powershell -NoProfile -ExecutionPolicy Bypass -File "$runtime\run.ps1" draft probe --output NEW_PRIVATE_DIR
powershell -NoProfile -ExecutionPolicy Bypass -File "$runtime\run.ps1" env smoke --output ANOTHER_NEW_PRIVATE_DIR
```

`draft probe` 仅操作合成夹具和隔离副本，不注册用户项目。完整 env smoke 真实渲染 12 秒公开乐谱、已知声调夹具、中文字幕、预览和四轨草稿，并完成解码和原生重读；声调是测试输入，不是 TTS／ASR 证明。成功后保存按当前能力指纹绑定的回执。`env smoke --local-only` 可在尚未安装剪映的机器上验证本地音乐／媒体能力，但不授予 native；随后完成 `draft probe` 后，还需完整 `env smoke` 验证集成。full 和 local 回执分别保留，本地重验不会撤销仍有效的完整证据。

## 账号、云端与 Chrome

运行只读取运行目录根 `.env` 与进程环境，同名进程变量优先。公开 `config.example.env` 只含空 Key 和默认模型参数；不复制其他项目凭据。配置文件和密钥不进入分发清单、回执或公开示例。

Key 存在记录为 `configured_unverified`。只有获得当前任务云验收授权后，才运行 `env cloud-smoke --output NEW_DIR`，实际核验 TTS、ASR 和视觉请求；成功响应、缓存和 pending 分别保存，不重复提交未决收费请求。模型、账号、端点或配置改变后重新验收，不借用其他账号的旧结果。

Chrome 连接、ChatGPT 登录、“创建图片”、原图下载属于宿主能力，Python doctor 不能代替。按 image-generation.md 逐项核对，并让首个正式候选承担生成／下载实测。已通过本地检查不代表浏览器或云账号已通过。

## 配置保留与验收边界

安装按 manifest 白名单维护源码，升级前比较已安装哈希；版本备份位于技能发现目录之外及运行目录的 sibling backups。`.env`、`runtime-config.json`、项目、缓存和用户新增文件不属于源码覆盖清单。普通目录交付，不自动打包。

安装结果、工具就绪、隔离 smoke、同机重定位、干净 Windows 和用户在剪映中播放／保存／重开分别记录。没有真实干净系统证据时，不将本机新目录安装称为干净系统通过；完整流程的复测说明见仓库 `docs/windows-vm-test.md`。
