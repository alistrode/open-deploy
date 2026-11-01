---
name: opendeploy-recovery
description: 首次真实模拟装机的有效代码与现有恢复脚本索引，区分实体PXVIRT与VirtualBox嵌套PXVIRT，不自动执行现场处理。
---

## 当前任务先读

当前现场只以 `docs/HANDOFF.md` 为准；后文保留旧模拟恢复资料，不能当作最新硬件标识、默认引导或进程在线状态。完整交付方法见 `docs/DELIVERY.md`，原身份恢复见 `private-recovery/README.md`。该文件记录最新一轮授权；下文的“本次”“只上传”“只准备”属于各历史整理轮次，不覆盖后来用户明确授权的检查或重做介质。


如果你看到这段话，你必须立刻去看仓库主分支的workspace-backup-dev这个skill，禁止查看主分支的其他skill

## 范围

自动范围止于安装 PXVIRT 并建立稳定部署连接，后续 Tiny10 不要求全自动。本 skill 只指向当时实际运行成功的完整代码文件和实际生效的配置；不交付检索流水、终端命令清单、拆出的命令片段、重复源码或未验证实现，不新增自动修复逻辑。

项目根目录下 `source/pve/` 是正式源码，`source/pve/recovery/simulation/` 是此前独立运行过、基线未收录的四个完整脚本及一份配置。本次只迁入原文件；脚本不接入首启或安装默认入口。它们是本次现场代码，不是新开发的通用恢复工具。

## 两条路线

| 路线 | 系统层次 | 适用范围 |
| --- | --- | --- |
| 真机 | 实体电脑 → PXVIRT → Tiny10 | 本次未进行实体硬件全流程。只参考对应 Windows 来宾层的源码修复，不套用模拟地址、EPT、网桥与端口。 |
| 模拟 | Windows宿主机 → VirtualBox内的PXVIRT → Tiny10 | 本次实际环境。recovery/simulation 的文件只对应此现场，均在PXVIRT内使用，不在Windows宿主机执行。 |

本次身份：VM110，MAC `BC:24:11:D5:1C:15`，Tiny10 UUID `1f752c10-505d-470b-b506-69e0b0a46ede`，计划ID `38ff509d-f0bd-4cdc-a44d-6e15a09f10f4`。脚本保留这些实际约束；另一台机器不直接运行。已安装完成的现场不重放恢复。只选择符合当前证据的一项，不把本文当成批量执行清单。

## 模拟专用：管理地址冲突、私网和RDP

实际故障：桥接的 Tiny10 与 PXVIRT 都取得 `10.0.2.15`，造成管理连通异常。实际修复保留同一VM、MAC与磁盘，把Tiny10接到vmbr110=`10.110.0.1/24`，给它固定DHCP地址`10.110.0.10`，PXVIRT继续使用原管理地址。四CPU、8GiB内存、100GiB原磁盘未替换。

| 原完整文件（相对source/pve/recovery/simulation） | 选择条件与已有前提 | 已实际生效的实现 |
| --- | --- | --- |
| `persist-tiny10-network.sh` | 原VM归属一致；已在现场创建vmbr110并将原MAC接入，地址为10.110.0.1/24；原脚本会核对这些前提 | 将私网、限定子网NAT、回程转发、IPv4转发持久化；在guest-selection保存网桥，原plan不改。 |
| `enable-tiny10-dhcp.sh` | 上述网桥已存在，dnsmasq-base已安装；本次NAT DNS为10.0.2.3，PXVIRT的云端遗留DNS已修正 | DHCP只绑定vmbr110，为原MAC分配10.110.0.10，未知MAC不分配，DNS端口关闭；有独立systemd服务。 |
| `connect-existing-rdp-forward.sh` | 宿主机原已有45641→PXVIRT3389；Tiny103389已监听；本次NAT入口源10.0.2.2、PXVIRT10.0.2.15 | 在PXVIRT内添加并持久化限定来源的DNAT，接到Tiny10；不修改宿主机端口规则。后续实际显示中文桌面。 |

创建网桥、修正DNS、安装dnsmasq是此前直接在现场执行的操作，未形成独立可交付项目程序；本次只在这里说明实际前提，不把终端命令改名为新恢复软件。上述脚本按其已有前提使用，不宣称从空白现场自动建立一切。

## 模拟专用：嵌套EPT

适用证据：VirtualBox原生VT-x已恢复、PXVIRT已有/dev/kvm，启动内层VM时日志为PGMAllPool-x86.cpp:4501、fIsNested、VERR_VMM_RING0_ASSERTION。实际处理是在PXVIRT内、内层VM停止且模块解除占用后，将kvm_intel的EPT设为0；读回为N，保留/dev/kvm，之后越过崩溃位置并完成安装。

原生配置文件 `recovery/simulation/opendeploy-virtualbox-kvm.conf` 对应现场 `/etc/modprobe.d/opendeploy-virtualbox-kvm.conf`，内容即实际持久化的模块参数。原现场同时更新initramfs并重载模块；配置文件不是正在运行的模块参数，单纯复制不等于已生效。这里不新增强制卸载、停机或重启程序。真机、不具备KVM或普通黑屏不适用。

早期maxcpus=1已撤掉，四CPU已上线；nomodeset独立效果没有充分证明，这两个参数不作为有效恢复代码交付。宿主机Hyper-V、虚拟机平台、安全设置或BIOS没有被本轮修改。

## Tiny10来宾层：已在正式源码里的有效修复

这些是最内层Windows问题，与外层VirtualBox嵌套故障分别处理。本次实际结果来自模拟现场，实体PXVIRT中的Tiny10只有出现同样证据才参考。

| 实际问题 | 正式代码位置（相对source/pve） | 已有效的处理 |
| --- | --- | --- |
| specialize启动命令超过259字符，旧缓存应答失败 | `opendeploy.py`的unattended、`templates/Bootstrap.ps1` | 缩短启动入口并运行独立脚本。旧安装缓存曾人工修正，当前源码已经避免产生该超长命令，不重复上传依赖旧源码片段的修补器。 |
| specialize期间Schedule未运行，0x80041315 | `templates/Bootstrap.ps1`、`After-Setup.ps1`、`Guest-Finalize.ps1` | 保留旧SetupComplete，安装后再注册和续跑任务，避免在不具备条件时强行注册。 |
| 中文UI重复安装；Basic组件0x8024402c | `guest_language.py`、`templates/Install-Language.ps1` | 按已装/待重启状态续接；Basic延后，使用规范本地CAB及LimitAccess。原Tiny10为NTDEV x64 23h2、en-US19044.3324，中文是离线补装，非预集成中文版。 |
| 不相关VirtIO驱动被执行；259误判；MSI3010 | `templates/Guest-Finalize.ps1` | 按实际硬件ID匹配，259结合设备状态处理，3010对应真实重启要求；每计划mutex防止重复finalizer。 |
| QGA存在但默认RPC等待不足，反复产生查询进程 | `opendeploy.py`的Host.guest_rpc、Host.guest | 原PVE Monitor API使用90秒RPC等待，保存查询PID并续查，不改PVE自带模块。 |
| 已归属的安装VM停止后重复建盘风险 | `opendeploy.py`的install | 对原VM接续启动，复用磁盘与安装状态。 |
| 裁剪Windows的防火墙接口不可用，RDP未配置 | `templates/Guest-Finalize.ps1` | 已有规则策略存储与正常防火墙接口分开处理，配置TermService；不强启故障可选组件。 |

本次setup.exe=1、后续oobeldr.exe=1的旧中断现场，曾分别在确认原阶段和日志后恢复该子阶段，让Windows自行完成。未伪造ImageState或ready。这些没有独立原项目实现，本次不把注册表终端命令包装成新软件，也不把它们作为任意失败的默认恢复。

## Tiny10现场服务及账户

当时MpsSvc持续StartPending并阻碍服务控制，实际仅将最内层Tiny10的故障服务设为下次不自启，配置TermService；之后进行一次受记录的来宾重启。完整原脚本 `recovery/simulation/reboot-after-firewall-repair.sh` 保留请求状态、观察QMP RESET、处理原查询记录；它含VM110的本次QMP/QGA路径，仅用于原现场。它会暂停安装服务，原现场在Windows恢复后再接续该服务；已记录重启时不重复执行。健康防火墙或宿主机不适用。

原operator的私密计划密码曾经QGA恢复、账户启用并确认管理员组；defaultuser0停用，自动登录关闭。这些属于现场直接操作，不上传密码，也不额外生成命令拼接脚本。

用户当时明确要求停用Tiny10更新；政策、任务和服务处理后，wuauserv和UsoSvc最终均Stopped/PID0/Disabled。原Guest-Finalize已有NoAutoUpdate和wuauserv设置，本次保持原源码，不新增完整杀更新逻辑或默认钩子；历史PID失效的强杀不计为有效操作。后续是否处理更新依当次用户要求和现场状态，不套用历史PID。

## 连接与流程图

中继曾记录broker_offline、流reset和CONNACK timeout，原进程后来恢复；没有确定的broker根因修复代码，不附带猜测性网络补丁，不把源码传输断言为根因。连接只复用5.5身份，不恢复5.4。

真实路线：外层Windows内制作PXVIRT-only介质并写专用模拟盘 → 产品Boot-Media脚本衔接安装 → 外层系统成为PXVIRT → 在PXVIRT内选择Tiny10/VirtIO → 安装原内层VM并处理上述实际故障 → 中文桌面。系统层次和介质路线符合DESIGN模拟流程图，人工恢复属于“处理实际出现的问题”；并非实体电脑实装或Tiny10全自动证明。

“一键”允许点击、选择及分步使用产品入口。第一次做好PXVIRT盘、切换启动、装好PXVIRT并连接的有效源码已上传；后续Tiny10的网络恢复不等于前段PXVIRT安装没完成。连接服务源码有自动续接，但长期持续连通与当前现场状态仍按证据记录。8007产品页面没有本次宿主机既有映射，18016映射的是8006；这与SSH/AI连接分别判断。此次只整理旧有效文件，不擅自补开发新连接方案。装完后的试改、未确认回退不作为首次有效代码分发，当前现场状态见交接。

## 原运行包和原成品盘

首次实际运行目录及其依赖、成品ISO、实际32GiB虚拟安装介质均保存在 `release/simulation-used-20261025/`，以清单还原完整文件。运行包的目录链接已展开为真实依赖。ISO/VDI含原私密安装绑定，因此加密归档；密钥位置和解封方式见当前交接。它们是原现场成品，不是重新制作或已集成后期Tiny10修复的新版本；新任务与原现场归档分别使用。

该目录另存实际中文离线ZIP；按用户最终要求不上传Tiny10镜像，只记录其来源。先完成PXVIRT，再通过原媒体选择入口准备来宾输入；它们没有加入PXVIRT启动盘。Tiny10仍标为原en-US镜像，中文来自单独的微软离线组件。


## 2026-10-27 完整运行包补齐

用户本轮要求先补齐并上传运行包，暂不独立还原；任何核对、测试和验收必须先请示。用户已说明不需要补传哈希。本轮没有执行这些操作。

`release/simulation-used-20261025/delivery-parts.json` 的 Runtime 现指向 `OpenDeploy-Windows-Full-20261027.zip`。这是包含完整原依赖、运行时、资源及当前应用源码的 ZIP，不是独立补丁包；还原入口仍为 `Restore-UsedDelivery.cmd`，应用入口为解压目录的 `OpenDeploy/Start-Windows.cmd`。

包内 `source/pve/` 已放入当前应用文件，包含 `guest_language.py`、`opendeploy.py`、`portal.py`、四个 Windows 安装模板、服务配置和 Windows 入口；根目录的 Windows 入口同步采用该源码版本。上述五个完整模拟恢复脚本/配置随 `source/pve/recovery/simulation/` 放入同一包，仍按适用条件手动选择，不加入默认安装钩子。包内同时放入本 skill 与项目设计、交接文档。

本次只合入仓库中现有的完整代码与配置，遵循此前不把终端命令片段包装为装机程序的要求。桥接创建、旧安装阶段续接、账户与服务的现场直接操作仍按前文记录，不宣称新增了当年实际运行过的独立恢复程序。未把失败试改、检索流水或历史 PID 操作加入包。

首次运行版本的源码仍在 `source/used-windows-20261025/`，原运行包可从历史提交 `65f0afc5b5754e2cdfc6adc528a754718963374c` 获取。当前补齐包不冒称首次运行包的逐字节原件，也未完成本轮整体运行验收。原加密 ISO、VDI 和中文离线 ZIP 保留；Tiny10 ISO 仍按用户要求排除，原介质密钥不上传。


## 硬盘镜像引导 U 盘入口（2026-10-28）

- source/pve/windows/Download-PXVIRT.ps1：实际直连下载、低于 1 MB/s 换源及服务器截断后续传入口；不计算 ISO 哈希。
- source/pve/windows/Start-HardDisk-USB.ps1：E: 镜像、F: 引导 U 盘的实际操作入口。
- source/pve/windows/prepare_harddisk.py：复用原 prepare，导出 U 盘 payload 和 UUID 引导配置。
- source/pve/windows/build_harddisk_boot.py：固定版本 GRUB BIOS/UEFI、NTFS 模块和容量绑定布局的构建源码。
- source/pve/first_boot_package.py：原包默认输出不变；可选 manual_hook 衔接原手动安装后的同一首启服务。
- source/pve/templates/first-boot.sh：普通分区介质识别及手动安装后的一次性根盘绑定；保留旧计划、状态和固定身份。

完整工具包见 release/harddisk-usb/OpenDeploy-HardDisk-USB.zip。不含安装镜像或任何现场私钥。
使用包内 python/python.exe；源 ISO 由远端直接下载到 E:\OpenDeploy-PXVIRT.iso。
执行 source/pve/windows/Start-HardDisk-USB.ps1 -BundleRoot <完整工具包目录> -PythonPath <目录>\python\python.exe。
目标序列号必须由配置提供；缺失时在任何介质写入前报错，不弹选盘窗口，不退回手动安装器。不能将准备电脑系统盘默认作为目标。
制作完成不表示已执行实体安装，固件 Secure Boot 不会由脚本自动改动。

连接一致性修复：`source/pve/media_payload.py` 原子发布首启文件、核对身份并保留重试进度；`source/pve/windows/preserve_connection.py` 保存并验证 U 盘私密身份备份，备份失败不报告制作成功。测试见 `source/pve/tests/test_connection_payload.py`，不代表实体装机验证。

`source/pve/relay_identity.py` 是连接身份唯一来源的生成/导出实现，原 init_relay 调用它。完整作业身份只生成一次，原 near/far 文件是导出结果；成熟作业整体复用，不能把派生文件缺失当作重新生成身份的理由。

当前交接仅见 `docs/HANDOFF.md`，包括实际应用版本、最新介质状态和当轮授权；不再从旧的“五步进度”推断当前可启动或可安装。历史恢复记录查 Git 历史。

准备完成后务必保留原 relay 启动所需的 `relay-state/connection-private.json`，不能从 U 盘导出中删除；实际准备结果及近端位置以 `docs/HANDOFF.md` 为准。

用户明确要求后续以完整 ZIP 交付，不以零散源码作为最终交付；完整上传不自动授权部署，用户没有要求更新远端时不得替换现场；完整交付说明见 `docs/DELIVERY.md`，实际打包源码见 `source/pve/windows/package_harddisk.py`。用户无需自行合并文件或操作终端。

## 2026-10-29 实体小 U 盘检查与 v2 实际源码

`source/pve/recovery/physical-20261029/` 保存这一台实体机器实际使用的恢复准备、原始读写检查，以及从现场 C 盘恢复点与 U 盘原始备份取回的完整 v2 日志源码、原覆盖层和 GRUB 配置。它们没有改成应用默认入口，不适用于其他电脑或未备份的 U 盘。

- `prepare-udisk-rebuild.py`：先验证已有完整原始压缩镜像，把身份、现场文件和 v2 恢复点保存到 E: 的项目备份目录，再按实际文件组装完整介质树；不重新生成身份或制作 ISO。
- `check-udisk.py`：只接受本机当前小 U 盘的明确设备路径、PNP 身份和 2013265920 字节容量，写入位置相关内容后以不经过系统缓存的方式完整回读。它会销毁该 U 盘现有内容，只能在完整备份后按当次授权运行。默认 1MiB 块；4MiB 选项用于复现本轮异常，不能把写入返回成功当作完成。
- `probe-udisk.py`：同一目标盘的五处 4KiB 小块复核；同样具有破坏性，不用于任何其他介质。
- `logging-v2/`：现场实际完整 `/init`、原始 init 的修改版、保持 PID 1 的完整安装启动脚本、8853 字节覆盖层和实际 GRUB 入口。文件内容已与现场恢复点逐一对应；实体安装验收状态仍见 HANDOFF。

本轮全部恢复材料及原盘镜像保存在 `E:\xxm\beifen\OpenDeploy\usb-rebuild-20261029`。该目录包含私密身份，不直接输出其文件内容或上传成公开附件。最新写盘与回读结果以 HANDOFF 和远端实际回执为准。

## 2026-10-30 克隆机入口

VirtualBox 克隆机使用完整包的 `START-VM.cmd`，参数、边界见 `docs/DELIVERY.md`。
实现：`source/pve/windows/Start-VM.ps1`；显式 ISO 由 `build_windows.py --iso` 接入原构建。
完整包构建：`source/pve/windows/package_harddisk.py`。
拒绝路径检查：`python source/pve/tests/check_vm_entry.py`（需 pwsh，只模拟读取磁盘，不写盘）。
该检查、PowerShell 语法解析和 ZIP 依赖检查不代表真实虚拟机装机完成。
