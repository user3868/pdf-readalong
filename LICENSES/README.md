# 许可材料来源 / Provenance

这些文件只包含许可文本和声明，不包含 Python、FFmpeg、模型或一键包二进制。

| 文件 | 来源及用途 |
|---|---|
| 根目录 `LICENSE` | 原样复制现有合规材料 `PyMuPDF-AGPL-3.0.txt`，GNU AGPL 第 3 版全文；适用于本项目原创代码的 AGPL-3.0-only 许可声明，也供查阅 PyMuPDF 的 AGPL 分支 |
| `source-python-packages.txt` | 2026-10-02 从本仓库新建 `.venv` 的 29 个运行依赖提取，共 48 份 dist-info 许可/声明文件；每段保留包名、版本、原路径和原文件 SHA256；不包含 pip 打包工具 |
| `Python-3.12-PSF-LICENSE.txt` | 原样复制本机 CPython 3.12.10 的 `LICENSE.txt`，对应本轮源码验证运行时 |
| `Python-3.11-PSF-LICENSE.txt` | 原样复制现有便携包的 Python 3.11 合规文本，只用于该包运行时背景，不代表源码环境使用 Python 3.11 |
| `FFmpeg-GPLv3.txt` | 原样复制现有便携包合规材料中 GPLv3 全文；本机验证使用同版本 8.1.1 essentials 构建，但本仓库不分发其二进制 |
| `portable-components-20261001.txt` | 原样保留 2026-10-01 的便携包组件清单及未核清事项；它是构建时快照，不是本仓库依赖锁定文件，也不构成合规完成声明 |

原材料只读来源：便携包构建目录中的 `LICENSES/`（构建机本地路径，不随本仓库分发）。本轮没有读取或复制其中的应用源码，没有改动该目录或其上级打包目录。

`portable-components-20261001.txt` 末尾把源码权利主要归于第 13 条的说明不完整：二进制分发的对应源码要求见 AGPL 第 6 条；修改版的远程网络交互要求见第 13 条。本仓库以 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) 的区分为准，并原样保留旧清单供追溯。

这些文本不替代完整对应源码、构建信息、安装信息或真实可用的源码下载入口。发布前必须完成 [发布检查清单](../发布检查清单.md) 中的阻断项。
