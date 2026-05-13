# EBAZ4205 — HIL Linux Boot (PetaLinux 2025.1 + Vivado 2025.1)

Tudo necessário para recompilar o design FPGA, gerar o Linux e gravar no SD card da EBAZ4205.

---

## Hardware

| Item | Especificação |
|------|--------------|
| Placa | EBAZ4205 (Zynq-7010) |
| FPGA | xc7z010clg400-1 |
| RAM | 256 MB DDR3 |
| Ethernet PHY | IP101GA via EMIO/PL (GMII 4-bit, 100Mbps) |
| Boot | SD card (SD0, MIO40–45) |
| Console UART | UART1 (MIO24=TX, MIO25=RX), 115200 8N1 — header J7 |

### Modificação de hardware obrigatória

A placa vem de fábrica configurada para boot por **NAND flash**. Para bootar pelo SD card é preciso mover o resistor **R2584 → R2577** na PCB (coloca MIO4 e MIO5 em VCC, selecionando SD boot).

### Conexão UART (J7)

```
J7 Pin 1 → VCC 3.3V  (não conecte)
J7 Pin 2 → TX placa  → RX do adaptador USB-serial
J7 Pin 3 → RX placa  → TX do adaptador USB-serial
J7 Pin 4 → GND       → GND do adaptador
```

```bash
picocom -b 115200 /dev/ttyUSB1    # ajuste o device conforme seu sistema
```

---

## Pré-requisitos (build completo)

| Ferramenta | Versão | Path padrão |
|-----------|--------|-------------|
| Vivado | 2025.1 | `/opt/Xilinx/2025.1/Vivado/bin/vivado` |
| PetaLinux | 2025.1 | `~/xilinx/petalinux/settings.sh` |

> Se os paths forem diferentes, edite as variáveis `VIVADO` e `PETALINUX_ENV` no `Makefile` raiz.

---

## Opção A — Gravar direto (imagens prontas)

Use quando não quiser recompilar. As imagens testadas estão em `sd_images/`:

```bash
# Na raiz do repositório:
make linux-flash SD=/dev/sdX    # substitua pelo device correto (ex: /dev/sda)
```

O script particiona o SD automaticamente:
- **p1** FAT32 256 MB → `BOOT.BIN`, `boot.scr`, `image.ub`
- **p2** EXT4 restante → rootfs

---

## Opção B — Build completo do zero

Reconstrói tudo: Vivado → síntese → PetaLinux → SD card.

```bash
# Na raiz do repositório (~90 min na primeira vez):
make linux-all-axi

# Depois de concluído, gravar:
make linux-flash SD=/dev/sdX
```

### O que `make linux-all-axi` faz

| Passo | Comando | O que faz |
|-------|---------|-----------|
| 1/5 | `make vivado-project` | Cria projeto Vivado com BD completo (PS7 + EMIO Ethernet + HIL_Regs_AXI + DSP48E1) |
| 2/5 | `make synth` | Síntese + implementação + exporta `ebaz4205.xsa` e `.bit` |
| 3/5 | `make linux-config` | Importa XSA no PetaLinux com `--silentconfig` (preserva configs) |
| 4/5 | `make linux-build` | Compila kernel, rootfs e FSBL |
| 5/5 | `make linux-package` | Empacota `BOOT.BIN` (FSBL + bitstream + U-Boot) |

### Passo a passo manual (se preferir controle individual)

```bash
make vivado-project          # Cria ebaz4205.xpr
make synth                   # Gera ebaz4205.xsa e ebaz4205_wrapper.bit
make linux-config            # Importa XSA no PetaLinux
make linux-build             # Build (~30-60 min)
make linux-package           # Empacota BOOT.BIN
make linux-update-sdimages   # Copia para sd_images/
make linux-flash SD=/dev/sdX # Grava SD card
```

---

## Detalhes de implementação importantes

### Por que usamos o XSA gerado pelo Vivado 2025.1

O FSBL (First Stage Boot Loader) inicializa o DDR3 usando valores de calibração específicos do hardware. O XSA gerado pelo Vivado 2025.1 (`ebaz4205.xsa`) contém a calibração correta para esta placa:

```
DDR PHY calibration: 0x44E458D3  ← valor correto para este board
```

O Makefile usa sempre o XSA da síntese atual para compilar o FSBL.

### Por que o Ethernet precisa de EMIO

O PHY IP101GA da EBAZ4205 está conectado ao PL (FPGA), não diretamente ao PS via MIO. O Block Design inclui:
- `xlconcat_0` — agrega RXD[3:0] em barramento 8-bit para o PS
- `xlslice_0` — fatia TXD[7:0] → 4-bit para o PHY
- MDIO via EMIO (MDC + MDIO)
- Clock 25 MHz para o PHY gerado pelo PL (FCLK3)

O node PHY no device tree (`system-user.dtsi`) está configurado para o IP101GA no endereço MDIO 0.

### HIL_Regs_AXI

Registrador AXI4-Lite customizado que expõe controles do HIL para o PS:

| Offset | Registrador | Formato |
|--------|------------|---------|
| 0x00 | `va_ref` | signed int32 |
| 0x04 | `vb_ref` | signed int32 |
| 0x08 | `vc_ref` | signed int32 |
| 0x0C | `pwm_ctrl` | bit0=enable, bit1=fault, [31:2]=decimation |
| 0x10 | `vdc_word` | Q18.14 (V) |
| 0x14 | `torque_word` | Q18.14 (N·m) |

**Base address:** `0x43C00000` (definido no Block Design e em `src/ps_app/gpio.h`)

---

## Boot e login

Após gravar e ligar a placa, aguarde ~15 segundos. No terminal serial:

```
PetaLinux 2025.1 ebaz4205_petalinux ttyPS0

ebaz4205_petalinux login: root
```

Login: `root` (sem senha no build padrão).

Via SSH (após DHCP obter IP):
```bash
ssh root@<IP-da-placa>
```

---

## Atualizar só o bitstream (sem rebuild completo)

Quando só o design PL mudar e o Linux não precisar ser recompilado:

```bash
make vivado-project   # apenas se o projeto não existir
make synth            # nova síntese → novo ebaz4205.xsa + .bit
make linux-config     # atualiza XSA no PetaLinux
make linux-build      # recompila FSBL com novo XSA
make linux-package    # novo BOOT.BIN
make linux-update-sdimages && make linux-flash SD=/dev/sdX
```

---

## Estrutura do diretório

```
syn/hil/
├── create_ebaz4205_project.tcl   # Recria projeto Vivado completo do zero
├── run_impl_export.tcl           # Síntese + implementação + exporta XSA
├── resynth.tcl                   # Re-síntese sem recriar o projeto
├── ebaz4205_board.xdc            # Constraints: pinos, EMIO Ethernet, LEDs
├── flash_sd.sh                   # Particiona e grava SD card
├── sd_images/                    # Imagens pré-compiladas e testadas
│   ├── BOOT.BIN                  # FSBL + bitstream + U-Boot
│   ├── boot.scr                  # Script U-Boot
│   ├── image.ub                  # Kernel FIT image + DTB
│   └── rootfs.tar.gz             # Rootfs EXT4
└── ebaz4205_petalinux/
    └── project-spec/             # Configurações versionadas
        ├── configs/config        # DDR 256MB, UART1, SD0, FIT offset 0x6000000
        └── meta-user/
            └── recipes-bsp/device-tree/files/system-user.dtsi  # PHY node IP101GA
```

---

## Bugs conhecidos e soluções

| Sintoma | Causa | Solução aplicada automaticamente |
|---------|-------|----------------------------------|
| `ps7_nand_0: label not found` | PetaLinux 2024.2+ referencia label inexistente | `make linux-config` aplica `sed` automaticamente |
| `No Valid Environment Area found` (U-Boot) | U-Boot sem área de env na FAT | Normal — usa defaults |
| Ethernet não sobe | PHY node ausente no DTB | Configurado em `system-user.dtsi` |
| Placa não boota nada na serial | FSBL com DDR calibração errada | `make linux-config` usa o XSA correto |
| UART sem saída | TX/RX invertido no adaptador | Trocar RX↔TX no cabo |
