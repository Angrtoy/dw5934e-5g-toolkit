# DW5934e 通话期音频端点观察器

这个脚本只观察 Ubuntu 主机在通话前、拨号后、接通后和结束后可见的设备变化。它不会拨号，不会打开 `/dev/wwan0mbim0`，也不会调用 `qmicli`、`mbimcli` 或 `mmcli`。

它周期性保存：

- MHI 子设备及各自的 `uevent`；
- `/dev/wwan*`、`/dev/snd`、`/sys/class/sound`；
- `/proc/asound/cards`、`/proc/asound/pcm`；
- `aplay -l`、`arecord -l`（系统存在命令时）；
- 指定 DW5934e PCI 功能的 `lspci -vvnn`；
- `wwan0` 的只读链路状态；
- 与 WWAN/音频观察有关的进程名；
- 可选且限定在 `mhi`、`wwan`、`sound` 子系统的 udev 内核事件。

## 使用

开始采集：

```bash
./dw5934e-voice-audio-endpoint-observer.sh start --interval 2 --with-udev-events
```

命令会打印唯一的 `SESSION_DIR`。保留这个路径。用户确认开始拨号、对方接听以及通话结束时，分别标记：

```bash
./dw5934e-voice-audio-endpoint-observer.sh mark --session-dir "$SESSION_DIR" --phase dial
./dw5934e-voice-audio-endpoint-observer.sh mark --session-dir "$SESSION_DIR" --phase connected
./dw5934e-voice-audio-endpoint-observer.sh stop --session-dir "$SESSION_DIR" --phase end
```

`stop` 会等待观察器正常退出并生成：

- `manifest.json`：阶段标记、快照列表及每个快照的 SHA-256；
- `manifest.sha256`：manifest 本身的 SHA-256；
- `snapshots/`：时间戳快照；
- `udev-events.log`：仅在启用 `--with-udev-events` 时出现。

单次离线/环境检查：

```bash
./dw5934e-voice-audio-endpoint-observer.sh start --once --root-dir /tmp/dw5934e-observer-check
```

## 安全边界

- 普通用户即可运行；读取不到的项目会记录为缺失或错误，不要求提权。
- 自定义 `--session-dir` 必须不存在，脚本拒绝覆盖已有目录。
- `stop` 在发信号前会核对 PID 的命令行、脚本路径和会话目录；不会根据任意 PID 文件杀进程。
- 观察器拒绝使用 `SIGKILL`。如果不能正常停止，它会保留现场并返回失败。
- 输出不记录拨打的号码，也不抓取网络数据包、QMI 报文、通话内容或音频样本。
- 观察到新端点只能证明它在该通话生命周期中出现；没有新端点则否定当前标准主机路径的动态暴露，但不能排除模块内部或未公开硬件信号。

## 离线验证

```bash
python3 test_offline_observer.py
bash -n dw5934e-voice-audio-endpoint-observer.sh
```
