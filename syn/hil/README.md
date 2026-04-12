# EBAZ4205 — Linux Boot via PetaLinux 2025.1

Este diretório contém tudo necessário para:
1. Recriar o projeto Vivado (PS7 + Ethernet EMIO + LEDs)
2. Gerar o XSA e compilar o PetaLinux
3. Gravar o SD card e bootar Linux na EBAZ4205

---

## Hardware

| Item | Especificação |
|------|--------------|
| Placa | EBAZ4205 |
| FPGA | Zynq-7010 (xc7z010clg400-1) |
| RAM | 256 MB DDR3 (MT41K128M16 JT-125) |
| Ethernet PHY | IP101GA (GMII 4-bit via EMIO) |
| Boot | SD card (MIO40–45) |
| Console | UART1 (MIO24–25), 115200 8N1 |

### Modificação de hardware obrigatória para boot SD

Por padrão a placa vem configurada para boot NAND. Para bootar pelo SD card
é necessário mover o resistor **R2584 → R2577** na PCB (MIO4 e MIO5 para VCC).

---

## Estrutura do diretório

```
syn/hil/
├── create_ebaz4205_project.tcl   # Recria o projeto Vivado 2025.1 do zero
├── run_impl_export.tcl           # Sintetiza, implementa e exporta XSA
├── ebaz4205_board.xdc            # Constraints (pinos, IOSTANDARD, false paths)
├── flash_sd.sh                   # Grava SD card com as imagens
├── sd_images/                    # Imagens pré-compiladas prontas para flash
│   ├── BOOT.BIN                  # FSBL + bitstream + U-Boot
│   ├── boot.scr                  # Script de boot do U-Boot
│   ├── image.ub                  # Kernel + device tree (FIT image)
│   └── rootfs.tar.gz             # Sistema de arquivos raiz (EXT4)
└── ebaz4205_petalinux/           # Projeto PetaLinux
    └── project-spec/             # Configurações rastreadas no git
        ├── configs/config        # Configuração do sistema (FIT offset, rootfs EXT4)
        ├── configs/rootfs_config # Pacotes incluídos no rootfs
        └── meta-user/            # Recipes customizadas
```

---

## Opção A — Flash direto (imagens pré-compiladas)

Use quando quiser bootar Linux sem precisar recompilar.

```bash
# Verificar device do SD card
lsblk

# Gravar (substitua /dev/sdX pelo device correto)
sudo ./flash_sd.sh /dev/sdX
```

O script cria automaticamente:
- **p1** FAT32 256 MB → `BOOT.BIN`, `boot.scr`, `image.ub`
- **p2** EXT4 restante → rootfs

---

## Opção B — Build completo do zero

Use quando quiser modificar o design FPGA ou o sistema Linux.

### Pré-requisitos

| Ferramenta | Versão |
|-----------|--------|
| Vivado | 2025.1 |
| PetaLinux | 2025.1 |

```bash
source /opt/Xilinx/2025.1/Vivado/settings64.sh
source ~/xilinx/petalinux/settings.sh
```

### 1. Criar projeto Vivado e gerar XSA

```bash
cd syn/hil

# Criar projeto (PS7 + Ethernet EMIO + LEDs)
vivado -mode batch -source create_ebaz4205_project.tcl

# Sintetizar + implementar + exportar XSA
vivado -mode batch -source run_impl_export.tcl
# Gera: syn/hil/ebaz4205.xsa
```

### 2. Configurar e compilar PetaLinux

```bash
cd syn/hil/ebaz4205_petalinux

# Importar XSA (abre menuconfig — apenas na primeira vez ou após mudar o XSA)
petalinux-config --get-hw-description=../ebaz4205.xsa
# Parâmetros importantes já configurados:
#   u-boot Configuration → FIT image offset = 0x6000000  (256 MB RAM)
#   Image Packaging → Root filesystem type = EXT4

# Configurar U-Boot (necessário apenas uma vez)
# ATENÇÃO: bug conhecido — corrigir system-conf.dtsi antes de rodar
sed -i 's/&ps7_nand_0/\&nfc0/g' \
  components/plnx_workspace/device-tree/device-tree/system-conf.dtsi
petalinux-config -c u-boot
# No menuconfig: Boot options → Boot media → [*] Support for SD/EMMC

# Build completo (~30–60 min na primeira vez)
petalinux-build

# Gerar BOOT.BIN
petalinux-package boot --force \
  --fsbl ./images/linux/zynq_fsbl.elf \
  --fpga ./images/linux/system.bit \
  --u-boot ./images/linux/u-boot.elf
```

### 3. Gravar SD card

```bash
cd syn/hil
sudo ./flash_sd.sh /dev/sdX
```

### 4. Atualizar imagens pré-compiladas no repo

```bash
cp ebaz4205_petalinux/images/linux/BOOT.BIN   sd_images/
cp ebaz4205_petalinux/images/linux/boot.scr   sd_images/
cp ebaz4205_petalinux/images/linux/image.ub   sd_images/
cp ebaz4205_petalinux/images/linux/rootfs.tar.gz sd_images/
```

---

## Boot e acesso ao console

Conecte um adaptador USB-Serial (3.3V TTL) ao header UART da placa:

```
Placa TX → Adaptador RX
Placa RX → Adaptador TX
GND      → GND
```

```bash
picocom -b 115200 /dev/ttyUSB0
```

Para sair do picocom: `Ctrl+A` seguido de `Ctrl+X`.

**Login:** usuário `petalinux` (cria senha no primeiro acesso).

---

## Atualizar apenas o bitstream (sem rebuild Linux)

Quando só o design PL mudar:

```bash
# 1. Regerar XSA
cd syn/hil
vivado -mode batch -source run_impl_export.tcl

# 2. Atualizar PetaLinux com novo XSA
cd ebaz4205_petalinux
petalinux-config --get-hw-description=../ebaz4205.xsa

# 3. Rebuild e reempacotar
petalinux-build
petalinux-package boot --force \
  --fsbl ./images/linux/zynq_fsbl.elf \
  --fpga ./images/linux/system.bit \
  --u-boot ./images/linux/u-boot.elf

# 4. Regravar SD
cd ..
sudo ./flash_sd.sh /dev/sdX
```

---

## Notas e bugs conhecidos

| Problema | Causa | Solução |
|----------|-------|---------|
| `ps7_nand_0: label not found` | Bug PetaLinux 2025.1 | Renomear `&ps7_nand_0` → `&nfc0` em `system-conf.dtsi` |
| `udhcpc: no lease` no boot | Sem cabo/DHCP na rede | Normal — não afeta o boot |
| `No Valid Environment Area found` | U-Boot sem env na FAT | Normal — usa environment padrão |
| UART sem saída | TX/RX invertido | Trocar RX↔TX no adaptador |
