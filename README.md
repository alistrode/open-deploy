# OpenDeploy：两套完整交付

本仓库只保留首次成功模拟原版和最新完整交付。原仓库 `trlstdin/rororororo` 及其业务分支未修改。

| 交付 | 位置 | 内容 |
| --- | --- | --- |
| 首次成功模拟原版 | [release/simulation-used-20261025](release/simulation-used-20261025/) | 历史提交 `65f0afc5b5754e2cdfc6adc528a754718963374c` 的原 411 个文件：实际使用的运行包、原加密 ISO、原 32 GiB VDI、中文离线资源、还原脚本。约 6.24 GiB。 |
| 最新完整交付 | [release/latest-complete](release/latest-complete/) | 10 月 30 日最新应用、源码和修复，加原有完整运行依赖、PXVIRT ISO、VirtIO ISO、中文离线资源及引导资源。一份完整 ZIP，共 145 个分片，约 2.26 GiB。 |

首次版的 Runtime 明确是 `OpenDeploy-Used-PXVIRTOnly-Windows-Full-20261025.zip`，未用 10 月 27 日更新版冒充。原 411 个文件已逐一核对 Git 对象；原运行包已通过完整 ZIP CRC 核验。

最新交付于 2026-11-01 重新整理，以原分支提交 `226908ca533310e39c50c7841efa6702a78c59b7` 的 67 MB 完整应用包为准，应用标记 `99944c1343e1976d7d719bb1213b38a3bcf5b051`。应用文件保持原样；补齐的依赖与固定版本镜像取自 `OpenDeploy-Windows-Full-20261027.zip`，另加入原中文离线 ZIP。它不是原仓库曾发布的同名全资源包，也未经过新一轮装机验收。

两套各自包含还原入口；先完整取得相应目录的所有分片。首次版使用原 `Restore-UsedDelivery.cmd`，最新交付使用 `Restore-Latest.cmd`。还原不启动装机。最新镜像是原完整包的固定版本，不是实体机器 E 盘的逐字节备份。按原要求不包含 Tiny10 ISO。

私密连接身份与原加密介质的解密密钥仍在原私密位置，没有放入公开仓库。公开仓库不包含 `private-recovery/pxvirt-original-identity.zip`。源码与历史现场说明保留在根目录 `source/`、`docs/`，当前包索引以本文件和 `docs/DELIVERY.md` 为准。
