# Windows 安装、配置与恢复

[English](INSTALL.en.md) · [返回首页](../README.md)

## 安装

基础环境为 Windows 11 x64、Codex 和接收者自行安装的剪映专业版。获取本仓库源码并解压，在目录中运行：

```powershell
powershell -NoProfile -File .\install.ps1
```

默认技能目录为用户的 `.agents/skills/jianying-draft-collab`；已存在的旧 `.codex/skills` 安装会原位维护，避免重复发现。默认工具目录为 `%LOCALAPPDATA%\JianyingDraftCollab`。安装输出给出实际技能、运行根与检查结果。

```powershell
powershell -NoProfile -File .\install.ps1 -RuntimeRoot 'C:\VideoTools\JianyingDraftCollab' -SkillRoot 'C:\MySkills\jianying-draft-collab'
```

依赖包含固定 Python、两个独立环境、完整 FFmpeg、FluidSynth、固定音乐渲染器及 VCSL／VSCO 选定音源。首次需要约 GB 级下载，准确大小与空间检查以安装器的锁清单为准；另为视频素材和渲染预留空间。工具位于指定根目录，不依赖作者盘符或全局 Python。音乐根路径过长时，按诊断选择较短目录。

安装成功表示工具已准备。原生草稿、云服务和 Chrome 能力仍按任务验证，最终以 preflight 的能力报告决定是否开工。

## 检查与第一个样例

```powershell
$runtime = Join-Path $env:LOCALAPPDATA 'JianyingDraftCollab'
& "$runtime\run.ps1" env doctor --task install --details
& "$runtime\run.ps1" env smoke --local-only --output "$runtime\checks\local-first"
& "$runtime\run.ps1" env preflight --task music
& "$runtime\run.ps1" draft doctor
& "$runtime\run.ps1" draft probe --output "$runtime\checks\native-first"
& "$runtime\run.ps1" env smoke --output "$runtime\checks\full-first"
```

每次 smoke／probe 使用新输出目录。doctor 只读且离线；local-only 样例实际渲染音乐与视频，其回执只证明本地能力。native probe 在独立目录创建测试草稿，验证后重读，不注册用户项目。

遇到新剪映版本时，先读取 `draft doctor` 的状态，再让 Codex 按技能的兼容参考分析已安装接口，在隔离副本上验证本任务所需操作。通过后缓存到本机；不要为解决适配问题直接升级或降级剪映。

## Agent Plan 与已有音频

编辑实际运行目录中的 `.env`，填写你自己的 `VOLC_AGENT_API_KEY`，并按该文件模板确认模型、端点和音色。运行只读取进程环境和该 `.env`，进程变量优先；不读取其他项目凭据。

配置存在记为 `configured_unverified`。真实 TTS／ASR／视觉验收通过独立的 `env cloud-smoke --output NEW_DIR` 完成，会调用服务并可能计费；在本次授权范围内执行，保留请求和 pending 记录。结果不确定时先核状态，不重复提交。

已有旁白及对应字幕可本地导入，音乐和媒体处理无需云密钥。完整新制片使用的服务必须就绪；无关服务不阻断归档或局部音频处理。

## Chrome 讲解图页

在 Codex 桌面应用的 Computer Use 设置中连接实际使用的 Chrome 配置，按提示安装官方扩展；在当前聊天中 `@Chrome`。由用户登录 ChatGPT。需要上传本地文件时，按扩展说明设置对应文件访问权限。

分别验证连接、登录、项目访问、创建图片与原图下载；公开页面可读不代表生图已通过。生成请求或下载结果未决时核对会话与下载目录后恢复。所有新增讲解整图使用“创建图片”，字幕继续用字幕轨。

## 更新、缓存与回滚

```powershell
# 新源码目录中的安装入口：校验文件并更新受管代码
powershell -NoProfile -File .\install.ps1
# 显式修复缺少的工具、环境或音源
powershell -NoProfile -File .\install.ps1 -Repair
# 仅探测现有安装
powershell -NoProfile -File .\install.ps1 -ProbeOnly
# 使用上一版本备份回滚
powershell -NoProfile -File .\install.ps1 -Rollback
```

升级保留 `.env`、本机配置、项目和用户新增文件。受管文件内容与已知版本不符时先报告冲突；核对本地修改后再决定保留或合并。备份放在技能发现目录外。

`-ArchiveCache` 可指定下载缓存；`-Offline` 仅使用完整且校验通过的缓存。断开下载不会被当作成功；再次运行检查已完成内容后恢复。运行环境按锁重建，不把作者机器的 venv 直接复制到另一台电脑。

## 常见状态

| 状态 | 下一步 |
|---|---|
| 工具或音源缺少 | 显式 Repair，检查磁盘、下载来源和哈希 |
| 原生能力待探测 | 隔离 native probe，再依据结果做本机适配 |
| 适配器指纹变化 | 重做相应能力验收，不沿用旧写入许可 |
| 云配置未验证 | 核对自己的服务与配置，授权后执行 cloud-smoke |
| Chrome 不可用 | 恢复宿主连接与正确账号，保留图片队列 |
| 剪映正在运行 | 保留已验证的新草稿，等待自然退出后注册 |

测试新环境请按[虚拟机清单](windows-vm-test.md)逐项记录。原始素材、私人草稿和凭据保持私有。
