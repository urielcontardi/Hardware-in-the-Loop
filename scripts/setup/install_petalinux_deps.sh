#!/bin/bash
# Script de instalação de dependências Petalinux para Ubuntu 24.04

set -e

echo "======================================"
echo "Instalando dependências Petalinux"
echo "======================================"

sudo apt update

echo "Instalando pacotes essenciais..."
sudo apt install -y \
    build-essential git wget curl \
    python3 python3-pip python3-pexpect python3-git python3-jinja2 \
    xz-utils debianutils iputils-ping libegl1-mesa libsdl1.2-dev \
    pylint iproute2 gawk make net-tools libncurses5-dev tftpd zlib1g-dev \
    libssl-dev flex bison libselinux1 gnupg diffstat chrpath socat \
    xterm autoconf libtool tar unzip texinfo zlib1g-dev gcc-multilib \
    libglib2.0-dev libpixman-1-dev screen pax gzip cpio rsync file

echo ""
echo "======================================"
echo "Dependências instaladas com sucesso!"
echo "======================================"
echo ""
echo "Próximos passos:"
echo "1. Baixe o Petalinux 2024.1 do site AMD/Xilinx:"
echo "   https://www.xilinx.com/support/download/index.html/content/xilinx/en/downloadNav/embedded-design-tools.html"
echo ""
echo "2. Salve em ~/Downloads/"
echo ""
echo "3. Execute:"
echo "   cd ~/Downloads"
echo "   chmod +x petalinux-v2024.1-final-installer.run"
echo "   mkdir -p ~/xilinx/petalinux"
echo "   ./petalinux-v2024.1-final-installer.run -d ~/xilinx/petalinux"
echo ""
echo "4. Depois de instalar, source o ambiente:"
echo "   source ~/xilinx/petalinux/settings.sh"
echo ""
