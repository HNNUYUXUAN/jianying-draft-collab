# 干净 Windows 验收 / Clean Windows acceptance

此流程用于验证新用户从零安装。新目录安装、CI 工具验证和真实剪映使用分别留证；前者不能替代后者。

This procedure verifies first-time setup. A new directory, CI tool checks, and actual Jianying use are separate evidence levels.

## 环境 / Environment

使用全新的 Windows 11 x64 虚拟机、Windows Sandbox 或独立设备。记录 OS build、PowerShell 版本、Codex 版本、剪映版本与构建指纹；不导入作者的 Python、Conda、uv、Git、媒体工具、音源、环境变量或用户项目。剪映与 Codex 由测试者从官方渠道安装。预留至少 6 GB 安装空间，另加剪映、项目与虚拟机空间。

Use a fresh Windows 11 x64 VM, Sandbox, or independent device. Install Codex and Jianying from official sources. Record their versions and OS build. Do not copy the author's runtimes, account settings, media, or projects. Reserve at least 6 GB for tools/cache, plus the application and test project.

## 本地工具 / Local tools

1. 将仓库源码复制到普通目录。使用系统 PowerShell 5.1，从不含 Python／Conda／uv／Git 的 PATH 开始，运行 README 的安装命令。保存安装预算、来源校验、工具和音乐环境自检结果。
2. 在无云 Key、无 Chrome 登录时，先运行 `env smoke --local-only --output NEW_DIR`，再运行 `env preflight --task music`。检查 12 秒预览可完整解码、四条乐器分轨、MIDI、已知字幕和原旁白字节保持。
3. 保留下载缓存后，在另一个空运行目录使用 `-ArchiveCache CACHE -Offline` 安装。该结果标为“缓存复用离线安装”；缺一个缓存文件时必须明确失败，不能新联网或切换版本。
4. 修改一个受管源码文件后升级，确认报告具体冲突且改动保留。添加用户配置后正常升级／回滚，确认 `.env`、`runtime-config.json`、项目和新增文件字节不变。

Start with stock PowerShell and a minimal PATH. Validate music without credentials. Separately test an offline installation using the complete verified cache, a missing-cache failure, upgrade conflicts, configuration preservation, and rollback.

## 剪映集成 / Jianying integration

1. `draft doctor` 识别本机安装；多个候选或未确认版本应报告明确选择／探测动作，不静默选最高版本。
2. 在空目录运行 `draft probe`，完成合成四轨、隔离副本、独立身份、素材替换及重读验收，确认未注册或改动用户项目。
3. 运行完整 `env smoke`；再运行 `env doctor`，确认当前指纹匹配。随后再次执行 `--local-only` smoke，完整原生证据应继续有效。
4. 运行公开示例，按授权注册其新草稿。由测试者打开剪映，播放、保存、退出后重新打开并导出。记录这四个动作的实际结果，不用后台解析代替。
5. 从用户保存的草稿创建配乐修订版，验证字幕文字／样式／时间线、旁白 SHA、素材引用与原版本保护；归档后做全片解码。

Validate the installed application's identity, isolated probe, full smoke, a registered public sample, and actual playback/save/reopen/export. Verify that a BGM-only revision preserves user edits and the original narration.

## 云与 Chrome / Cloud and Chrome

只在测试者授权后配置自己的 Agent Plan Key，并执行显式 cloud-smoke。分别记录“Key 存在”“账号真实调用”“样例完成”。测试者在 Chrome 登录自己的 ChatGPT，通过 Codex 宿主连接核验“创建图片”和原图下载；不共享 Cookie、密钥或作者会话。

Use the tester's own authorized accounts. Record configured credentials, real requests, and completed samples separately. Verify the connected Chrome Create image and original download flows without sharing keys, cookies, or author sessions.

## 报告 / Report

在私有验收目录保存命令、退出码、时间、依赖锁、检查报告、样例 SHA、原生读回、用户动作与阻塞。公开只提交脱敏的版本矩阵、通过范围及产物摘要。任何未执行项写 `not_tested`；仅完成 CI 时标为工具链验证，不宣称剪映 GUI 或干净系统完整通过。

Keep detailed evidence private. Publish only sanitized version/scope summaries. Mark unperformed steps `not_tested`; CI alone proves neither GUI behavior nor complete clean-system acceptance.
