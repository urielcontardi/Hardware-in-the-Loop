# HIL PS Application — V/F Controller + UDP Server

Aplicação C que roda no ARM Linux (PS) do EBAZ4205. Implementa um controlador
V/F em malha aberta a 1 kHz e expõe uma interface UDP para configuração e
leitura de dados do solver.

## Estrutura

```
src/ps_app/
├── main.c      — inicialização, timer 1 kHz, servidor UDP
├── gpio.c/h    — acesso ao hardware via /dev/mem (AXI GPIO)
├── vf_ctrl.c/h — controlador V/F malha aberta
└── Makefile    — targets de build, deploy e limpeza
```

## Dependências (toolchain)

Cross-compilação para ARM Cortex-A9 usando a toolchain gerada pelo PetaLinux SDK.

### Gerar o SDK (uma vez após o primeiro `make linux-build`)

```bash
cd syn/hil/ebaz4205_petalinux
source ~/xilinx/petalinux/settings.sh
petalinux-build --sdk
petalinux-package sysroot
```

O SDK é instalado em:
```
syn/hil/ebaz4205_petalinux/images/linux/sdk/
```

## Como compilar

### Via Makefile raiz (recomendado)

```bash
# Ativa SDK e compila
make ps-build

# Compila + copia para a placa
make ps-deploy IP=192.168.1.100

# Limpa binários
make ps-clean
```

### Manualmente

```bash
# 1. Ativa a toolchain
source syn/hil/ebaz4205_petalinux/images/linux/sdk/environment-setup-cortexa9t2hf-neon-xilinx-linux-gnueabi

# 2. Compila
cd src/ps_app
make

# 3. Copia para a placa
make deploy IP=192.168.1.100
```

### Build nativo (x86, sem hardware — para testes de compilação)

```bash
cd src/ps_app
make native
```

## Como usar na placa

```bash
# No terminal da placa (via picocom ou SSH)
sudo ./hil_controller
```

A aplicação escuta na porta UDP **5005**.

## Protocolo UDP

### POST — configurar parâmetros

```json
{"cmd":"set","freq_hz":30.0,"vdc_v":300.0,"torque_nm":0.0,"enable":1,"decim":0}
```

| Campo        | Tipo  | Descrição                                              |
|--------------|-------|--------------------------------------------------------|
| `freq_hz`    | float | Frequência elétrica de saída [Hz]                      |
| `vdc_v`      | float | Tensão DC do barramento [V]                            |
| `torque_nm`  | float | Torque de carga [N·m] (passado ao solver)              |
| `enable`     | int   | 0 = desligado, 1 = ligado                              |
| `decim`      | int   | Decimation ratio do DMA (0 = default 375 → 10 kHz)    |

Resposta: `{"status":"ok"}`

### GET — ler estado do solver

```json
{"cmd":"get"}
```

Resposta:
```json
{
  "speed_rad_s": 12.34,
  "ialpha_A":    1.23,
  "ibeta_A":     0.98,
  "flux_alpha_Wb": 0.45,
  "flux_beta_Wb":  0.43,
  "freq_hz": 30.0,
  "vdc_v":   300.0,
  "enable":  1
}
```

### STOP — encerrar a aplicação

```json
{"cmd":"stop"}
```

### Exemplos com `nc` (netcat)

```bash
# Ligar a 30 Hz, 300 V
echo '{"cmd":"set","freq_hz":30,"vdc_v":300,"enable":1}' | nc -u -w1 192.168.1.100 5005

# Ler estado
echo '{"cmd":"get"}' | nc -u -w1 192.168.1.100 5005

# Desligar
echo '{"cmd":"set","enable":0}' | nc -u -w1 192.168.1.100 5005
```

## Parâmetros internos

| Parâmetro      | Valor     | Arquivo     |
|----------------|-----------|-------------|
| `FREQ_NOM_HZ`  | 50 Hz     | vf_ctrl.c   |
| `V_NOM_PU`     | 1.0 pu    | vf_ctrl.c   |
| `CARRIER_MAX`  | ±75000    | gpio.h      |
| `VDC_MAX_V`    | 600 V     | vf_ctrl.c   |
| `TORQUE_MAX_NM`| 50 N·m    | vf_ctrl.c   |
| `MON_SCALE`    | 1/2^18    | main.c      |

> **CARRIER_MAX:** 150 MHz / (1 kHz × 2) = 75000 — representa 100% de modulação.
>
> **MON_SCALE:** os valores de monitor são os 32 MSBs do formato Q14.28 (42 bits),
> portanto dividir por 2^18 converte para a grandeza real.

## Mapa de registradores AXI GPIO

| Periférico          | Endereço base | CH1 (+0x000)     | CH2 (+0x008)      |
|---------------------|---------------|------------------|-------------------|
| `axi_gpio_monitor_1`| `0x41200000`  | `ialpha_mon`     | `ibeta_mon`       |
| `axi_gpio_monitor_2`| `0x41210000`  | `flux_alpha_mon` | `flux_beta_mon`   |
| `axi_gpio_monitor_3`| `0x41220000`  | `speed_mon`      | `data_valid_mon`  |
| `axi_gpio_vdc_torque`| `0x41230000` | `vdc_word`       | `torque_word`     |
| `axi_gpio_vref_ab`  | `0x41240000`  | `va_ref`         | `vb_ref`          |
| `axi_gpio_vref_c`   | `0x41250000`  | `vc_ref`         | `pwm_ctrl`        |

`pwm_ctrl`: `bit[0]` = enable, `bit[1]` = clear_fault, `bits[31:2]` = decim_ratio
