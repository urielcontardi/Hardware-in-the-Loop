# HIL Data Pipeline - EBAZ4205

Este documento define o contrato atual entre solver, DMA, daemon, gateway e plot.
Arquivos Vivado gerados (`syn/hil/ebaz4205/`) nao sao fonte do projeto: o TCL
canonico e `syn/hil/create_ebaz4205_project.tcl`.

## Taxas e clocks

| Item | Valor |
|---|---:|
| AXI/controle | 100 MHz |
| Solver | 200 MHz |
| Portadora PWM | 1 kHz |
| `CARRIER_MAX` | 50000 |
| Tick do controle V/F | 10 kHz |
| Taxa interna aproximada do solver | 7.69 MHz |
| Decimacao de telemetria | 77 |
| Taxa de aquisicao DMA/UDP | aproximadamente 100 ksample/s |
| Reducao para exibicao | bucket de 100 amostras |

O tick de 10 kHz do controle nao altera a portadora: a portadora permanece em 1 kHz.

## Fluxo completo

```text
HIL_AXI_Top (PL, 200 MHz)
  -> AXI4-Stream, frame de 256 bits
  -> width converter 256 -> 64 bits
  -> AXI DMA S2MM
  -> DDR reservada
  -> hil_controller (PS Linux)
  -> UDP, bursts de 32 amostras
  -> receiver Go
  -> buffer circular raw (cursor incremental, sem filtro)
  -> binario HTTP / chamada Wails
  -> frontend TypeScript
  -> plot, limitado a aproximadamente 20 FPS
```

## Controle PS para PL

O PS escreve referencias e parametros no IP `HIL_Regs_AXI`, base `0x43C00000`.
O projeto nao usa os antigos AXI GPIOs de referencia descritos em documentos legados.

| Offset | Campo |
|---:|---|
| `0x00` | `va_ref` |
| `0x04` | `vb_ref` |
| `0x08` | `vc_ref` |
| `0x0c` | controle PWM |
| `0x10` | tensao do barramento DC |
| `0x14` | torque de carga |

O DMA usa controle em `0x40400000`. Monitores auxiliares permanecem na faixa
`0x41200000`; os enderecos definitivos devem coincidir com o TCL e `src/ps_app/gpio.h`.

## Frame de telemetria PL

Cada amostra tem 256 bits/32 bytes:

| Bits | Campo |
|---:|---|
| `41:0` | corrente alpha, signed 42 bits |
| `83:42` | corrente beta, signed 42 bits |
| `125:84` | fluxo alpha, signed 42 bits |
| `167:126` | fluxo beta, signed 42 bits |
| `209:168` | velocidade mecanica, signed 42 bits |
| `241:210` | timestamp do HIL em ciclos, 32 bits |
| `255:242` | epoch do HIL, 14 bits |

O layout e decodificado em `src/ps_app/dma_telem.c`. Alterar o frame exige atualizar
RTL e daemon PS em conjunto. Nunca implante apenas um dos lados.

## Transporte PS para host

O DMA e armado em blocos de 128 frames. O daemon converte cada amostra para o
formato UDP compacto de 26 bytes e envia bursts de 32 amostras. O timestamp vem do
proprio frame PL; ele nao e interpolado no software.

O receptor Go solicita um buffer UDP de 4 MiB e valida o tamanho dos bursts. Perdas de
UDP continuam possiveis e devem ser observadas pelos contadores de sequencia/epoch.

## Exibicao e persistencia

A aquisicao permanece em aproximadamente 100 ksample/s e chega integralmente ao
frontend pelo transporte raw incremental. No navegador, o formato e binario para
evitar o custo de 100 mil objetos JSON por segundo. Nao ha filtro nem decimacao nesse
caminho. A memoria circular do backend retem aproximadamente tres segundos e o
frontend retem aproximadamente seis segundos para inspecao detalhada.

O `DisplayReducer` continua apenas como fallback JSON de baixa taxa. Para janelas
longas, o frontend constroi uma visao min/max separada; isso nao substitui nem altera
as amostras da janela raw.

Cada `Run` inicia o recorder raw antes do ring e do `DisplayReducer`. Os bursts
sao copiados para uma fila limitada e escritos por uma goroutine separada. `Stop`
faz flush, anexa os eventos PWM e promove o arquivo temporario para `.hilbin`.
O salvamento prioriza essa captura integral; o buffer reduzido e apenas fallback.
Os contadores `record_written` e `record_dropped` indicam se o disco acompanhou
a aquisicao.

## Build reproduzivel

```bash
make                 # RTL + Go + frontend + compilacao PS nativa
make vivado-check   # recria o projeto e valida conexoes criticas do BD
make synth           # recria projeto, sintetiza, implementa e exporta XSA
make all-hardware    # validacao host + Vivado + binarios ARM
```

`make synth` sempre chama `make vivado-project`. O preflight falha caso qualquer uma das
conexoes de timeline/PWM capture esteja ausente. Isso evita o comportamento do Vivado de
amarrar portas desconectadas em zero e ainda produzir uma execucao aparentemente valida.

## Fonte de verdade

- RTL e layout: `src/rtl/HIL_AXI_Top.vhd`
- Registradores e escalas PS: `src/ps_app/gpio.h`
- DMA e pacote UDP: `src/ps_app/dma_telem.h` e `dma_telem.c`
- Decoder/reducao host: `apps/hil-go/internal/frame/`
- Receptor: `apps/hil-go/internal/receiver/receiver.go`
- Block Design: `syn/hil/create_ebaz4205_project.tcl`
- Preflight: `syn/hil/bd_preflight.tcl`
