# 依赖许可与分发义务 / Third-party notices

本项目原创代码按 **AGPL-3.0-only** 提供，许可全文见根目录 [LICENSE](LICENSE)。第三方组件仍按其自身许可提供；该声明不把第三方代码重新许可，也不声称拥有其版权。代码的具体版权署名由权利人在发布前确认。

## PyMuPDF / MuPDF：必须提供对应源码

PyMuPDF / MuPDF 提供 AGPL 与 Artifex 商业双许可，本项目选择 AGPL 分支，未声称取得商业许可。[上游许可说明](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright)。

发布受覆盖程序时，保留版权、许可及修改声明；发布二进制/便携包时，按照 AGPL 第 6 条提供匹配分发版本的完整对应源码。源码范围包括适用的应用源码、依赖源码及生成、安装、运行、修改所需脚本；不能只用旧提交、上游首页链接或一份许可文本代替。修改版支持远程网络交互时，第 13 条还要求显著向远程用户提供该版本对应源码的获取机会。范围和条件以 [AGPL 原文第 1、4–6、13 条](https://www.gnu.org/licenses/agpl-3.0.html) 为准。

推荐采用第 6(d) 条的网络交付方式：在每个二进制下载位置清楚标注匹配版本的源码归档位置，提供同等获取能力、无额外费用，并持续保证可用。公开源码仓库可以承载应用源码，但不能自动证明其提交与实际付费包一致，也不自动补足第三方二进制的对应源码。

当前源码目录提供此版本的运行代码及锁定依赖；尚未创建远程 URL，尚未做付费包逐文件核对。背景中的本地语音实现 `tts_local.py` 不在当前仓库。若它在受覆盖分发版本内，就必须纳入该版本对应源码交付，不能以付费为由排除。UI 目前也没有源码链接，本轮未修改 UI；见 [发布阻断项](发布检查清单.md)。

AGPL 允许收费；它同时保留接收者的修改和再分发权利。仓库可不附便携运行时和安装包，不能据此限制这些权利或隐匿受覆盖源码。导出音视频/PDF 不因运行 AGPL 程序就一概成为 AGPL 作品，仍需处理输入内容及输出内容的实际权利。

## 源码运行环境：实装依赖清单

下表是 2026-10-02 在本仓库新建 CPython 3.12.10 虚拟环境中安装的 **29 个运行依赖**（含传递依赖），对应 `requirements.txt`。许可字段来自各 wheel 的元数据及许可文件，不是对每个嵌入子组件的独立法律结论。安装工具 pip 不列为应用运行依赖。

| 包 | 已验证版本 | 上游声明许可 |
|---|---|---|
| aiohappyeyeballs | 2.7.1 | PSF-2.0 |
| aiohttp | 3.14.3 | Apache-2.0 AND MIT |
| aiosignal | 1.4.0 | Apache 2.0 |
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| attrs | 26.1.0 | MIT |
| certifi | 2026.7.22 | MPL-2.0 |
| click | 8.5.0 | BSD-3-Clause |
| edge-tts | 7.2.8 | LGPLv3；srt_composer.py 单文件 MIT |
| fastapi | 0.142.2 | MIT |
| frozenlist | 1.8.0 | Apache-2.0 |
| h11 | 0.16.0 | MIT |
| idna | 3.20 | BSD-3-Clause |
| multidict | 6.9.1 | Apache License 2.0 |
| numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| opentelemetry-api | 1.45.0 | Apache-2.0 |
| pillow | 12.3.0 | MIT-CMU |
| propcache | 0.5.4 | Apache-2.0 |
| pydantic | 2.13.5 | MIT |
| pydantic_core | 2.46.5 | MIT |
| pymupdf | 1.28.2 | AGPL-3.0（本项目选择）/ Artifex 商业双许可 |
| python-multipart | 0.0.32 | Apache-2.0 |
| starlette | 1.7.0 | BSD-3-Clause |
| tabulate | 0.10.0 | MIT |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| uvicorn | 0.54.0 | BSD-3-Clause |
| yarl | 1.25.1 | Apache-2.0 |

已保留 48 份 dist-info 许可/声明原文于 [source-python-packages.txt](LICENSES/source-python-packages.txt)，每段标明包名、版本、原始路径与原文件 SHA256。PyMuPDF wheel 的 COPYING 只是指针，根目录 `LICENSE` 补入 AGPL 全文。NumPy 等多许可组件须按原文保留各部分声明；edge-tts 的 `srt_composer.py` 单文件使用 MIT，其余使用 LGPLv3。若重新分发这些依赖的二进制，还须按其许可履行源码等适用义务，不能只保留这张表。

CPython 3.12.10 适用其 PSF 及随附历史许可，完整文本见 [Python-3.12-PSF-LICENSE.txt](LICENSES/Python-3.12-PSF-LICENSE.txt)。本仓库只提供安装说明，没有分发该 Python 二进制。

## FFmpeg：按具体构建判断

本机运行验证使用 FFmpeg / ffprobe **8.1.1 essentials build（gyan.dev）**。已有便携包清单记录该构建启用 `--enable-gpl --enable-version3 --enable-static`，并包含 x264/x265 等；清单将其识别为 GPL-3.0-or-later，不能笼统写成“FFmpeg 都是 LGPL”。GPL 全文见 [FFmpeg-GPLv3.txt](LICENSES/FFmpeg-GPLv3.txt)。[FFmpeg 官方许可说明](https://ffmpeg.org/legal.html)。

应用通过子进程调用 FFmpeg。本仓库不包含 FFmpeg 二进制；若付费包另分发该静态构建，其 FFmpeg 及所含库的对应源码、配置/补丁、必要构建资料和声明仍要按具体构建履行，普通上游下载首页不证明是同一个二进制的对应源码。

## 便携包清单是历史证据，仍有未闭环事项

[portable-components-20261001.txt](LICENSES/portable-components-20261001.txt) 原样来自已有合规目录：Python 3.11.15、PyMuPDF 1.28.2、FFmpeg 8.1.1，以及 36 个 Python 包（包含打包工具和录屏组件）。它不是本轮源码环境的清单；本轮 NumPy 2.5.3 / FastAPI 0.142.2 / Uvicorn 0.54.0 等版本与该快照不同。两种环境的许可证和对应源码必须分别追溯。

旧清单将源码权利主要归于第 13 条，表述不完整：第 6 条处理非源码形式的分发，第 13 条处理修改版的远程网络交互。原材料说明有 35 个包的许可文件目录，而组件元数据计数为 36；需要在最终构建中查清差异。

已有材料明确尚未逐项核对 NumPy 各子许可、pip/setuptools vendor、部分 C vendor，以及 FFmpeg 静态第三方库声明。此仓库保留上述状态，不将“已有合规材料”表述为“全部合规完成”。源码获取地址、二进制/源码版本映射及可复现构建仍须补全。

## 模型、服务、输入和字体

当前源码只接入在线 edge-tts；服务条款和文本发送行为需要另行核对，开源库许可不等于语音服务授权。本地模式约 2.4GB 模型的具体来源和权重许可未提供，未下载或分发；不得推断模型也采用 AGPL。

样例 PDF 有项目内生成脚本，但作者仍须确认公开权利。用户应自行取得讲义内容的授权。程序读取 Windows 已安装的微软雅黑字体，本仓库没有分发字体；其他分发版本不得未经授权复制 Windows 字体。

以上是发布材料和已识别义务的记录；当前商业包分发仍有阻断项，详见 [发布检查清单](发布检查清单.md)。许可文件来源及适用环境见 [LICENSES/README.md](LICENSES/README.md)。
