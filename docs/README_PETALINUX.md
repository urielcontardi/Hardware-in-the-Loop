# Integração Petalinux - EBAZ4205 HIL

## O que foi criado:

### 1. Documentação
- **PETALINUX_GUIDE.md**: Guia completo passo-a-passo para:
  - Instalar Petalinux 2024.1
  - Criar design Vivado com memória compartilhada (AXI BRAM)
  - Configurar projeto Petalinux
  - Build e geração de BOOT.BIN
  - Preparar SD Card
  - Boot Linux e teste

### 2. Scripts

#### `install_petalinux_deps.sh`
Instala todas dependências necessárias no Ubuntu 24.04.
```bash
./install_petalinux_deps.sh
```

#### `udp_sender.py` (para EBAZ4205)
Script Python que roda no Linux embarcado:
- Lê dados do solver da BRAM (0x40000000)
- Converte Q14.28 para float
- Envia via UDP (192.168.1.100:5005)
- Taxa: 100 Hz

**Layout memória BRAM:**
```
0x00: speed_mech   (8 bytes)
0x08: ialpha       (8 bytes)
0x10: ibeta        (8 bytes)
0x18: flux_alpha   (8 bytes)
0x20: flux_beta    (8 bytes)
```

#### `udp_receiver.py` (para seu PC)
Recebe dados UDP e salva em CSV:
```bash
python3 udp_receiver.py
```

## Próximos Passos

### 1. Instalar Dependências
```bash
cd ~/Desktop/Projects/Hardware-in-the-Loop
./install_petalinux_deps.sh
```

### 2. Baixar Petalinux
- Acesse: https://www.xilinx.com/support/download/index.html/content/xilinx/en/downloadNav/embedded-design-tools.html
- Baixe: `petalinux-v2024.1-final-installer.run` (~10GB)
- Salve em `~/Downloads/`

### 3. Instalar Petalinux
```bash
cd ~/Downloads
chmod +x petalinux-v2024.1-final-installer.run
mkdir -p ~/xilinx/petalinux
./petalinux-v2024.1-final-installer.run -d ~/xilinx/petalinux
```

### 4. Seguir PETALINUX_GUIDE.md
Leia o guia completo para os próximos passos detalhados.

## Arquitetura Final

```
┌──────────────────────────────────────┐
│  EBAZ4205                            │
│                                      │
│  ┌────────────────────────────────┐ │
│  │ PL (FPGA)                      │ │
│  │  TIM_Solver → BRAM (porta B)   │ │
│  │      ↓                          │ │
│  │  BRAM dual-port                │ │
│  │      ↓ (porta A)                │ │
│  │  AXI BRAM Controller           │ │
│  └──────────┬─────────────────────┘ │
│             │ AXI HP0               │
│  ┌──────────▼─────────────────────┐ │
│  │ PS (ARM + Linux)               │ │
│  │  - udp_sender.py               │ │
│  │  - lê /dev/mem @ 0x40000000    │ │
│  │  - converte Q14.28 → float     │ │
│  └──────────┬─────────────────────┘ │
│             │ Ethernet              │
└─────────────┼───────────────────────┘
              │ UDP 192.168.1.100:5005
              │
┌─────────────▼───────────────────────┐
│  Seu PC                             │
│  - udp_receiver.py                  │
│  - salva CSV                        │
│  - GUI Tauri (futuro)               │
└─────────────────────────────────────┘
```

## Checklist Hardware EBAZ4205

- [ ] Resistor R2584 removido
- [ ] Resistor R2577 soldado (boot SD Card)
- [ ] Capacitores C585/C584 (se PHY precisa clock do PL)
- [ ] SD Card 4GB+ formatado (FAT32 + ext4)
- [ ] USB-UART conectado (TX=F19, RX=F20, GND)

## Troubleshooting Rápido

**Petalinux build falha com "ps7_nand_0 not found":**
```bash
vim components/plnx_workspace/device-tree/device-tree/system-conf.dtsi
# Mudar &ps7_nand_0 para &nfc0
```

**"Cannot open /dev/mem" no Linux:**
```bash
# Use UIO ao invés:
ls /dev/uio*  # deve mostrar /dev/uio0
```

**Ethernet não funciona:**
- Verifique cristal 25MHz e capacitores
- Check `dmesg | grep eth`
- Testar: `ethtool eth0`

## Contatos Úteis

- Blog referência: https://codeembedded.in/posts/fpga-zero-to-hero-vol-5-ebaz4205-chronicles/
- Xilinx Docs: https://docs.amd.com/
- Petalinux UG1144: https://docs.amd.com/r/en-US/ug1144-petalinux-tools-reference-guide
