# 03 FCC 内部持久化
fcc/verified-e11d-artifacts 是历史 E11D 工厂样卡材料。脱敏历史证据：Ubuntu 真冷启动后 DMS Online、FCC state [0,0]、身份稳定、5G 注册/PS attached/SIM ready；只读复核 writes_sent=0。
这不是一键部署器。reference/unverified-host-deploy 仅供审阅，含外部依赖风险，禁止直接执行。ddc 的 v2/v2-retry/v3 没有成功 Ubuntu transaction；不扩展到其他设备。
推荐：授权、同模块现场哈希、双读审计、合格人员安装、冷启动、再次双读。module-audit 仅 GET；module-uninstall 是 PACKAGE-AUTHORED 模板，须确认与目标哈希，不能宣称恢复原状态。
