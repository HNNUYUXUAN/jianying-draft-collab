---
name: jianying-draft-collab
description: Create or revise editable Jianying Pro drafts from real footage on Windows, with narration, subtitles, Chrome-generated image pages and original instrumental BGM. 将实拍素材制作或修订为剪映草稿、导入包与预览。
---
# 剪映草稿协作 / Jianying Draft Collaboration

用于实拍制片、已有草稿局部修订和最终归档。宿主 Codex 负责策划与检查，脚本负责可复现媒体处理；时长、风格和发布素材按用户任务确定。安装入口自包含，不要求接收者预装其他创作技能。

## 开工前

1. 识别新制片、草稿修订或导出后归档；读取源文件和当前保存版，确定工作区、最终归档与所需能力。沿用明确的信息和已有授权。
2. 按 [environment.md](references/environment.md) 定位运行根，运行只读 `env doctor` 和本任务 `env preflight`。安装、真实 smoke、云调用与宿主 Chrome 检查分别记录。先解决缺失依赖及原生适配，再进行正式云请求和批量制作。
3. 使用用户当前可用的剪映安装，按 [compatibility.md](references/compatibility.md) 在接收端隔离验证并缓存能力。版本号用于说明，文件指纹和真实读写决定可用性。不自动升级、降级、启动、关闭或激活用户剪映。

## 按任务读取

- **新视频**：[video-workflow.md](references/video-workflow.md)。取材、讲稿、时间线对应；使用 `video prepare/build/resume/validate` 制作与恢复。
- **配音字幕**：[audio.md](references/audio.md)。配置只读取运行根 `.env` 和进程环境，进程变量优先。复用有效音频，不重复提交成功或结果不确定的请求。
- **原创 BGM／专项配乐**：[bgm.md](references/bgm.md)。按画面与旁白密度写旋律、和声和段落，渲染器负责采样乐器、分轨与旁白避让。缺谱面先完成谱面；用户提供音频或选择无 BGM 时按其选择。
- **新增讲解图页**：[image-generation.md](references/image-generation.md)。全部走宿主 Chrome ChatGPT“创建图片”，整页文字、数字与图形一并生成。程序用于计算核验、真实证据抽帧、无语义改绘的适配编码和字幕轨。合成数值测试夹具明确标注测试身份。
- **已有草稿**：[draft.md](references/draft.md)。从最后保存的完整副本建立独立项目，保留用户编辑、未知字段与旧版本；不以旧制作计划覆盖用户时间线。
- **交付／扫尾**：[storage-and-handoff.md](references/storage-and-handoff.md)。核对归档、引用和源稳定性后，清理本任务临时副本，保留共享环境与凭据。

## 完成标准

默认交付普通目录中的导入包、可编辑草稿和完整预览；封面、发布文案、演示文稿等按任务添加。记录文件与素材检查、完整解码和原生读取证据；界面播放、用户导出和听感评价分别记录。最终链接指向已验证归档。

语言入口：[中文接入](references/zh-CN/start.md) / [English onboarding](references/en/start.md)。
Keep working editor versions and user edits intact, verify required capabilities
before production, and report observed evidence. The English README covers installation.
