# DW5934E AP047：冷启动两阶段方案

本包不连接设备；脚本仅在复制到目标主机后由管理员手动执行。

复制前后先在包目录执行 `sha256sum -c SHA256SUMS`；清单涵盖所有可部署脚本、unit 和离线测试。

`phase-a-stage-rc-local.remote.sh` 的唯一运行时驱动方向是 `mhi-pci-generic → mhi_q`。它先要求 native MBIM 报告 radio-off，切到 vendor 后再以 QMI 读取确认 Low Power，最后经 `/dev/mhi_ADB` 把模块的 `/etc/rc.local` 从 `/data/rc.local.pre-low-power-20260904` 恢复。模块侧同时检查既有 `dw_dms` 三个业务文件、`S86dw_dms` 链接和最终 SHA-256 `c21bedf9042f038bdb5017f490df3f666f4811473c85b93b17d562d2b73e0f29`。它不发送 Online，结束时保持 `mhi_q`，要求真正冷启动；因此既有 `/etc/init.d/dw_dms worker` 最早只能在下一次冷启动运行 Online。

阶段 A 在切换前会验证既有 native-maintenance 的持久准备已经存在：native modules-load、vendor `pcie_mhi` block、`dw5934e-maintenance-radio-off.service` 的 enable link，以及 ModemManager 的 `Requires/After` gate。否则它不切驱动。因此下一次**真实冷启动**才会使用 `mhi-pci-generic`；不要通过运行中的 `mhi_q → mhi-pci-generic` 完成此事。该方向已知会触发 `Device died`，包内没有它。

在下一次冷启动后，先安装本包（只安装文件，不启动升级）：

```bash
sudo ./install-host-artifacts.remote.sh
sudo /usr/local/sbin/dw5934e-ap047-phase-a       # 阶段 A，完成后执行真实冷启动
# 冷启动进入既有 native maintenance；它必须成功写出 radio-off marker
sudo systemctl start dw5934e-ap047-phase-b.service
```

阶段 B 只接受 BDF `0000:07:00.0`（17cb:0309:105b:e11d）、driver `mhi-pci-generic`、BDF 下的 `/dev/wwan0mbim0`、现有 `dw5934e-maintenance-radio-off.service` 的本次启动成功 marker、MM model `DP25-42843-47`、源版本 `FDE2.F0.0.0.1.2.CU.001`，以及 fwupd 同一对象的 GUID `666d7968-3783-513c-8981-49c6fab13626` 和源版本。它在当前 boot 未看到 n78 crash 后，才以无 timeout 的单个 `fwupdmgr install --no-reboot` 写入本地、非符号链接且 SHA-256 已验证的 AP047 CAB。开始写入后，trap 不会停止 ModemManager、切驱动或发送 DMS。

安装命令开始前失败时，阶段 B 会停止 ModemManager 并保持 native 驱动不变。开始写入后失败时只能保留设备和服务状态并收集日志；不要自行运行任何恢复、driver switch、MM stop 或 DMS 命令。`rollback-before-install.remote.sh` 只适用于安装尚未开始的情况，它删除本包自身的部署文件，不回滚模块内容、RF、NV、FCC 或既有 native-maintenance 配置。

本包不含且不执行 EDL、RF、NV、FCC、MCFG 操作。
