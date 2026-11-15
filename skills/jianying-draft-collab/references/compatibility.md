# 接收端剪映兼容与本机适配

使用接收者当前安装的剪映专业版。先复用本机已验证路径；安装文件变化时，由 Codex 在该设备分析并验证接口。应用保持原位，不自动升级、降级、下载旧版或修改安装文件。

## 已知路径与能力状态

发行包保留剪映 11.7.0.14652 的 vebun、CLI、客户端 DLL 和 videoeditor 四项 SHA，作为 vebun → lyra-cli 适配器的快速识别依据。它不把其他版本判为永久不支持，也不代替接收端验收。

draft doctor 只读输出 ready、needs_probe、needs_local_adapter 或 failed，列出任务要求、已验证能力和缺口。draft inventory 记录实际版本、文件指纹和选择依据。安装选择顺序为显式 --app、runtime-config.json 的 jianying.app、上次验证所用安装、当前运行实例、唯一已验证／已知安装、唯一候选；多个候选需要指定，避免随最高版本目录切换。

缓存位于运行目录 state/native-adapters，可用 jianying.state_root 配置。jianying.projects 指定项目根，未设置时采用 Windows 当前用户目录。安装位置、原生工具文件、适配器源码或 Python 工具变化会使回执失效。

## 隔离验收

    & <runtime-root>/run.ps1 draft probe --output <new-private-directory>
    & <runtime-root>/run.ps1 draft probe --output <another-new-directory> --app <installed-app-directory> --required read create independent_copy blueprint

探测先保存安装内 CLI 帮助，再用生成的校准图片、WAV 和文本建立四轨外部草稿，创建独立身份副本，修改并另起进程重读。核对文字、样式、音量、时间、删除、素材替换、节点 ID、源副本稳定性及用户项目索引。不读取用户作品，不注册项目，不控制剪映窗口。每次输出目录和原生临时项目名均独立。

读取、新建、文本、样式、音量、时间、素材替换、独立副本及加密内容读取分别记录。实际保存产生加密内容并成功重读，encrypted_read 才通过。明文读回、退出码、Python 可导入和 Key 存在不能代替这些证据。生产命令按实际操作检查能力，读取通过不能授予任意写入。

## 新版本在本机收敛

标准探测失败后，Codex 读取私有帮助、结果与错误，形成有证据的候选：

1. 分析已安装应用自身的正常宿主、CLI、帮助树、可读配置和日志，确认参数及返回结构。
2. 接口形状兼容时复用内置适配器；参数、宿主或规范化输出改变时，编写本机适配器。
3. DLL 路线仅在导出符号与 ABI 有具体证据时作为隔离候选。相同符号名不能证明调用约定或格式兼容。codec 至少完成 decode→encode→decode 语义回环，并由应用原生解析器读取保存结果；证据不足时保持该能力未验证。

本机适配器放在 state/native-adapters/local/<adapter-name>/，仅用于 Codex 在本机编写、审阅的代码。项目、下载材料或他人导出的配置不能直接当作可执行适配器。

描述文件：

    {"id":"installed-version-local","kind":"local_python","module":"adapter.py"}

模块入口为 execute(app: Path, args: list[str], *, cwd, timeout) -> dict。参数沿用本技能的规范化命令语义；draft extract 返回 {"json_result": [stdraft nodes...]}，帮助返回 {"help_text":"..."}。模块按已查明的安装接口转换和本地调用，遵守超时、私有目录和应用保护约束。模块在独立 Python 进程运行，主进程不加载该代码；描述、模块和应用指纹纳入回执。

    & <runtime-root>/run.ps1 draft probe --output <new-private-directory> --adapter <state-root>/local/<adapter-name>/adapter.json

机械化探测验证已有接口形状；分析变化、解释错误、编写和审阅适配器由 Codex 完成。不假设通用解密算法，不注入进程，不修改应用，不关闭宿主校验。应用自身规范化提取也可构成已验证的加密草稿读取路径，无须导出通用解密算法。

## 收敛边界

一轮安装清点，最多三条有证据的候选；每条初测失败后，最多针对明确原因修正复测一次。帮助进程 15 秒，原生读写进程 60 秒，一次探测总计最多 30 分钟。相同宿主／权限拒绝不重复撞接口。超过边界，保留失败阶段和已通过能力，停止该能力；任务所需能力未全部通过前，保持预检状态，不先提交收费制作请求。

通过后缓存于接收者本机，不要求维护者逐版本发布白名单。新版本是否可用取决于实际验证；安装、本机测试、同机重定位、干净系统和应用内播放分别报告。
