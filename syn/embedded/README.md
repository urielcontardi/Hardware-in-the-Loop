# Embedded Linux Synthesis

Este diretório contém o projeto Petalinux para EBAZ4205 (síntese do sistema embarcado Linux).

## Estrutura

```
syn/embedded/
├── README.md              # Este arquivo
├── project/               # (vazio - será criado durante setup)
│   └── hil-ebaz4205/     # Projeto Petalinux (após petalinux-create)
    ├── images/linux/      # Binários gerados (BOOT.BIN, rootfs, etc)
    ├── project-spec/      # Configurações do projeto
    ├── components/        # Device tree, u-boot, kernel
    └── build/             # Diretório de build Yocto
```

## Quick Start

### 1. Instalar Petalinux
```bash
# Primeiro instale dependências
cd ../../scripts/setup
./install_petalinux_deps.sh

# Baixe instalador do site Xilinx e instale
mkdir -p ~/xilinx/petalinux
~/Downloads/petalinux-v2024.1-final-installer.run -d ~/xilinx/petalinux

# Source ambiente
source ~/xilinx/petalinux/settings.sh
```

### 2. Criar Projeto
```bash
cd syn/embedded/project
petalinux-create -t project --name hil-ebaz4205 --template zynq
cd hil-ebaz4205
```

### 3. Importar Hardware
```bash
# Assumindo que você já exportou .xsa do Vivado
petalinux-config --get-hw-description=../../hil
```

### 4. Build
```bash
petalinux-build

# Gerar BOOT.BIN
cd images/linux
petalinux-package --boot \
    --fsbl zynq_fsbl.elf \
    --fpga ../../project-spec/hw-description/*.bit \
    --u-boot u-boot.elf \
    --force
```

### 5. Preparar SD Card
Ver guia completo em: `../../docs/PETALINUX_GUIDE.md`

## Embedded Scripts

Os scripts em `src/embedded/` devem ser copiados para o rootfs do Linux embarcado.

**Durante build (recomendado):**
```bash
# Copiar para rootfs antes de fazer tar
sudo cp ../../src/embedded/*.py build/tmp/work/*/rootfs/home/root/
```

**Após boot (via SCP):**
```bash
scp ../../src/embedded/udp_sender.py root@192.168.1.10:/home/root/
```

## Arquivos Importantes

### `hil-ebaz4205/images/linux/`
Após build bem-sucedido, encontrará:

- **BOOT.BIN** - Boot image (FSBL + FPGA bitstream + U-boot)
- **boot.scr** - U-boot script
- **image.ub** - FIT image (kernel + device tree + initramfs opcional)
- **rootfs.tar.gz** - Root filesystem completo
- **system.dtb** - Device tree blob

### `hil-ebaz4205/project-spec/meta-user/`
Customizações do projeto:

- `recipes-bsp/device-tree/files/system-user.dtsi` - Device tree customizado
- `recipes-apps/` - Aplicações customizadas
- `recipes-kernel/` - Módulos kernel customizados

## Configurações Importantes

### Device Tree (system-user.dtsi)
```dts
/include/ "system-conf.dtsi"
/ {
    reserved-memory {
        solver_bram: solver_bram@40000000 {
            compatible = "shared-dma-pool";
            reg = <0x40000000 0x10000>;
            no-map;
        };
    };

    solver_mem: solver_mem@40000000 {
        compatible = "generic-uio";
        reg = <0x40000000 0x10000>;
    };
};
```

### U-boot Offsets (256MB RAM)
```
Fit image offset: 0x06000000
Ramdisk offset:   0x04000000
Kernel offset:    0x00200000
```

## Comandos Úteis

```bash
# Source ambiente (sempre antes de usar petalinux)
source ~/xilinx/petalinux/settings.sh

# Clean build
petalinux-build -x mrproper

# Rebuild componente específico
petalinux-build -c u-boot -x clean
petalinux-build -c u-boot

# Config menuconfig
petalinux-config                  # Projeto
petalinux-config -c kernel        # Kernel
petalinux-config -c rootfs        # Root filesystem
petalinux-config -c u-boot        # U-boot

# Deploy para TFTP (alternativa a SD card)
petalinux-package --prebuilt --fpga images/linux/system.bit
```

## Troubleshooting

**Build falha com "Disk full":**
- Petalinux precisa ~60GB livres em `/tmp` e no diretório de trabalho
- Limpar build: `petalinux-build -x mrproper`

**"ps7_nand_0 not found":**
```bash
vim components/plnx_workspace/device-tree/device-tree/system-conf.dtsi
# Mudar &ps7_nand_0 para &nfc0
```

**Build Yocto muito lento:**
- Use `--cpus` e `--mem` para limitar recursos
- Configure `BB_NUMBER_THREADS` e `PARALLEL_MAKE` em `project-spec/configs/config`

**Kernel panic no boot:**
- Verifique offset do FIT image (não pode sobrepor ramdisk)
- Check device tree (erros em .dtsi causam boot failure)

## Referências

- **Guia completo**: `../../docs/PETALINUX_GUIDE.md`
- **Xilinx UG1144**: PetaLinux Tools Documentation Reference Guide
- **Embedded scripts**: `../../src/embedded/README.md`
- **FPGA synthesis**: `../hil/` (Vivado project)
