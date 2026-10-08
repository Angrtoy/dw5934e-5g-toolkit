# DW5934e E11D 假 PA 高温掉网：OEM 根修请求

## 结论

目标模块在实际环境温度约 34°C 时，MPSS 将 `sdr0_pa` 报为 131–136°C。该错误样本触发 CFCM 热保护，随后网络协议栈主动撤销注册并进入省电态。主机、SIM、运营商、WebUI、`modemst1/2`、`fsg`、`persist` 和 Windows/Linux 驱动均不是该故障的生产源。

现有本地可部署介质无法根修：

- 修改 `1183_0_0.mbn` 后会破坏 MBNv7 segment SHA-384 与 Foxconn OEM ECDSA-P384 签名，设备会在启动后的完整性复核阶段重启。
- MPSS 完成 secure handoff 后，APSS 对 MPSS DDR 的实际读访问被 XPU 拦截；一次固定地址、固定长度 16 字节的只读验证即触发模块重启。因此不能用 APSS 运行时 overlay 修补。
- DIAG generic memory peek 返回 `BAD_CMD`，未发现厂商授权的 MPSS 内部更新接口。
- 177 个本地 profile 路径、28 个唯一有效签名 profile、15 个唯一 1183 版本均已筛查，`safe_substitute_count=0`。
- Dell 最新官方 `KNP7D / 0.1.0.32 / A10` 的两条固件轨也已完整离线解包并逐个验证：Win10 轨 revision `066` 与 Win11 轨 revision `072` 各含 4 个数字 RFC profile，全部通过 MBNv7 段哈希和 Foxconn OEM ECDSA-P384 签名校验，但没有一个是安全替代项。两条轨的 `1183_0_0.mbn` 均仍保留 `phy 4/6/10` 三条错误 therm association；`safe_substitute_count=0`。
- A09 与 A10 的热敏/CFCM 语义差分也已闭合：相关 QDB 记录数量均为 `1453/1453`，语义增删为 `0`；`PA_FR1_SDR0`、`pa_nr_sdr0_dsc` 与 `/mcpm/rf_thermistor` 对应静态数据在对齐链接位移后相同。A10 不存在隐藏在 1183 之外的 provider/CFCM 修复。

因此需要 OEM 提供重新签名的 1183 profile 或重新签名的 MPSS/Clade RF 驱动。

## 已闭合的故障链

1. `/mcpm/rf_thermistor` 产生错误 QPA PA 温度。
2. `sdr0_pa` 在冷启动后稳定返回 131–136°C；同一时刻：
   - `sdr0`：33–34°C
   - `mmw_ific0`：33–34°C
   - 未装的 `mmw0..3`：-273°C
3. `/therm/mitigate/pa_nr_sdr0_dsc` 消费该错误值。
4. CFCM 以 `PA_FR1_SDR0 / monitor 28` 执行 `action 0 (DNE)`。
5. CMAC deregister，effective `mode_pref` 从 `0x1220` 清为 `0`。
6. 设备进入 `FORCE_PREF -> SD/PWR_SAVE -> SwitchOff`，因此 Linux/Windows 看到模块已上电但 registration state 为 idle、无信号、无法建立数据会话。

最新冷启动后的只读实测：`sdr0_pa=135°C`、`sdr0=34°C`、`mmw_ific0=34°C`。采样已正常发送两次 stop 并退出。

2026-08-22 再次只读复核：模块 USB/ADB 正常枚举、MPSS 为 `running`，但 Linux thermal 仍为 `sdr0_pa=137°C`、`sdr0=27°C`、`mmw_ific0=34°C`。这证明恢复原厂 A09 后错误生产源仍稳定存在。

## 根因对象

1183 RF profile 中三条 QPA therm logical association 将未形成有效温度生产者的对象当作有效传感器：

| ASIC | 当前 physical instance | 对应器件 | 当前 logical 类型/ID | 建议同总线温度别名 |
|---|---:|---|---|---:|
| 1 | 4 | MID `0x217`, PID `0x1A8`, rev `0x93` | class/type `8`, id `92 (0x5C)` | physical 3 |
| 2 | 6 | MID `0x217`, PID `0xA26`, rev `0x93` | class/type `8`, id `92 (0x5C)` | physical 3 |
| 3 | 10 | MID `0x217`, PID `0xA26`, rev `0x93` | class/type `8`, id `92 (0x5C)` | physical 12 |

作为对照，physical 3 与 12 的 QPA 控制/温度对象有效；其 MID 为 `0x217`、PID 为 `0x4`、rev 为 `0x190`。

## 请求的 OEM 修复方案 A：重新签名 1183

基线文件：

- 路径：`/firmware/image/modem_pr/so/1183_0_0.mbn`
- 大小：2,142,560 字节
- SHA-256：`ea15011321e7b378578ddd3c50daeb259e564603c960b696a3ff899450cf9179`
- 固件族：Dell A09 / package 0.1.0.31 / AP070

只修改三条 therm association，保持所有其他内容不变：

| 文件偏移 | 当前值语义 | 请求值语义 |
|---:|---|---|
| `0x3903C` | ASIC 1 therm: phy 4 | ASIC 1 therm: phy 3 |
| `0x39050` | ASIC 2 therm: phy 6 | ASIC 2 therm: phy 3 |
| `0x39064` | ASIC 3 therm: phy 10 | ASIC 3 therm: phy 12 |

重新生成 segment hash table，并使用目标平台接受的 Foxconn OEM P-384 私钥签名。

必须保持不变：

- 全部 physical topology；
- 除上述三条外的全部 logical topology；
- 所有 class/type `4`, id `67` QPA RF-control rows；
- HWID/FSID/BID、SKU、FCC、IMEI 与校准身份；
- 其他 1183 SO 与 NON-HLOS 内容。

离线候选（未部署、不能直接刷入）：

- candidate SHA-256：`1094a78b69ba15822b934e23a89ae516d90dfeeeee3779cec54af89d87401aec`
- 它仅用于说明期望的 payload 差异；必须由 OEM 重新构建/签名后才能部署。

## 请求的 OEM 修复方案 B：修正 RF/Clade 温度驱动

若不改 profile，请在 OEM 签名的 MPSS/Clade RF 驱动中修复以下行为：

1. PID `0x1A8` 与 `0xA26` 的 therm callback 在传感器不存在、未就绪、读失败或样本超出物理范围时，返回失败/invalid（例如框架既有的 -273°C invalid 表示），不得提交 131–136°C 的伪有效值。
2. 上层 QPA wrapper 必须传播 callback 的失败状态，不能把失败强制改为 success。
3. `/mcpm/rf_thermistor` 聚合器必须校验样本有效性与 freshness；无有效 PA 样本时应回退到有效的同总线温度对象或保持 invalid。
4. 不得通过提高阈值、删除 `pa_nr_sdr0_dsc`、关闭 CFCM action 或持续强制重新注册来绕过热保护。

## 不应再尝试的方案

- 重刷同一份 A09/AP070：已经执行，异常生产源不变。
- 降级到 `4HP7C / 0.1.0.26 / A05`：该包早于当前 A09/0.1.0.31，且不是新的修复候选。
- 升级到 `KNP7D / 0.1.0.32 / A10`：两条 A10 固件轨的 `1183_0_0.mbn` 均已离线核验，physical topology、非 therm logical topology、QPA control 与当前板完全相同，但错误 therm 映射也完全相同；Win11/AP072 的 MPSS build 字符串与当前 AP070 相同。A10 不是该热敏拓扑的修复包，不能把版本号本身当作根修依据。
  - 官方 EXE SHA-256：`63fe8a2605c81720e427aeaca47919a76a695f610a5222f83e6d22b2c0ce1d55`，Dell Authenticode 有效。
  - Win11/AP072 `1183_0_0.mbn` SHA-256：`e792f97741db04c10e898bbd051aecc03442bb6bdca99209c628fe9314aa8e95`；MBNv7 段哈希与 Foxconn OEM 签名均有效，但 therm 仍为 `3/4/6/10/12`。
- 覆盖 `modemst1/2`、`fsg`、`persist` 或借用其他模块 NV：不能改变签名 1183/driver 内的生产者逻辑，且可能破坏本机唯一身份与射频校准。
- 修改 `/nv/item_files/therm_monitor/config.ini`：该文件只定义下游采样、阈值和动作，不产生 QPA 温度；提高阈值仅掩盖安全故障。
- APSS 直接读写、`memremap`、SCM ownership reassignment、RAM overlay：已被 XPU/安全所有权边界否定，会导致重启或破坏 MPSS 运行。
- 未签名 MBN、猜测 selector/MCFG/NV、主机 watchdog 反复拉起网络：不是根修。
- 切换 `1183_1_0`/`1183_2_0` 或 selector `01/02`：三个 1183 子 profile 的 QPA control 与 therm 映射都同为 `3/4/6/10/12`，差异只在通用调谐器 BOM；selector `02` 又已在真冷启动中导致 offline。selector `00 / FSID0` 应保持为当前基线。

## OEM 包验收标准

修复包刷入并真正断电冷启动后，必须同时满足：

1. `sdr0_pa` 与同板温度一致且在物理合理范围；不得稳定卡在 131–136°C。
2. 不再出现 CFCM `PA_FR1_SDR0 / monitor 28 / action 0` 的错误动作。
3. 无 CMAC thermal deregistration；effective `mode_pref` 不得从 `0x1220` 清为 `0`。
4. 模块能注册网络并连续保持至少 5 分钟，完成真实数据收发。
5. 再次真正断电冷启动后自动恢复注册和数据，不依赖主机脚本、ADB、WebUI 或人工命令。
6. MPSS 保持 running，无 hash/auth/XPU/SYS_ERR/AP reboot。

## 证据索引

- `analysis/thermal_diag_live_d49d7220_20260822.md`
- `analysis/ap070_thermal_diag_protocol_20260822.md`
- `analysis/signed-rfc-profile-library-screen-20260822.json`
- `analysis/a10_knp7d_all_signed_rfc_profile_screen_20260822.json`
- `analysis/a10_knp7d_19041_all_signed_rfc_profile_screen_20260822.json`
- `artifacts/1183_0_0.ea150.qpa-therm-alias.mbn.json`
- `analysis/apss_rproc_da_readonly_probe/BOUNDARY_20260822.md`
- `docs/workflow-state/e11d-358893170158733-rf-repair.md`
