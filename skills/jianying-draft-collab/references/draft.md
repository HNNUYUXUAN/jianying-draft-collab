# 后台草稿编排

使用用户已安装的剪映专业版和通过本机验证的后台适配器。通过文件、终端和隔离进程完成，不启动、激活或关闭用户剪映。开工运行 draft doctor；需要适配时按 [compatibility.md](compatibility.md) 完成隔离验收。

## 命令

以下命令通过 <runtime-root>/run.ps1 执行：

- draft doctor：只读本机安装、回执及缺口，不调用云服务。
- draft inventory [--app APP]：实际版本、工具指纹及选择依据。
- draft probe --output NEW_PRIVATE_DIR [--app APP] [--required read create ...]：生成夹具验收，不注册项目。
- draft list：用户项目目录与内容指纹。
- draft inspect SOURCE [--details]：原生节点和时间。
- draft create --plan PLAN --output NEW_STAGE --destination NEW_FINAL。
- draft edit SOURCE --plan PLAN --output NEW_STAGE --destination NEW_FINAL。
- draft validate NEW_STAGE：后台引擎读取，独立于界面播放。
- draft install-copy NEW_STAGE：应用自然退出后，将已验证的新项目注册到首页。

--app 指定安装目录，--projects 指定项目根；配置为 runtime-config.json 的 jianying.app/projects。正式操作检查所需能力及当前指纹，探测失败时不自动切换为未验证的旧 codec。

## 计划与原生行为

新建计划 schema_version=2；project={width,height,fps}；tracks 为 id/type(video/audio/text)/segments。片段含 id/start_us/duration_us；媒体另含 path/source_start_us/volume，文本另含 text/style。相对媒体路径按计划目录解析。初次生成速度 1 倍，由目标引擎核对画幅和时长。

修改计划使用 inspect 观察到的 track_id/segment_id。operations 支持更新与删除；更新字段为 text/start_us/duration_us/volume/style，样式字段为 size/bold/italic/color/alpha。素材替换使用已验收的 blueprint 资源引用，不重建用户时间线。

native_actions 只接受声明的 typed 命令：文本内容／样式、添加片段、移动／时长、音量及删除。动作不能覆盖目标引用或动作链参数。媒体使用 local:///<absolute-path>。动作依次作用于独立副本，记录进度和原生联动；失败副本保持 prepared，不注册。

原生节点可能以毫秒表达，提交微秒应为整数，按真实精度核对。缩短主轨可能联动字幕，需报告实际变化。避免为设置相同比例而调用会重设画幅的配置。

## 独立副本与安装

完整快照来源并核对哈希，保留未知文件、用户字幕和布局。原生新项目提供独立元数据身份，再接入来源时间线；临时项目名应唯一，避免应用缓存的同名工程冲突。全部读写使用新副本绝对引用。

引擎决定活跃 Timelines；根内容可能为兼容镜像。二者不同时先核对活跃内容，不用旧根覆盖最后保存的时间线。需要镜像同步时，只在隔离副本上以分别重读确认的结果为依据，保留同步前文件。

完成后核对请求值，并逐字段比较全部节点（含根与轨道）。返回成功但目标值未改变，或出现未声明的节点／字段变化时，保存 needs_native_review 回执，不注册。原生时间按毫秒读回，超过 1 ms 的帧量化差异也须复核，建议计划先按目标帧率对齐。

确有意允许联动时，计划使用 allowed_linked_changes 数组逐项声明 segment_id、精确 fields 和 reason，例如 fields 为 ["timeline.start.ms","timeline.end.ms"]；禁止通配字段。它不能免除请求值核对。变更超出该声明时仍需复核。验收通过后记录规范化节点 SHA，注册前重新读取，防止使用验收后已改变的 staging。来源与索引在复制、修改、验收各阶段检查稳定性。

注册前检查应用进程及索引快照；运行时保留待安装目录，等待自然退出。索引冲突只撤回与本次 staging 完全一致的新目录，不覆盖其他变化。分别记录文件检查、后台读取、注册和用户界面播放状态。

## 图页替换

列出直接图片段和已编入视频的静态页区间。新增图页按 [image-generation.md](image-generation.md) 使用 Chrome ChatGPT“创建图片”，记录原图、来源与 usage。图像来源审计通过后，在新版本副本更新引用；未改变的配音、字幕和实拍继续复用。
