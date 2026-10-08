# 故障排除

| JSON `DeviceKind` / 消息 | 安全处理 |
| --- | --- |
| `e11d_pci`，但提示 Dell package missing | 下载 KNP7D A10 原文件，核对文件名和 SHA-256；不要用其它版本或拷贝出的 INF。 |
| 签名或哈希验证失败 | 删除该文件并重新从 Dell 获取；不要绕过检查。 |
| `e118_usb_mbim` | 查看设备管理器的 Generic Mobile Broadband Adapter 和 `netwmbclass.inf`；该路径不应安装 E11D PCI 驱动。 |
| `e118_pci_unsupported` | 当前自动安装器不支持；不要强制 E11D 驱动。 |
| `recovery` | 检测到 `05C6:9008` 或 `0489:E131`。停止；本项目没有恢复流程。 |
| `multiple` | 保留一个目标模块后重试。 |
| `MbnQuerySucceeded: false` | 检查 Windows 蜂窝服务、飞行模式、SIM/eSIM 和设备管理器；该字段不泄露身份信息。 |
| 有适配器但不能上网 | 在 Windows 设置确认蜂窝已启用，并按运营商提供的资料由用户配置 APN。 |
| `driver_complete_fcc_failed` | 驱动步骤已完成，但默认受保护状态检查未达到验证成功。不要视为完整成功；若报告提示 QMUX/MBN 尚未枚举，重启后运行不带跳过参数的 `Repair`。 |
| `driver_complete_state_skipped` / `FccSkippedByUser: true` | 用户明确跳过了状态检查。此结果故意为非零，表示只完成驱动、蜂窝状态未验证；重启后用默认 `Repair` 完成检查。 |

若需要支持，请提供脱敏 JSON 的 `DeviceKind`、`Outcome`、`Message` 和 Windows 版本；不要提交 IMEI、MEID、序列号、手机号、APN 或密码。
