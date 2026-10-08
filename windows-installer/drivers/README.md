# 不放驱动文件的 drivers 目录

本项目**不包含** Dell 的 OEM EXE、INF、CAT、SYS 或其他二进制文件，也不会使用从其他电脑拷出的残缺驱动。

安装器只会寻找下面这个精确文件名：

`Dell-Wireless-5934e-and-Qualcomm-Snapdragon-X72-Firmware_KNP7D_WIN64_0.1.0.32_A10.EXE`

查找顺序为：命令行 `-DriverPackagePath`、本目录、当前用户的 `Downloads`。找到后还必须同时通过精确 SHA-256 和有效的 Dell Technologies Inc. Authenticode 签名检查。把官方下载文件放在此目录是方便离线安装的可选做法；不要改名。

安装器只以 Dell DUP 的 `/s /drivers=<新目录>` 提取经验证的驱动组件到新建的 ProgramData 专用临时目录，并仅调用 `pnputil` 安装 `MhiHost.inf`、`QmuxMdm.inf`、`qcmbbnetadapter.inf`。提取目录会在结束时删除。它不使用 `/driveronly`，也不启动该 EXE 的更新/安装流程。
