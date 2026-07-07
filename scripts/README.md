# Scripts para Host PC (Ubuntu)

Este diretório contém scripts que rodam no seu PC de desenvolvimento (não na placa).

## Estrutura

```
scripts/
├── board.sh                  # Wrapper SSH não-interativo para a EBAZ4205
├── deploy_board.sh           # Envia bitstream + binários para a EBAZ4205
├── hil_fullstack_mock.py     # Mock C full-stack (V/F + NPC + IM_Model) vs .hilbin
├── hil-watchdog.py           # Watchdog do hil_controller na EBAZ4205
├── rebase_clean.sh           # Rebase + remove string de todas as mensagens de commit
├── serial_connect.sh         # Lista portas USB seriais e abre picocom
├── ssh_board.sh              # Abre sessão SSH na EBAZ4205
├── validate_hil_pwm.py       # Valida telemetria FPGA vs modelo C usando captura de PWM
├── setup/                    # Scripts de instalação e configuração
│   └── install_petalinux_deps.sh
├── build/                    # Scripts de build Vivado/PetaLinux (ver build/README.md)
├── vivado/                   # Scripts auxiliares de Vivado
│   └── jtag_reset.sh
└── test/                     # Scripts de teste e validação
    └── udp_receiver.py
```

## Placa (EBAZ4205)

### `board.sh`
Wrapper SSH não-interativo. Credenciais embutidas no arquivo — por isso ele
está em `.gitignore` e não é commitado.

```bash
./scripts/board.sh                          # shell interativo
./scripts/board.sh "comando shell"          # roda comando e sai
IP=192.168.15.20 ./scripts/board.sh ls      # override de IP
```

### `ssh_board.sh`
Abre uma sessão SSH interativa na placa.

```bash
./scripts/ssh_board.sh
IP=192.168.1.50 ./scripts/ssh_board.sh
```

### `deploy_board.sh`
Envia bitstream (`BOOT.BIN`) e binários compilados para a EBAZ4205.

```bash
./scripts/deploy_board.sh
IP=192.168.1.50 ./scripts/deploy_board.sh
```

### `serial_connect.sh`
Lista portas USB seriais disponíveis e abre `picocom` na escolhida (mata
instâncias anteriores do picocom antes de abrir).

```bash
./scripts/serial_connect.sh            # baud padrão: 115200
./scripts/serial_connect.sh 9600       # baud customizado
```

### `hil-watchdog.py`
Watchdog do processo `hil_controller` rodando na EBAZ4205 — monitora e
reinicia o controlador se ele travar/cair.

## Validação / modelos de referência

### `hil_fullstack_mock.py`
Compila e roda um mock nativo em C (V/F + modulação NPC ideal + `IM_Model`)
e compara contra um arquivo `.hilbin` capturado — usado na campanha de
validação para isolar erro de metodologia vs. erro real do solver.

```bash
python3 scripts/hil_fullstack_mock.py --help
```

### `validate_hil_pwm.py`
Valida a telemetria da FPGA contra o modelo C de referência, usando a
captura de eventos PWM (`REG_PWM_CAP_*` em `src/ps_app/gpio.h`) para
alinhar fase em vez de assumir portadora ideal.

## Setup

### `setup/install_petalinux_deps.sh`
Instala todas as dependências necessárias para PetaLinux no Ubuntu 24.04.

```bash
cd scripts/setup
./install_petalinux_deps.sh
```

## Vivado

### `vivado/jtag_reset.sh`
Reseta a EBAZ4205 (Zynq-7010) via JTAG usando `xsdb`. Requer Vivado/Vitis
instalado (com `xsdb` no `PATH`) e um adaptador JTAG conectado.

```bash
./scripts/vivado/jtag_reset.sh              # reset de sistema (padrão)
./scripts/vivado/jtag_reset.sh --halt       # reset e halt na primeira instrução
./scripts/vivado/jtag_reset.sh --cores      # reset só dos cores PS
./scripts/vivado/jtag_reset.sh --list       # lista alvos JTAG disponíveis
```

## Build

Ver `build/README.md` — scripts de build Vivado/PetaLinux ainda planejados;
por enquanto o fluxo reproduzível é via `make synth` / `make all-hardware`
na raiz do projeto (ver `README.md` principal).

## Git

### `rebase_clean.sh`
Faz rebase sobre uma branch base e remove uma string de todas as mensagens
de commit (ex.: remover assinatura de coautoria de um conjunto de commits).

```bash
./scripts/rebase_clean.sh "<string-a-remover>" [branch-base]
```

## Test

### `test/udp_receiver.py`
Recebe dados UDP do EBAZ4205 e salva em CSV.

```bash
cd scripts/test
python3 udp_receiver.py
```

**Configuração (script legado):**
- Porta: 5005, pacote único de 5 floats (20 bytes) — speed, ialpha, ibeta, flux_alpha, flux_beta

> **Desatualizado:** o protocolo atual do daemon (`src/ps_app/telemetry.h`)
> envia telemetria em **UDP:5006**, em bursts de 32 amostras por pacote, não
> mais um float por amostra em 5005 (5005 hoje é só comandos/status JSON,
> ver `docs/architecture.md` seção 3). Este script não decodifica o formato
> atual — use o gateway Go (`apps/hil-go`) ou `validate_hil_pwm.py` para
> capturar telemetria real.
