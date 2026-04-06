# Guia: Petalinux no EBAZ4205 com Solver RTL → UDP

## Objetivo Final
1. **PL (FPGA)**: Seu solver TIM escreve resultados em memória compartilhada (AXI BRAM ou HP port)
2. **PS (ARM)**: Linux lê essa memória via driver e envia dados por UDP ethernet
3. **Boot**: SD Card com BOOT.bin (FSBL + bitstream + U-boot) + rootfs Linux

---

## Pré-requisitos

### Hardware
- EBAZ4205 com modificações necessárias:
  - Resistor R2584 removido, R2577 soldado (boot SD Card)
  - Capacitores C585/C584 (se PHY clock via PL)
  - SD Card 4GB+ (2 partições: FAT32 boot + ext4 rootfs)

### Software (seu sistema Ubuntu 24.04)
- **Vivado 2024.1** (já instalado em `/opt/Xilinx/Vivado/2024.1`)
- **Petalinux 2024.1** ou **2024.2** (vamos instalar)
- **Dependências**: `apt install` de libs necessárias

---

## Passo 1: Instalar Petalinux

### 1.1 Download do Instalador
```bash
# Baixe do site Xilinx (AMD):
# https://www.xilinx.com/support/download/index.html/content/xilinx/en/downloadNav/embedded-design-tools.html
# Arquivo: petalinux-v2024.1-final-installer.run (~10GB)

# Salve em ~/Downloads/
```

### 1.2 Instalar Dependências (Ubuntu 24.04)
```bash
sudo apt update
sudo apt install -y \
    build-essential git wget curl \
    python3 python3-pip python3-pexpect python3-git python3-jinja2 \
    xz-utils debianutils iputils-ping libegl1-mesa libsdl1.2-dev \
    pylint iproute2 gawk make net-tools libncurses5-dev tftpd zlib1g-dev \
    libssl-dev flex bison libselinux1 gnupg diffstat chrpath socat \
    xterm autoconf libtool tar unzip texinfo zlib1g-dev gcc-multilib \
    libglib2.0-dev libpixman-1-dev screen pax gzip cpio rsync file
```

### 1.3 Executar Instalador
```bash
mkdir -p ~/xilinx/petalinux
cd ~/Downloads
chmod +x petalinux-v2024.1-final-installer.run
./petalinux-v2024.1-final-installer.run -d ~/xilinx/petalinux
```
**Tempo**: ~15-30 min

### 1.4 Source do Ambiente (sempre antes de usar)
```bash
source ~/xilinx/petalinux/settings.sh
```
Adicione ao `~/.bashrc` se quiser automático:
```bash
echo "alias petalinux-setup='source ~/xilinx/petalinux/settings.sh'" >> ~/.bashrc
```

---

## Passo 2: Criar Design Vivado com AXI para Memória Compartilhada

### 2.1 Arquitetura
```
┌─────────────────────────────────────────┐
│  PS (ARM Cortex-A9)                     │
│  - Linux Kernel                         │
│  - UDP daemon (Python ou C)             │
│  - Acessa memória via /dev/mem ou UIO   │
│                                         │
│  AXI HP0 (High Performance Port)        │
└──────────┬──────────────────────────────┘
           │ AXI4 Full (64-bit, 150 MHz)
┌──────────▼──────────────────────────────┐
│  AXI BRAM Controller                    │
│  - Base address: 0x40000000             │
│  - Size: 64KB (ajuste conforme solver)  │
└──────────┬──────────────────────────────┘
           │ BRAM interface
┌──────────▼──────────────────────────────┐
│  BRAM (Block RAM)                       │
│  - Dual-port: porta A → PS, porta B → PL│
└──────────┬──────────────────────────────┘
           │ porta B (custom logic)
┌──────────▼──────────────────────────────┐
│  TIM_Solver (seu RTL)                   │
│  - Escreve resultados (speed, current)  │
│    em endereços fixos da BRAM           │
└─────────────────────────────────────────┘
```

### 2.2 Modificar Vivado Block Design
No seu projeto `syn/hil/`:

1. **Abrir Vivado**:
   ```bash
   cd ~/Desktop/Projects/Hardware-in-the-Loop/syn/hil
   vivado HIL_EBAZ4205/HIL_EBAZ4205.xpr
   ```

2. **Adicionar PS7 com HP Port**:
   - Open Block Design
   - Add IP: `ZYNQ7 Processing System`
   - Double-click PS7 → Zynq Block Design
   - `PS-PL Configuration`:
     - HP Slave AXI Interface → **Enable S_AXI_HP0**
     - Clock Configuration → PL Fabric Clocks → **FCLK_CLK0 = 100 MHz**
   - `MIO Configuration`:
     - Enable SD0, UART1, ENET0 (como no blog)
   - `DDR Configuration`: MT41K128M16 HA-15E

3. **Adicionar AXI BRAM Controller**:
   - Add IP: `AXI BRAM Controller`
   - Config:
     - Number of BRAM interfaces: **1**
     - Data Width: **64** (match HP0)
     - ECC: Disabled
   - Connect `S_AXI` → PS7 `M_AXI_GP0` (ou use AXI Interconnect se precisar múltiplos slaves)

4. **Adicionar BRAM Generator**:
   - Add IP: `Block Memory Generator`
   - Config:
     - Memory Type: **True Dual Port RAM**
     - Port A: Width=64, Depth=8192 (64KB)
     - Port B: Width=42 (ou conforme seu solver), Depth ajustado
   - Connect porta A → AXI BRAM Controller
   - **Porta B**: external ports para seu `TIM_Solver`

5. **Conectar seu TIM_Solver**:
   - Adicione wrapper HDL que pega saídas do solver e escreve na porta B do BRAM
   - Exemplo:
     ```vhdl
     -- WriteSolverResults.vhd
     process(clk)
     begin
       if rising_edge(clk) then
         if solver_data_valid = '1' then
           bram_wrb <= '1';
           bram_addrb <= addr_speed;  -- offset fixo, ex: 0x00
           bram_dinb <= solver_speed; -- 42-bit
         end if;
       end if;
     end process;
     ```

6. **Address Editor**:
   - Assign AXI BRAM Controller base: **0x40000000**
   - Range: **64K** (0x40000000 - 0x4000FFFF)

7. **Export Hardware**:
   - Generate Bitstream
   - `File → Export → Export Hardware → Include Bitstream`
   - Salva `.xsa` em `syn/hil/hil_ebaz4205.xsa`

---

## Passo 3: Criar Projeto Petalinux

### 3.1 Criar Projeto
```bash
cd ~/Desktop/Projects/Hardware-in-the-Loop/syn/embedded
mkdir -p project && cd project

petalinux-create -t project --name hil-ebaz4205 --template zynq
cd hil-ebaz4205
```

### 3.2 Importar Hardware (.xsa)
```bash
petalinux-config --get-hw-description=../../hil
```

### 3.3 Configurar Petalinux (menuconfig abre)
Ajustar:
- **u-boot Configuration → u-boot script configuration → JTAG/DDR image offsets**:
  - Fit image offset: `0x06000000` (256MB RAM limit)
  
- **Image Packaging Configuration**:
  - Root filesystem type: **EXT4 (SD/eMMC/SATA/USB)**

- **Subsystem AUTO Hardware Settings → Ethernet Settings**:
  - Verify PHY address (0x01 para IP101GA)
  - GMII mode

- **Subsystem AUTO Hardware Settings → Advanced bootable images storage Settings**:
  - Boot Device: **primary sd**

Salve e saia (Save → Exit)

### 3.4 Fix Device Tree Bug (se ocorrer)
Se der erro `ps7_nand_0 not found`:
```bash
vim components/plnx_workspace/device-tree/device-tree/system-conf.dtsi
# Mudar &ps7_nand_0 para &nfc0 (ou deletar o bloco inteiro)
```

### 3.5 Adicionar Device Tree para BRAM (memória compartilhada)
```bash
vim project-spec/meta-user/recipes-bsp/device-tree/files/system-user.dtsi
```
Adicione:
```dts
/include/ "system-conf.dtsi"
/ {
    reserved-memory {
        #address-cells = <1>;
        #size-cells = <1>;
        ranges;

        solver_bram: solver_bram@40000000 {
            compatible = "shared-dma-pool";
            reg = <0x40000000 0x10000>; /* 64KB */
            no-map;
        };
    };

    solver_mem: solver_mem@40000000 {
        compatible = "generic-uio";
        reg = <0x40000000 0x10000>;
        interrupt-parent = <&intc>;
        interrupts = <0 29 4>; /* ajustar se tiver IRQ */
    };
};
```
Isso expõe memória como `/dev/uio0` no Linux.

---

## Passo 4: Build Petalinux

### 4.1 Compilar tudo
```bash
petalinux-build
```
**Tempo**: 1-3 horas (primeira vez baixa 20GB+ de pacotes Yocto)

### 4.2 Gerar BOOT.BIN
```bash
cd images/linux
petalinux-package --boot \
    --fsbl zynq_fsbl.elf \
    --fpga ../../project-spec/hw-description/*.bit \
    --u-boot u-boot.elf \
    --force
```
Gera `BOOT.BIN` com tudo: FSBL + bitstream + U-boot

---

## Passo 5: Preparar SD Card

### 5.1 Particionar (via fdisk ou gparted)
```bash
sudo fdisk /dev/sdX  # substitua X pela letra do seu SD

# Criar:
# /dev/sdX1: 500MB, FAT32, bootable
# /dev/sdX2: resto, ext4
```

### 5.2 Formatar
```bash
sudo mkfs.vfat -F 32 -n BOOT /dev/sdX1
sudo mkfs.ext4 -L rootfs /dev/sdX2
```

### 5.3 Copiar Arquivos Boot
```bash
sudo mount /dev/sdX1 /mnt
cd ~/Desktop/Projects/Hardware-in-the-Loop/petalinux/hil-ebaz4205/images/linux
sudo cp BOOT.BIN boot.scr image.ub /mnt/
sync
sudo umount /mnt
```

### 5.4 Extrair rootfs
```bash
sudo mount /dev/sdX2 /mnt
sudo tar xf rootfs.tar.gz -C /mnt
sync
sudo umount /mnt
```

---

## Passo 6: Criar Aplicação UDP no Linux (Userspace)

### 6.1 Adicionar Python ao rootfs (se necessário)
```bash
petalinux-config -c rootfs
# Package Groups → python3-modules → enable
# Filesystem Packages → misc → python3 → python3-pyserial
petalinux-build
```

### 6.2 Script UDP Python (no SD Card)
Crie `udp_sender.py` no rootfs `/home/root/`:
```python
#!/usr/bin/env python3
import socket
import struct
import mmap
import time

BRAM_ADDR = 0x40000000
BRAM_SIZE = 0x10000
UDP_IP = "192.168.1.100"  # IP destino
UDP_PORT = 5005

# Mapeamento memória via /dev/mem
with open("/dev/mem", "r+b") as f:
    mem = mmap.mmap(f.fileno(), BRAM_SIZE, offset=BRAM_ADDR)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

while True:
    # Lê 42-bit data do BRAM (exemplo: offset 0 = speed)
    mem.seek(0)
    data_bytes = mem.read(8)  # lê 64-bit
    speed_raw = struct.unpack('<Q', data_bytes)[0] & 0x3FFFFFFFFFF  # mask 42-bit
    
    # Converte Q14.28 para float
    speed_float = speed_raw / (2**28)
    
    # Envia UDP
    packet = struct.pack('<f', speed_float)
    sock.sendto(packet, (UDP_IP, UDP_PORT))
    
    time.sleep(0.01)  # 100 Hz
```

Adicione ao rootfs:
```bash
sudo mount /dev/sdX2 /mnt
sudo mkdir -p /mnt/home/root
sudo cp udp_sender.py /mnt/home/root/
sudo chmod +x /mnt/home/root/udp_sender.py
sudo umount /mnt
```

### 6.3 Auto-start na inicialização (systemd)
Crie `/mnt/etc/systemd/system/udp-solver.service`:
```ini
[Unit]
Description=UDP Solver Sender
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 /home/root/udp_sender.py
Restart=always

[Install]
WantedBy=multi-user.target
```
Enable:
```bash
sudo systemctl enable udp-solver.service
```

---

## Passo 7: Boot e Teste

### 7.1 Inserir SD Card e Conectar UART
- USB-UART em J7: TX(F19), RX(F20), GND
- Minicom: `minicom -D /dev/ttyUSB0 -b 115200`

### 7.2 Ligar EBAZ4205
- U-boot deve aparecer no UART
- Kernel boot log
- Login: `root` / `root`

### 7.3 Verificar FPGA carregado
```bash
cat /sys/class/fpga_manager/fpga0/state
# Deve mostrar: "operating"
```

### 7.4 Verificar memória UIO
```bash
ls /dev/uio*
# /dev/uio0 → sua BRAM
```

### 7.5 Testar UDP
```bash
# No EBAZ4205:
ifconfig eth0 192.168.1.10 netmask 255.255.255.0 up
ping 192.168.1.100  # seu PC

# No seu PC (receber UDP):
nc -lu 5005
# Deve ver dados chegando
```

### 7.6 Iniciar daemon
```bash
systemctl start udp-solver.service
systemctl status udp-solver.service
```

---

## Resumo de Arquivos Gerados

```
petalinux/hil-ebaz4205/
├── images/linux/
│   ├── BOOT.BIN           → SD partition 1
│   ├── boot.scr           → SD partition 1
│   ├── image.ub           → SD partition 1
│   └── rootfs.tar.gz      → extrair em SD partition 2
```

---

## Troubleshooting

### Erro: "Fit image load address overlap"
- Aumentar `Fit image offset` para **0x08000000** (se usar INITRAMFS)

### Erro: "PHY not detected"
- Verificar cristal 25MHz (capacitores C585/C584)
- Checar constraints do MDIO no `.xdc`

### Erro: "Cannot open /dev/mem"
- Kernel config: `CONFIG_DEVMEM=y` (já default no Petalinux)
- Tentar com UIO: `/dev/uio0` é mais seguro

### Solver não escreve na BRAM
- Verificar sinais `clk`, `wren` no ILA (Vivado)
- Adicionar ChipScope/ILA no design para debug

---

## Próximos Passos

1. **Otimizar latência**: DMA direto com driver kernel (em vez de UIO)
2. **Timestamp**: Adicionar contador no PL, enviar junto com dados
3. **Múltiplos dados**: Estruturar buffer circular na BRAM
4. **GUI Tauri**: Integrar com `apps/hil-gui-tauri` recebendo UDP

---

**Referências**:
- Blog original: https://codeembedded.in/posts/fpga-zero-to-hero-vol-5-ebaz4205-chronicles/
- Xilinx UG1144: PetaLinux Tools Documentation
- Zynq-7000 TRM: https://docs.amd.com/v/u/en-US/ug585-zynq-7000-SoC-TRM
