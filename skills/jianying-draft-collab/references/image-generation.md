# 视频图片生成

本技能所有新增独立成图均通过 **Chrome ChatGPT“创建图片”** 生成。范围包括教材定位、文字讲解、流程、数据表、公式计算、曲线/柱图、原理、总结、过渡和横竖封面；整页文字、数字、表格、箭头与图形一并生成。内容简单或需要精确数据时仍使用此渠道。维护模板为 assets/video-image-prompt.md。

## 成图与取材边界

程序负责计算核验、提示词和资产清单、哈希、真实素材抽帧/ROI、原图等比适配、音视频编码及字幕。独立讲解页面不使用PIL、HTML/CSS、SVG、绘图库或演示文稿形状排版成图，也不在生成原图上用程序改字、改数、补表格或重画图形。需要修订某页时，更新该页完整提示词，通过“创建图片”生成新候选。

原始实拍、原始软件录屏、原始照片和真实截图属于取材；可原样引用、截取真实帧和作不改变信息的裁切放大。把素材重新组织为带文字、公式、数据或标注的独立讲解页时，该完整页面进入创建图片队列。正常旁白字幕使用可编辑文本轨；不把讲解页拆成字幕/形状轨来绕过整页成图规则。

## 系列策划与生成

先锁定页面清单、讲稿对应关系、经计算核验的唯一文字和全部数字。系列图共用画幅、色板、字体气质、信息层级、边距和字幕安全区；各页提示词自包含，明确页面任务和本页完整可见内容。数据表和计算图逐项写出核定值，科学图明确原理示意身份，实际软件证据保持真实身份。

默认视频内页面16:9、白底深蓝青绿、1080p可读，底部留字幕安全区；横竖封面默认4:3及3:4，分别构图。文字密度按阅读时长安排，可减少单页信息或增加图页；计算原始数据、单位和结论保持一致。用户仅要求视频内整图系列时交付图片目录，不引入PPTX封装或相关运行时。

Chrome由单一控制者使用当前宿主公开网页接口：发现并绑定连接、命名任务、每图新对话、选择“创建图片”或明确要求创建图片，提交后观察是否进入真实生成状态；完成后打开原图查看器并下载。未提交草稿与未决请求分开记录；点击无效先查看状态。下载事件不受支持时核对正常下载目录中的新文件、字节及尺寸。保留下载原图，不以预览截图替代原文件，不通过隐藏端点、Cookie或其他生图服务补齐页面。

## 验收与来源清单

逐字核对中文、公式、正负号、小数、单位、图表数值、箭头关系和事实身份；在最终视频尺寸检查可读性与字幕遮挡。原图保持字节，等比适配放在视频渲染阶段。每张图记录image_id、项目/系列ID、完整提示词路径/SHA、渠道和模式、网页会话、实际提交/完成/下载时刻、下载原图路径/SHA/尺寸、QA、采纳状态及使用位置。真实时刻缺失时记录缺失，不补造时间。

production-plan.json新增visual_asset_manifest，指向项目根相对的JSON文件。该文件version=1，assets为采纳资产数组，source_reviews覆盖全部被时间线引用的视频源。通过 video audit-images --project PROJECT 做只读本地审核；build/resume在收费合成前执行同一审核，缺失或不一致返回needs_image_audit。历史video validate不要求补写来源清单。

每个生成资产包含：image_id、lane=web_chatgpt_chrome、mode=create_image、conversation_url、prompt={path,sha256}、original={path,sha256}、qa={facts,text,visual:passed}、usage。prompt与original路径相对项目根；plan.images中采纳图SHA须与下载原图SHA一致。

usage直接图片段用{segment_id,type:image}。已拼接进视频的静态页用{segment_id,type:derived_video_static,source_id,start_us,end_us}，时间是源视频内的微秒区间。封面用{type:cover,file:{path,sha256}}。source_reviews对真实原拍/录屏记录{kind:capture}；对衍生视频记录{kind:derived_video,static_ranges:[{image_id,start_us,end_us}]}，纯实拍衍生视频可为空数组。static_ranges记录源视频内整段静态页；usage按每个segment实际消费源区间的交集记录，完全未用到的页不要求usage，同源被多段使用时逐segment覆盖，避免旧静态页藏在source_id视频中。

真实证据截图记录kind=evidence_capture、lane=source_evidence、mode=capture，并保留original、QA与usage。视频帧用evidence={source_id,source_sha256,at_us}；独立PNG/JPEG等原始截图用evidence={source_file:{path,sha256}}，无需视频时间戳，采纳文件保留原字节。独立截图若先作无损裁切，附crop_box=[left,top,right,bottom]，审核比对源图裁切后的尺寸与像素；缩放留在视频渲染阶段。它表示原始内容的真实截取，不表示重新排版的讲解图。来源审核核验本地文件、SHA、声明和覆盖范围；Chrome控制者另以网页状态确认实际生成与下载，不能把渠道字符串当作网页行为证明。

队列状态planned→submitted→generated→downloaded→verified→adopted；失败和pending单列。重连先核队列、会话与已下载结果；不重复提交未决请求。单页问题局部修订，其他已采纳页SHA保持不变。网页能力故障时保留待生图队列，继续独立音频、计算和文件任务，不切换渠道或程序成图。

派生视频尚未编码时，可先运行video audit-images --project PROJECT --images-only：完整检查图像来源和声明覆盖，仅延后derived_video文件的存在/SHA检查，返回images_ready并列出延后源。编码完成后更新source SHA，再运行不带该参数的完整审核。build/resume始终执行完整审核，images_ready不代表视频已验收。
