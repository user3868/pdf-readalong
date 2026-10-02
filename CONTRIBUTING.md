# 参与贡献 / Contributing

欢迎改进 PDF 文本提取、跨行高亮、字幕可读性和 Windows 源码安装体验。项目原创代码按 **AGPL-3.0-only** 发布；贡献采用相同许可，第三方代码保留原有许可和版权声明。

提交问题时请说明 Windows / Python / FFmpeg 版本、复现步骤、报错，以及能公开的最小 PDF。不要上传学生资料、私人讲义、凭据、日志中的个人信息或无权公开的文件。

提交修改时请说明触发问题、修改后的行为和实际验证结果。画面相关修改应附修改前后的截图，检查跨行句、换页和字幕。模型、运行时、一键包、音视频和 `jobs/` 产物不进 Git。新增依赖应同时更新 `requirements.txt` 和 [依赖许可说明](THIRD_PARTY_NOTICES.md)。

仓库内的录屏、测量和历史脚本是开发资料，部分仍使用作者本机路径或额外依赖；运行前先检查其路径，不要把它们当作快速开始入口。

**English:** Please include a minimal reproducible example, environment versions, and validation evidence. Contributions use AGPL-3.0-only. Preserve third-party notices; do not submit private PDFs, credentials, generated media, model weights, or paid distribution bundles.
