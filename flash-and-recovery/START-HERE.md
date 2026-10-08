# DW5934e Ubuntu AP070 客户材料包
材料可离线传递；但首次构建 qdl 若 Ubuntu 依赖未预装，仍需要 Ubuntu 官方仓库或经批准的内部 APT 镜像。没有依赖或受控镜像时，停止，不要伪称完整离线运行环境。
安全顺序：
1. [环境准备](docs/01-Ubuntu环境准备.md)：无网时先运行 /bin/bash -p tools/build-qdl-ubuntu.sh 的依赖检查；缺依赖即停止。
2. [状态矩阵与停止条件](docs/05-E11D-E118-状态矩阵与停止条件.md)。
3. [包校验](tools/verify-bundle.sh)：/bin/bash -p tools/verify-bundle.sh。
4. [EDL/AP070 高风险流程](docs/02-EDL9008与AP070刷机.md)。
5. [FCC 内部持久化](docs/03-FCC内部持久化.md)。
6. [联网](docs/04-解锁后联网.md)。
7. [来源与证据](docs/06-来源许可证与验证证据.md)。

安全说明：flash/verify 使用 /bin/bash -p，Bash 在读取脚本前忽略 BASH_ENV、ENV 和导出函数；脚本随后固定 PATH 并清除动态加载变量。普通 bash 启动会在正文最早处以 126 拒绝，不能进入任何硬件路径。
