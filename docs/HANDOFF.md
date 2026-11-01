# OpenDeploy 当前交接

更新时间：2026-10-29 20:26（北京时间）。仓库 `trlstdin/rororororo`；长期分支 `projects/open-deploy`。本文件是唯一当前状态入口，历史从 Git 查询。

## 2026-10-30 虚拟机完整包更新

新增 VirtualBox 克隆机入口 START-VM.cmd，显式提供源 ISO、目标盘及介质盘序列号，默认只做盘。
补齐模拟脚本的根目录依赖及显式 ISO 构建参数。使用条件见 DELIVERY.md。
每次从 Win10 母版完整克隆，母版不参与安装。此次更新不替换任何远端现场，不代表真实虚拟机装机完成。
下文保留原实体机现场记录，不能用于克隆机选盘或身份配置。

## 当前结论与本轮授权

用户本轮要求依据虚拟机成功记录与真机交接检查远端，尤其关注日志覆盖缺口；介质损坏时重新做盘。随后询问 F 盘是否还能用，并明确不要提问。此前“只写文档”的范围已经被本轮明确的检查、备份和重做介质授权取代；本轮没有启动实体安装或重启电脑。

**约 2GB 的 General UDisk 目前不能可靠充当安装盘。两次整盘写入均报告完成，随后不经过系统缓存的回读都发现内容不一致。没有重做成功或实体启动成功的结论。** 小块即时写读能成功，不等于整盘健康，也不能凭此把问题定性为彻底物理报废。当前应更换安装 U 盘，不应继续用它承载唯一日志或无人值守安装。

安装目标仍是指定的内置 Micron，原授权范围为清空该盘 C/D、保留外置 E 的其他资料。**Windows 仍在线；尚无 PXVIRT 安装完成、正常首启或原远控接回的证据。** 本轮写入仅针对已识别的小 U 盘；E 上只新增项目备份和恢复资料。

用户无视觉，依靠脑机接口工作。不要把图片、菜单颜色、盲选方向键或盯屏判断交给用户。维护、下载、配置衔接和日志读取由 AI 完成；需要真实本地操作时，说明最少且确定的动作，不保证 Windows 远控能操作固件界面。

## 这次实际检查和处理结果

### 目标介质与故障证据

现场仍为 `LAPTOP-MCMQHDN4`，远控实际账户 `NT AUTHORITY\SYSTEM`。设备为 Windows 磁盘 2、General UDisk、USB、2013265920 字节，非启动盘、非系统盘。其序列号字段不可用，因此本轮同时绑定磁盘号、型号、完整容量和实际 PNP 身份，不以历史 F: 盘符选盘。

```text
USBSTOR\DISK&VEN_GENERAL&PROD_UDISK&REV_5.00\6&2E4EBCDF&0&_&0
```

开始时 F: 没有可识别的文件系统，原始扇区 0 和 1MiB 位置均为全 FF，缺少 55AA 与 FAT32 标记；盘中仍有非 FF 数据。这个事实解释了卷不可读，但本身不能区分内容损坏和硬件失效。

远端还有交接未覆盖的恢复点 `usb-recovery\20261029T114541Z`：19:45—19:47 完成了整盘压缩读取，随后曾仅重启 USB 设备节点，并于 19:51 提取部分文件。本轮没有把这当作成功修盘。

本轮先完整解压读取该压缩镜像并确认覆盖 2013265920 字节，再把它、身份、现场文件和恢复点复制到 E 的独立备份目录，之后才清除小 U 盘分区并进行写入性检查。

| 实际操作 | 结果 |
| --- | --- |
| 第一轮：4MiB 块，位置相关内容写满全盘，WriteThrough + NO_BUFFERING；关闭并重新打开物理设备回读 | 写入 2013265920 字节；首个不一致字节为 2097152；失败 |
| 五处 4KiB 小块即时写读：盘头、2MiB、32MiB、盘中与盘尾 | 五处均相同；只证明这些即时小块操作，不证明容量、长期保持或整盘可用 |
| 第二轮：1MiB 块重新写满全盘，以同样的不经过缓存方式回读 | 写入 2013265920 字节；已连续核对 18874368 字节，随后在该偏移出现不一致；失败 |
| 恢复 FAT32/启动文件 | 因整盘回读未通过，没有执行，不标为重做成功 |
| 电脑重启、固件修改、实体安装、E 上 ISO 替换 | 均未执行 |

不能把这次异常仅归因于 4MiB 大块传输；改成 1MiB 后仍失败。也没有进一步证实损坏位于闪存、控制器、USB 通路或驱动中的哪一层。**能识别、能报告写入完成、能通过几个小块探测，均不能替代完整回读。**

这块小 U 盘当前含本轮检查写入的模式数据，不是可启动安装介质，不应再建议直接 F12 启动。旧内容已保存到 E 的原始镜像及提取目录；没有丢弃原始备份。

### 当前恢复材料

所有本轮材料根目录：

`E:\xxm\beifen\OpenDeploy\usb-rebuild-20261029`

| 相对位置 | 内容 |
| --- | --- |
| `before\usb-recovery\20261029T114541Z\udisk-before.img.gz` | 原盘完整压缩镜像，原文件 62276108 字节，本轮已完整解压读取 |
| `before\usb-tree`、`before\install-logging`、`before\connection-identity`、`before\ai-private` | 制作材料、v2 恢复点、原身份完整副本 |
| `before\application-source-pve`、`before\boot-assets`、`before\split-boot` | 现场实际源码、原固定引导布局和分段准备记录 |
| `staged-usb` | 65 文件、55518891 字节的完整待写介质树，含原连接身份和 v2；没有写回成可用盘 |
| `prepared.json` | 原始备份检查、v2 逐文件对应与原身份保持的回执 |
| `integrity.json`、`integrity.stdout.log`、`integrity.stderr.log` | 4MiB 整盘写读失败记录 |
| `probe.json` | 五处 4KiB 即时探测结果 |
| `integrity-1m.json`、`integrity-1m.stdout.log`、`integrity-1m.stderr.log` | 1MiB 整盘写读失败记录 |
| `result.json`、`DO-NOT-USE-THIS-USB.txt` | 本轮实际结论；禁止把该介质当作已准备好 |

这些目录包含私钥、安装口令和原连接资料，不输出其内容到聊天。不要以“清理凭据”为由删除原 `connection-private.json`。

## 虚拟机成功记录能说明什么

首次模拟实际路线为 Windows 宿主机 → VirtualBox 内 PXVIRT → Tiny10，前段经过产品制作介质、安装 PXVIRT 并接回连接；后段曾完成中文桌面。完整原成品、依赖与加密 ISO/32GiB VDI 见 `release/simulation-used-20261025/`，源码索引见 `.agents/skills/opendeploy-recovery/SKILL.md`。

模拟中的嵌套 EPT、NAT 地址、vmbr110、固定 VM110 与 Tiny10 阶段恢复均有专门适用条件，不能作为实体电脑的默认修复。本轮没有改变虚拟机、网桥、硬件虚拟化或 Tiny10。模拟成功不能证明当前 2GB 实体介质可靠，也不能代替真实内置盘安装与首启验收。

## 真机既有安装故障与日志覆盖

此前确实进入过安装环境：日志证明 RAM 中 ISO 已拼接、挂载并切换根目录。旧日志包装随后返回 `rc=1`；不能再说“从未进入安装环境”。另一方面，C/D 仍存在，没有证据表明安装完成。

### 已定位的旧缺陷

1. 旧初始 `/init` 包含 `(while :; do sync; sleep 1; done) &`。切换根目录后，旧环境循环找不到 sync/sleep，不再等待，形成持续刷屏。等待不会推进安装。
2. 旧启动包装在原安装脚本尚未挂载 `/proc`、`/sys`、`/run`、`/dev/pts` 前调用 `script -q -f -e -c /sbin/unconfigured.sh`，并把要求 PID 1 的脚本变成子进程。其错误输出被送到 tty1，没有生成完整 `installer.console.log`，所以只有 rc=1，缺少包装自己的真实报错。

“伪终端提前依赖、PID 1 被破坏”有代码依据；没有原始 `script` 错误文本，不能说 rc=1 的所有原因都已实证排除。

### v2 的实际状态

19:13 写过的 v2 来自 C 盘作业恢复点 `install-logging\20261029T111315Z`。本轮从该恢复点和原盘提取文件取回完整源码、8853 字节覆盖层和实际 GRUB 配置，解析覆盖层并逐文件确认与 v2 恢复点相同，执行位存在，原刷屏循环已移除。

源码与原覆盖层已补到 `source/pve/recovery/physical-20261029/logging-v2/`。本轮只是保全、对应和组装这些实际文件，没有把仓库旧应用包覆盖到现场，也没有修改 ISO。

v2 撤掉 `script` 包装，以 exec 保持原安装启动链和 PID 1，切换根目录前结束旧日志进程，采集输出、命令跟踪、关键阶段、失败命令/行号/退出码，并在错误后停留。正常路径保留原重启流程。预期目录为 U 盘根的 `OpenDeploy-install-<时间>`，文件为：

- `boot.console.log`、`kernel.initial.log`、`kernel.stream.log`：早期驱动、RAM 拼接与切换前输出。
- `installer.console.log`、`installer.trace.log`：真实安装启动后的 stdout/stderr 和 Bash 命令位置。
- `stages.log`、`failure.log`：实际 PID、自动安装器/post-hook 返回与具体失败。
- `kernel.latest.log`、`kernel.failure.log`、`installer-files`：内核及安装器运行日志副本。

**v2 仍没有完成实体启动验收。** 本轮没有产生新的真实 v2 安装日志。早期尚未建立日志卷、硬断电、介质失联或内核致命故障仍可能留不下记录；尤其当前 U 盘自身不可靠，不能把“脚本覆盖错误出口”当成日志一定持久保存。必须先换可靠介质。

## 硬件与不可混淆的安装范围

- Acer Nitro AN515-58，约 16GB 内存；历史 BIOS Insyde V2.21。F2 是设置键、F12 是一次性菜单键；历史 Secure Boot 为关闭，不当作实时读数。
- 内置 Micron_3400_MTFDKBA512TFH，512110190592 字节，Windows 磁盘 0，当前 C/D 均在此盘。
- **唯一正确的安装筛选为 `ID_SERIAL_SHORT = "222339E164B9"`。** Linux 实机枚举所得；不得恢复废弃的 `ID_WWN=eui.00a0750139e164b9`，后者曾导致 filter did not match any device。
- 外置约 500GB JVVMEMII 为 E:，NTFS 卷 UUID `888A209C8A208930`。保留其余资料，它不是安装目标。
- 小 General UDisk 为 2013265920 字节，原 F:/OD_PXVIRT/FAT32；本轮状态如前，不再使用旧盘符或卷标推断可用。

当前实际 ISO 为 `E:\OpenDeploy-PXVIRT.iso`，2318270464 字节；RAM 分段载荷为 `E:\OpenDeploy-PXVIRT.boot.cpio`，2318284884 字节。ISO 内基础用户空间为 Debian 12（bookworm），并带 PXVIRT 安装层；启动内核曾为 6.6.0-10-openeuler。它们属于不同层次，不表示改装普通 Debian/Ubuntu；最终 PXVIRT 产品版本未现场验收。

原介质链从 E 的 ISO 读取内核与基础 initrd，再加载 E 的三段 CPIO，最后加载 U 盘 v2 覆盖层。ISO 三段为 1073741824、1073741824、170786816 字节，在 RAM 拼成 `/pxvirt.iso` 后删除分段。不能用旧单个 newc 大文件方案覆盖它。

## 现场路径与接入

Windows 程序：`C:\Windows\Temp\OpenDeploy-HardDisk-USB\OpenDeploy`。

作业：`C:\Windows\System32\config\systemprofile\AppData\Local\OpenDeploy\PXVIRT-harddisk-job`；计划 ID `c42b8fcb-3131-488f-a12d-fe226939fe85`。

作业中的 `plan.json`、`state.json`、`connection-identity`、`ai-private`、`media`、`usb-tree` 仍保留。本轮维护脚本另存于作业 `usb-rebuild-20261029` 及上述 E 备份目录。新备份已把原来只在 C 的 v2 恢复点保存在 E；更换介质时也必须带入。

当前云环境路径仅适用于本次环境：

- `/workspace/work/relay-5.4`：5.4 完整接入源码与生产依赖。
- `/workspace/work/private-5.4/near`：本轮已记住的 Windows 5.4 私密近端状态。
- `/workspace/work/private-5.4/mcp`：同一近端的 MCP 状态。
- `/workspace/work/open-deploy-source`：装机分支的稀疏源码检出；大交付文件仍在 GitHub 分支，不能因本地未检出就断言仓库丢失。

设备 ID 为 `0291959e-bcae-4f04-9db5-35a23a4c739b`，主机 `LAPTOP-MCMQHDN4`。使用已有 5.4 近端，不重配身份。状态命令：

```sh
node /workspace/work/relay-5.4/src/pro/cli.cjs devices --role near --state-dir /workspace/work/private-5.4/near
```

MCP 使用同一源码 `src/mcp.cjs --agent-dir /workspace/work/private-5.4/near --state-dir /workspace/work/private-5.4/mcp`，先 ssh_list_servers，工具返回的 server 名称为准。持久 operationId 查询原任务，不因超时重复写盘。本轮操作已结束，不重放写入性检查。

安装后仍沿用原 SSH Relay 3.0；仓库 `private-recovery/pxvirt-original-identity.zip` 和 E 备份保存原身份。恢复连接时只取身份，不把历史安装配置覆盖当前序列号或引导。旧云环境 PXVIRT 近端路径不在新环境自动延续；帮助脚本是 `source/pve/windows/start-pxvirt-near.py`，需要原运行时。目标原路径为 `/var/lib/opendeploy/relay3/`、服务 `opendeploy-relay`；尚无真实 PXVIRT peer/SSH 成功核验，不能说已经接回。

## 后续顺序与边界

1. 当前这块 General UDisk 不再作为可用介质。使用替换 U 盘时重新识别型号、PNP/序列号、容量、系统盘属性；不能让本轮固定 2GB/磁盘2 的检查脚本直接选另一块盘，尤其不能写 E。
2. 复用 E 的完整 staged-usb、原身份、实际 v2 和当前 E 上 ISO/分段载荷。原固定 `usb-prefix` 布局绑定 2013265920 字节；不同容量须按源码的 disk-bytes 重新制作对应布局，不把旧分区尾部当新容量。
3. 更换介质后实际确认写入/持久回读成功、完整文件、自动入口与原身份，才安排实体启动。日志覆盖层必须最后加载；不回退独立诊断停留模式。
4. 固件自动切换 USB 以前不可靠，旧 GUID 曾变化。不要复用历史固件 GUID，也不要保证 Boot-Media -Restart 一定进 USB。本轮未修改固件或重启；后续按用户当次启动意图执行。
5. 安装失败读取第一条真实 failure/trace/console/stages，不再让用户盲等刷屏。成功必须以指定内置盘首启、系统身份、PXVIRT 功能和原远控服务的实际结果认定，Windows 离线不是成功证据。
6. 用户本轮没有要求重新打完整应用 ZIP；仓库旧包 `release/harddisk-usb/OpenDeploy-HardDisk-USB.zip` 未替换，不能称其已包含本轮 v2。实际恢复脚本和 v2 源码已归档到本分支；完整交付仍按 `docs/DELIVERY.md`，不把这些源码与现场备份称为整机安装已验收。
