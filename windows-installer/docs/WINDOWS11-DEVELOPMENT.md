# Windows 11 开发与维护说明

## 结构和信任边界

* `Install-DW5934e.cmd` 是小白入口；`windows/Install-DW5934e.ps1` 是唯一安装流程。
* `windows/manifests/dell-packages.json` 是 OEM 包、签名策略、提取目录和 INF 白名单的可审计策略记录。
* `windows/lib/Dw5934e.Fcc.cs` 是封闭的 E11D QMUX 实现。它没有通用 QMI/AT 输入接口，且 C# 内部再次检查精确请求体。

正常 Install/Repair 在唯一严格 E11D 的驱动与 PNP 准备后默认调用该封闭实现；Inventory 和所有非 E11D 分类不调用。`-SkipFcc` 是唯一显式 opt-out：它只对 E11D Install/Repair 生效，报告 `FccSkippedByUser=true` 与 `driver_complete_state_skipped`，并以非零退出，绝不能被当成完整状态成功。

脚本的分类必须先于任何写操作。Inventory 是严格只读；Install 和 Repair 仅在分类为一个 Dell E11D PCI 模块时进行驱动写入。EDL、未知 E118 PCI、E118 USB、无模块和多模块都不进入 E11D 驱动或 QMUX 路径。

## OEM 包策略

从 Dell DUP 指南/包清单确认了 Windows 11 驱动根 `Production\Windows10-x64\22000\Drivers` 和 E11D 的 MHI、QMUX、网络适配器关联。网络最小白名单为：

1. `MhiHost.inf`（受支持 Dell 子系统 E11D PCI）
2. `QmuxMdm.inf`（由 MHI 总线产生的 QMUX/子设备）
3. `qcmbbnetadapter.inf`（E11D 的 WWAN 网络适配器）

提取后的每一个白名单 INF 会先按文本拒绝包含 firmware、MBFW、flash 或 firmware-update 指示词的内容，才交给 `pnputil`；缺少任何一个白名单 INF 也会失败关闭。不要扩大为递归 `/subdirs` 安装，不要使用现有远程盘点的残缺 INF，并且不能把包二进制放入仓库。

DUP 的安全路径是 `/s /drivers=<新目录>`，不是提取全部的 `/e`，更不是直接安装/更新驱动的 `/driveronly`。若精确 KNP7D 包拒绝 `/drivers`，保持失败，不得回退到其它流程。依据：Dell [Windows CLI options](https://www.dell.com/support/manuals/en-us/dell-update-packages/dup_framework_23.12.00_ug_pub/windows-cli-options?guid=guid-7e40f460-fdff-4cf9-b26f-e58065d8acbe&lang=en-us)、[CLI exit codes](https://www.dell.com/support/manuals/en-us/dell-update-packages/dup_framework_23.12.00_ug_pub/exit-codes-for-cli?guid=guid-709bb23f-1f40-492f-8774-bbed273df825&lang=en-us) 和 [PA14250 driver pack KB](https://www.dell.com/support/kbdoc/en-us/000272647/dell-pro-laptops-pa14250-windows-11-driver-pack)。

## QMUX 维护规则

该实现源自已审计 E11D 事务并保留 `{7dcb3244-c836-4a0c-a1e9-bd68d385aa2b}`、`#QcQmux_E11D105B#`、DMS 身份哈希双读、FOX/AP_FOX 状态双读、低功耗/selector/RF baseline/marker 前置检查、动作 3 以及动作 2/0 回滚验证。

状态 `0/0` 时返回 `already_unlocked_no_write`，不写入。只有稳定 `1/1` 和全部前置检查成功才允许唯一动作 3。混合、解析异常、身份不匹配或其他未知结果都失败关闭且零写入。事务前由 PowerShell 另外确认唯一 QMUX 和通向 Dell E11D PCI 的父链；身份只以 SHA-256 前提匹配，不写入报告原始值。

报告把模块写入区分为 `ModuleWriteRequestsAttempted`（发起的固定写请求数）与 `ModuleWriteRequestsSent`（底层 TX 已成功提交的数）；`ModuleWrites` 等于后者。动作 3 后的回滚动作 2、0 都分别计数，因此完整“动作 3 + 回滚”会是 3，不会再把任意写尝试笼统记成 1。只有 `already_unlocked_no_write` 或完整 `action3_verified` 才是状态目标成功；precondition failure、已回滚或回滚未验证都会令顶层非零退出，但会保留已完成的驱动阶段事实。

DMS Get IDs 的身份 TLV 保持为 `0x11`：上游 libqmi 将它定义为 IMEI（最多 15 位十进制），不是 MEID。PowerShell 只接受 `netsh mbn show interfaces` 中具名的 `Device ID`、`设备 ID` 或 `设备ID` 字段，且必须唯一；任意未标注的 14/15 位数字会失败关闭。两侧均对 `ASCII(identity + LF)` 计算 SHA-256，原始身份不进入报告。

修改 C# 请求、路径、服务、消息、TLV 或前置条件需要重新审计，不能以“测试设备可用”为由放宽。当前文件 SHA-256：`12fbe8333f26782667218fcdbe1ddced49a06c5f9f0e8503ceb4b41279bfa4aa`。

## 本地验证

在 Windows PowerShell 5.1 或 PowerShell 7 中运行：

```powershell
& .\tests\Test-Contracts.ps1
& .\windows\Install-DW5934e.ps1 -Mode Inventory
```

第二条命令只能验证本机只读分类和 MBN 查询，不能证明 Dell 包提取、驱动安装、蜂窝注册、真实上网或受控事务在真实 E11D 上成功。
