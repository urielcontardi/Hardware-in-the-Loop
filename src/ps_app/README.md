# HIL PS Application

Daemon C executado no ARM Linux da EBAZ4205. Ele controla o V/F, configura o PL
por `HIL_Regs_AXI`, recebe frames via AXI DMA e publica telemetria UDP.

O contrato completo do pipeline esta em `syn/hil/HIL_ARCHITECTURE.md`.

## Build

```bash
make ps-native-check  # validacao no host
make ps-build         # cross-build Cortex-A9
make ps-deploy IP=192.168.15.8
```

A toolchain ARM vem do SDK PetaLinux. Sem ela, `make ps-build` usa o ambiente
configurado pelo Makefile raiz quando disponivel.

## Taxas

| Item | Valor |
|---|---:|
| Portadora PWM | 1 kHz |
| Tick do controle V/F | 10 kHz |
| `CARRIER_MAX` | 50000 |
| Default DMA `decim` | 77 |
| Aquisicao DMA/UDP | aproximadamente 100 ksample/s |

O tick V/F de 10 kHz nao muda a portadora PWM de 1 kHz.

## Portas UDP

| Porta | Uso |
|---:|---|
| 5005 | comandos JSON e estado |
| 5006 | telemetria do solver |
| 5007 | eventos de transicao PWM |

Comandos principais na porta 5005:

```json
{"cmd":"set","freq_hz":30,"vdc_v":300,"torque_nm":0,"accel_s":1,"enable":1,"decim":77,"telem_dst":"192.168.15.11"}
{"cmd":"get"}
{"cmd":"run"}
{"cmd":"pause"}
{"cmd":"stop"}
{"cmd":"reset"}
{"cmd":"telem","dst":"192.168.15.11"}
{"cmd":"ping"}
{"cmd":"shutdown"}
```

`stop` para o motor e mantem o daemon ativo. `shutdown` encerra o processo.

## Hardware

Controle PS para PL usa `HIL_Regs_AXI` em `0x43C00000`. Os AXI GPIOs em
`0x41200000` a `0x41220000` sao apenas monitores auxiliares.

O DMA S2MM usa `0x40400000` e frames de 32 bytes:

```text
[41:0] ialpha, [83:42] ibeta, [125:84] flux_alpha,
[167:126] flux_beta, [209:168] speed,
[241:210] timestamp de 100 MHz, [255:242] epoch
```

O daemon arma blocos de 128 frames, decodifica Q14.28 e envia bursts UDP de
32 amostras. RTL e daemon devem ser implantados juntos quando o layout mudar.

## Arquivos

- `main.c`: ciclo de controle e protocolo de comandos
- `gpio.c/h`: registradores AXI e captura PWM
- `dma_telem.c/h`: DMA e decoder do frame PL
- `telemetry.c/h`: transporte UDP das amostras
- `vf_ctrl.c/h`: rampa e lei V/F
- `pwm_events.c/h`: stream de eventos PWM
- `supervisor.c`: supervisao do daemon
