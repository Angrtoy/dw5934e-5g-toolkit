# DW5934e 小白 Windows 11 安装器

这是一个**保守安装器**：它先识别模块，再只对受支持的单一 Dell 子系统 E11D PCI 路径安装经过验证的 Dell 驱动。正常双击安装在驱动/PNP 准备后会自动执行受保护的状态检查：已满足状态时零写入；只有所有严格前置条件成立才进行必要的受保护处理。它不会刷写固件、恢复模块或修改 APN。

## 最快使用方式

1. 从 Dell 获取与本项目文档一致的 KNP7D A10 包；可放在 `drivers/` 或 Windows 的“下载”目录。
2. 双击 `Install-DW5934e.cmd`，接受 Windows 管理员提示。
3. 等待 JSON 状态的 `Outcome`。完成后如运营商要求 APN，请只在 **设置 → 网络和 Internet → 蜂窝网络** 中按运营商资料配置。

先检查而不作任何写入：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Install-DW5934e.ps1 -Mode Inventory
```

`Inventory` 不提权、不写日志/报告、不运行 Dell 包、不运行 `pnputil`、不启动服务，也不发送模块命令。

若只需要完成驱动步骤、明确接受蜂窝状态尚未验证，可在 E11D 上显式跳过：

```powershell
.\Install-DW5934e.cmd -Mode Install -SkipFcc
```

该命令返回 `driver_complete_state_skipped` 和非零退出码，避免伪装为完整成功；重启后可运行 `Repair` 进行默认受保护检查。`-SkipFcc` 不会让 E118、EDL、多模块或无模块进入任何 E11D 路径。

## 支持边界

| 检测到的路径 | 处理 |
| --- | --- |
| 单一 Dell 子系统 E11D PCI | 可执行 Dell 驱动准备和 Windows 蜂窝服务检查。 |
| `USB\VID_05C6&PID_90D5&MI_02` | 只检查 Windows inbox MBIM（`netwmbclass.inf`/`cxwmbclass`）就绪状态；绝不强装 E11D PCI 驱动。 |
| E118 PCI、但没有上述 USB MBIM MI_02 | 明确报为未支持。 |
| `05C6:9008` 或 `0489:E131` | 明确停止：这是恢复/EDL 状态，不做任何恢复操作。 |
| 多个候选模块 | 明确停止，避免对错误设备写入。 |

详细操作和限制见 [Windows 11 部署](docs/WINDOWS11-DEPLOYMENT.md)、[故障排除](docs/TROUBLESHOOTING.md)。开发者见 [开发说明](docs/WINDOWS11-DEVELOPMENT.md)。OpenWrt 使用独立的 [部署说明](docs/OPENWRT-DEPLOYMENT.md)。

## 报告和隐私

安装/修复会在 `%ProgramData%\DW5934e-installer\reports` 写入一份脱敏 JSON，同时输出 JSON 到控制台。报告不保存 IMEI、MEID、序列号、手机号、APN 或 APN 密钥。`Inventory` 为严格只读，只有控制台输出。
