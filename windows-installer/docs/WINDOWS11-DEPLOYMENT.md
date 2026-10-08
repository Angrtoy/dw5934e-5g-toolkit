# Windows 11 部署

## 前提和安全边界

适用对象是**一个**具有 Dell 子系统的 E11D PCI 模块。安装器只接受 Dell KNP7D A10 的精确文件名、SHA-256 `63fe8a2605c81720e427aeaca47919a76a695f610a5222f83e6d22b2c0ce1d55`，以及有效的 `Dell Technologies Inc.` Authenticode 签名。

不要从另一台机器复制 INF/SYS/CAT，也不要把约 700 MB OEM 包提交或打包进本项目。若验证失败，安装器会停止，不会尝试“相近版本”。Dell PA14250 Windows 11 driver pack 的官方 KB 记录了 DW5934e/X72、Release ID KNP7D 和版本 0.1.0.32，但该条目已标为 Replaced，且它只证明 PA14250；不要把它宣传为所有机器通用，也不要猜测下载 URL。

## 一键安装

1. 下载上述 Dell 文件，保持原文件名；放到 `beginner-installer/drivers/`、当前用户 `Downloads`，或使用 `-DriverPackagePath` 指定它。
2. 双击 `Install-DW5934e.cmd`；正常 `Install`/`Repair` 会请求管理员权限。
3. 安装器以 Dell DUP 的 `/s /drivers=<新 ProgramData 临时目录>` **仅提取驱动组件**。若该精确包不支持该提取方式会安全停止；不会回退到主安装、`/driveronly`、升级器、固件更新、SIM 服务或其他包内 EXE。
4. 它只安装 Windows 11 目录下的 `MhiHost.inf`、`QmuxMdm.inf`、`qcmbbnetadapter.inf`，然后重扫 PnP、启动 `WwanSvc` 并查询 Windows MBN 状态。
5. 对唯一严格匹配 E11D，Install/Repair **默认**接着执行受保护状态检查：稳定 `0/0` 时报告 `already_unlocked_no_write` 且零写入；只有稳定锁定状态和全部身份、QMUX、LowPower、selector、RF baseline、marker 前置条件满足时，才允许必要的受保护动作。
6. QMUX/MBN 未枚举或其他前置失败会失败关闭并提示“可能需重启后以 Repair 重试”；不会猜测成功或强制切换低功耗。
7. 完成后在 Windows 设置中查看蜂窝网络。若运营商要求 APN，请由用户在设置中录入；安装器绝不创建或修改 APN。

可选命令：

```powershell
# 只读盘点（推荐先运行）
.\Install-DW5934e.cmd -Mode Inventory

# 指定下载位置；默认执行受保护状态检查
.\Install-DW5934e.cmd -Mode Install -DriverPackagePath 'D:\Downloads\Dell-Wireless-5934e-and-Qualcomm-Snapdragon-X72-Firmware_KNP7D_WIN64_0.1.0.32_A10.EXE'

# 重新应用受限驱动步骤和默认状态检查；不卸载、不降级、不刷写
.\Install-DW5934e.cmd -Mode Repair

# 明确仅完成驱动步骤；返回 warning/非零状态，状态未验证
.\Install-DW5934e.cmd -Mode Install -SkipFcc
```

`MbnQuerySucceeded: true` 表示 Windows 的 MBN 查询命令可以成功运行；它不是运营商注册或实际上网成功的证明。请在 Windows 蜂窝网络界面实际连接验证。

## 默认受保护状态处理与跳过

只有唯一 Dell E11D 进入默认状态流程；E118、EDL、多模块、无模块和 Inventory 永远不会调用它。它有唯一 QMUX、父设备链、MBN 身份哈希双重匹配和精确请求白名单保护。

如有维护原因需仅完成驱动步骤，可显式传 `-SkipFcc`。报告会有 `FccSkippedByUser: true` 和 `driver_complete_state_skipped`，并以非零状态提醒“驱动完成不等于状态成功”；重启后请以未带跳过参数的 Repair 重试。

## 不同硬件状态

* `USB\VID_05C6&PID_90D5&MI_02` 是已经验证的 E118 USB 复合设备路径：Windows 应使用 inbox `netwmbclass.inf` 和 `cxwmbclass`（Generic Mobile Broadband Adapter）。此路径不使用 Dell E11D 驱动或 E11D 状态流程。
* 只出现 E118 PCI 而没有识别到该 USB MBIM MI_02 时，本安装器不支持该路径。
* `USB\VID_05C6&PID_9008` 或 `USB\VID_0489&PID_E131` 是恢复状态：停止并寻求有资质的恢复流程；本项目不提供恢复功能。
* 出现多模块候选时先移除多余设备/关闭扩展坞路径，再重试。安装器不会猜测目标。
