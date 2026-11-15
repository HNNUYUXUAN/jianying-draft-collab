# 豆包配音和字幕

新制作使用 Agent Plan 专属 VOLC_AGENT_API_KEY，来自本机运行目录的 `.env`；进程同名变量优先。旧百炼响应保留历史离线对齐。
TTS：doubao-seed-tts-2.0，资源 seed-tts-2.0，HTTP https://openspeech.bytedance.com/api/v3/plan/tts/unidirectional；默认 zh_female_vv_uranus_bigtts。manifest 段内 voice_options 可覆盖 TTS_VOICE/TTS_SPEECH_RATE。
ASR：doubao-seed-asr-2.0，资源 volc.seedasr.sauc.duration，WebSocket wss://openspeech.bytedance.com/api/v3/plan/sauc/bigmodel_nostream。均以 X-Api-Key 鉴权；聊天模型 endpoint 不代替语音接口。
最终 WAV：48kHz单声道PCM16，ASR另转换16kHz。TTS2开启enable_subtitle，读取至最终20000000；原生词时间戳经全文和音频边界校验后复用，否则由asr识别。

入口 run.ps1：
- doctor：只读检查本地环境及独立配置，不发云请求。
- synthesize manifest.json NEW_OUTPUT
- synthesize manifest.json SAME_OUTPUT --resume
- assemble manifest.json NEW_OUTPUT：复用已有音频。
- asr OUTPUT/placement.json
- align OUTPUT/placement.json

manifest 的 segments 每段 id/text，assemble 另需 audio；支持 lead_ms/tail_ms/slot_ms/equivalences。相对音频按manifest定位；超出slot时报错，不截断不强行变速。
resume仅用于相同manifest与配置；新版本可复用文本及配置指纹绑定的完整TTS缓存。结果不确定保留pending，不自动重复提交。
ASR原响应先保存，再由align输出全文差异审计；equivalences只用于用户核对的映射。词内拆字标注within_word_interpolation，不冒充原生逐字。
输出总轨、分轨、placement、SRT与审计；导入分轨或总轨之一。字幕UTF-8 BOM、单行、无重叠。文件对齐不代表听审。
官方依据：https://docs.volcengine.com/docs/ark/agent-plan-personal-voice-model?lang=zh

## 视频字幕与音乐

新流程每行默认14字，按语义分句，显示层去句尾句读标点。source_text保留讲稿与TTS标点，display_text统一供SRT、预览和草稿。数学符号、小数和单位不清理；长分句拆分记录可读性复核。

配乐按 [bgm.md](bgm.md) 执行：原创乐谱 `score`、用户提供音频 `file`、明确不使用配乐 `none`。默认原创乐谱，缺少谱面返回 `needs_music_plan`，补充后恢复；沿用既有有效的旧配乐缓存。开工前检查所需音乐解释器、固定源码、FluidSynth、媒体工具和音源，并在收费配音前完成谱面校验与问题处理。

混音保留输入旁白 WAV 的字节，分别输出旁白、避让后的配乐与混音。教学讲解配置以 26 dB 的旁白／配乐活动窗口差距为目标，短停顿保持轻铺，较长观察空隙缓慢抬升；测量真峰值不超过 −1 dBTP，样本数不变。数值检查与用户听审分别记录。配乐变化复用未变化的 TTS 和画面缓存；已有用户草稿按新版本副本处理。
