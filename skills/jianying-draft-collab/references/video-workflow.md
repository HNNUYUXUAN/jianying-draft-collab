# 实拍制片

先按 [storage-and-handoff.md](storage-and-handoff.md) 确定工作区和最终归档。下文 `run.ps1` 指已安装运行根中的绝对入口，`PROJECT` 是本次项目目录。

## 开工与策划

1. 明确用户目标、输入、时长及交付；已有草稿转入副本修订流程。运行 `env preflight --project PROJECT` 核验本任务需要的本地、音乐和原生能力；缺项先按环境与兼容参考解决。需要云和图片时分别核验服务及当前 Chrome 会话。
2. `video prepare --project NEW --inputs FILE1 FILE2` 保留原件并记录 source_id、SHA、视频 PTS 和总览帧。动作窗口密集抽帧，图表用真实原分辨率 ROI；总览未采到动作不能据此判断原片缺失。
3. Agent 按真实证据写讲稿与 `production-plan.json`。计划 version=1、fps 默认60，draft_name为新项目名；segments每项包含id、frames、text，以及source_id/source_start_us/speed或image_id。用户指定时长优先；未指定时根据素材与讲解密度安排。可显式提供 duration_range_seconds。观察区间安排真实观察任务，不能以长定格填充内容。
4. 视觉分析使用专属 Agent Plan 配置；调用前核对本任务授权、图片与问题范围。可复用绑定相同源 SHA 与问题的结果；结果不确定先查回执，不重复发出请求。

## 图片、音乐与制作

- 所有新增图页按 [image-generation.md](image-generation.md) 建立系列，通过 Chrome ChatGPT“创建图片”。`images` 记录 path、sha256、qa；`visual_asset_manifest` 记录提示词、原图、会话、用途及衍生视频内静态页。先执行 `video audit-images --project PROJECT`。
- `music` 按 [bgm.md](bgm.md) 选择原创乐谱、用户音频或无配乐。原创模式先完成与时间线匹配的谱面并校验所需音源。缺失时保持 `needs_music_plan`，不使用固定鼓点代替。
- `video build --project PROJECT` 在正式请求前检查任务能力及输入审核，再完成语音、字幕、音乐、无声分段视频、完整预览和原生草稿。语音 slot 来自 frames/fps；超长语音明确报告，不截断或强行变速。
- 字幕默认单行、按语义处理句尾标点，原文保留。`caption_phrases` 可提供完整原文的语义切片，拼接必须与讲稿一致；数学负号、小数及单位不清理。阅读性警告由 Agent 检查后恢复。

## 恢复与交付

`video resume --project PROJECT` 复用一致计划下的语音、图片、音乐和分段渲染；缓存核对输入及工具指纹。修改内容后保留原版本。有效旧项目可以验证和复用既有配乐；新增或明确更换配乐时采用新模式。

`video validate --project PROJECT` 检查源 SHA、素材帧数、音频样本数、字幕和原生读取。再完整解码预览，查看关键动作、图表与字幕。新草稿安装采用 `draft install-copy`；剪映运行时保留待安装副本，等待自然退出。后台通过与用户界面播放分别记录。

默认交付 `delivery/剪映导入包`、`delivery/剪映草稿`、`delivery/完整预览.mp4`。旁白与音乐分轨、最终混音分别保存；导入时选分轨或混音之一。最终链接指向完整归档目录。

视频输出统一1920×1080、等比适配和BT.709。仅有明确BT.2020非恒定亮度、limited-range、HLG标签的素材执行既有色调映射；SDR和图片不套用HLG转换。渲染配置进入缓存身份。
