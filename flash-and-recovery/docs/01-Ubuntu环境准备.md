# 01 Ubuntu 环境准备
安装 network-manager modemmanager libqmi-utils linux-modules-extra-$(uname -r) pciutils usbutils iproute2 curl；启用 NetworkManager 与 ModemManager。
无网先用 /bin/bash -p tools/build-qdl-ubuntu.sh 做检查；缺依赖即停止。只有明确授权 --install-deps-online 才会 apt 安装；受控内部 APT 镜像/预装依赖可替代。用 /bin/bash -p tools/build-qdl-ubuntu.sh 构建固定 qdl；其依赖是 libxml2-dev libusb-1.0-0-dev libzip-dev meson ninja-build help2man。tools/detect-edl.sh 只读识别。
