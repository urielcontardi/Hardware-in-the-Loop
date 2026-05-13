# HIL AXI Architecture — EBAZ4205 (Zynq-7010)

Documentação da arquitetura Hardware-in-the-Loop com controle PS↔PL via AXI.

---

## Visão Geral

O PS (ARM Cortex-A9, Linux/PetaLinux) executa o algoritmo V/F e escreve as referências de tensão no PL via AXI GPIO. O PL gera a interrupção de sincronismo, faz a modulação NPC, converte os estados do inversor em tensão e roda o modelo de motor (TIM_Solver). Os resultados são transferidos para a DDR via AXI DMA.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PS — ARM Cortex-A9 (Linux)                          │
│                                                                             │
│  ┌─────────────────────┐    IRQ     ┌────────────────────────────────────┐  │
│  │   V/F Controller    │◄───────────│  carrier_tick_o → IRQ_F2P[0]       │  │
│  │   (software, C)     │            └────────────────────────────────────┘  │
│  │                     │                                                    │
│  │  va = A·sin(θ)      │  AXI GPIO  ┌────────────────────────────────────┐  │
│  │  vb = A·sin(θ-2π/3) ├───────────►│  axi_gpio_vref_ab  (va, vb)        │  │
│  │  vc = A·sin(θ+2π/3) ├───────────►│  axi_gpio_vref_c   (vc, ctrl)      │  │
│  │                     ├───────────►│  axi_gpio_vdc_torque (vdc, torque) │  │
│  │                     │            └────────────────────────────────────┘  │
│  │                     │  AXI GPIO  ┌────────────────────────────────────┐  │
│  │  (monitor/debug)    │◄───────────│  axi_gpio_monitor_{1,2,3}          │  │
│  │                     │            └────────────────────────────────────┘  │
│  │                     │  mmap DDR  ┌────────────────────────────────────┐  │
│  │  (ler amostras)     │◄───────────│  DMA buffer (N × 32 bytes)         │  │
│  └─────────────────────┘            └────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
         │ AXI GP0 (M)                                    ▲ AXI HP0 (S)
         ▼                                                │
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PL — Zynq-7010 Fabric                              │
│                                                                             │
│  ┌─────────────────┐  va/vb/vc  ┌──────────────-┐  gate   ┌──────────────┐  │
│  │  AXI SmartConn  │───────────►│  NPCManager   ├────────►│NPC_to_Voltage│  │
│  │  (7 slaves)     │  (±25000)  │  (1 kHz tri   │  4b×3   │  ±Vdc/2      │  │
│  │                 │            │   portadora)  │         └──────┬───────┘  │
│  │                 │            │               │                │ V_abc    │
│  │                 │◄──irq──────│ carrier_tick_o│                ▼          │
│  │                 │            └───────────────┘        ┌──────────────┐   │
│  │                 │  vdc/torque                         │  TIM_Solver  │   │
│  │                 │────────────────────────────────────►│  (motor IM   │   │
│  │                 │                                     │   3-fase)    │   │
│  │                 │                                     └──────┬───────┘   │
│  │                 │                                            │ data_valid│
│  │                 │  AXI4-Stream (256b)                        ▼           │
│  │                 │◄─────────────────────────────────── ┌──────────────┐   │
│  │                 │                                     │  HIL_AXI_Top │   │
│  │                 │                                     │  (stream reg)│   │
│  └──────┬──────────┘                                     └──────────────┘   │
│         │ AXI SmartConn (DMA→HP0)                                           │
│         ▼                                                                   │
│  ┌──────────────┐  S2MM   ┌───────────┐                                     │
│  │   AXI DMA    │◄────────│  Stream   │                                     │
│  │   (S2MM)     │         │  (256b)   │                                     │
│  └──────┬───────┘         └───────────┘                                     │
│         │ M_AXI_S2MM (AXI4, 64b) → HP0 → DDR                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Componentes do Block Design

| Instância | IP Xilinx | Função |
|-----------|-----------|--------|
| `processing_system7_0` | PS7 | ARM + DDR + clocks + AXI masters/slaves |
| `axi_smartconnect_0` | SmartConnect | AXI GP0 → 7 periféricos PL |
| `axi_smartconnect_1` | SmartConnect | AXI DMA M_AXI → HP0 (DMA→DDR) |
| `axi_gpio_vref_ab` | AXI GPIO | Ch1=va_ref, Ch2=vb_ref (escrita PS→PL) |
| `axi_gpio_vref_c` | AXI GPIO | Ch1=vc_ref, Ch2=pwm_ctrl (escrita PS→PL) |
| `axi_gpio_vdc_torque` | AXI GPIO | Ch1=vdc_word, Ch2=torque_word (escrita PS→PL) |
| `axi_gpio_monitor_1` | AXI GPIO | Ch1=ialpha, Ch2=ibeta (leitura PL→PS) |
| `axi_gpio_monitor_2` | AXI GPIO | Ch1=flux_alpha, Ch2=flux_beta (leitura PL→PS) |
| `axi_gpio_monitor_3` | AXI GPIO | Ch1=speed, Ch2=data_valid (leitura PL→PS) |
| `axi_dma_0` | AXI DMA | S2MM apenas (stream PL → DDR), sem SG, 256-bit |
| `hil_axi_top_0` | HIL_AXI_Top | Wrapper: NPCManager + TIM_Solver + AXI Stream |

---

## Mapa de Endereços AXI

> **Atenção:** os endereços abaixo são atribuídos automaticamente pelo Vivado (`assign_bd_address`).
> Confirme os valores reais no **Address Editor** após síntese, ou via `/proc/device-tree`.

| Periférico | Endereço base | Tamanho |
|-----------|---------------|---------|
| `axi_gpio_vref_ab` | `0x4124_0000` | 64 KB |
| `axi_gpio_vref_c` | `0x4125_0000` | 64 KB |
| `axi_gpio_vdc_torque` | `0x4123_0000` | 64 KB |
| `axi_gpio_monitor_1` | `0x4120_0000` | 64 KB |
| `axi_gpio_monitor_2` | `0x4121_0000` | 64 KB |
| `axi_gpio_monitor_3` | `0x4122_0000` | 64 KB |
| `axi_dma_0` (controle S_AXI_LITE) | `0x4040_0000` | 64 KB |
| DMA → DDR (S2MM destino) | `0x0000_0000` | 256 MB |

### Registradores AXI GPIO (offset interno)

Cada bloco AXI GPIO tem dois canais de 32 bits:

| Offset | Registrador |
|--------|-------------|
| `+0x000` | Canal 1 — DATA |
| `+0x008` | Canal 2 — DATA |
| `+0x004` | Canal 1 — TRI (direção: 0=output, 1=input) |
| `+0x00C` | Canal 2 — TRI |

---

## Registradores de Escrita (PS → PL)

### `axi_gpio_vref_ab` — Referências de tensão A e B

| Canal | Offset | Campo | Formato | Descrição |
|-------|--------|-------|---------|-----------|
| Ch1 | `+0x000` | `va_ref[31:0]` | signed 32b | Referência fase A (±CARRIER_MAX = ±25000) |
| Ch2 | `+0x008` | `vb_ref[31:0]` | signed 32b | Referência fase B |

### `axi_gpio_vref_c` — Referência C e controle PWM

| Canal | Offset | Campo | Formato | Descrição |
|-------|--------|-------|---------|-----------|
| Ch1 | `+0x000` | `vc_ref[31:0]` | signed 32b | Referência fase C |
| Ch2 | `+0x008` | `pwm_ctrl[1:0]` | bits | bit[0]=enable, bit[1]=clear_fault |

### `axi_gpio_vdc_torque` — Tensão DC e torque de carga

| Canal | Offset | Campo | Formato | Descrição |
|-------|--------|-------|---------|-----------|
| Ch1 | `+0x000` | `vdc_word[31:0]` | Q31 signed | Tensão do barramento DC (sign-ext p/ 42b no PL) |
| Ch2 | `+0x008` | `torque_word[31:0]` | Q31 signed | Torque de carga mecânico |

**Escala de referência:**
- `CARRIER_MAX = CLK_FREQ / PWM_FREQ / 2 = 50_000_000 / 1_000 / 2 = 25000`
- 100% modulação = `va_ref = ±25000`
- 85% modulação = `va_ref = ±21250`

---

## Registradores de Leitura (PL → PS) — Monitoramento

> Estes registradores refletem os **32 bits mais significativos** das saídas de 42 bits do TIM_Solver.
> São atualizados a cada amostra válida (`data_valid = 1`), ou seja, a cada período do solver.

### `axi_gpio_monitor_1` — Correntes alpha-beta

| Canal | Campo | Unidade |
|-------|-------|---------|
| Ch1 | `ialpha[31:0]` | A (ponto fixo Q31) |
| Ch2 | `ibeta[31:0]` | A (ponto fixo Q31) |

### `axi_gpio_monitor_2` — Fluxos rotóricos

| Canal | Campo | Unidade |
|-------|-------|---------|
| Ch1 | `flux_rotor_alpha[31:0]` | Wb (ponto fixo Q31) |
| Ch2 | `flux_rotor_beta[31:0]` | Wb (ponto fixo Q31) |

### `axi_gpio_monitor_3` — Velocidade e validade

| Canal | Campo |
|-------|-------|
| Ch1 | `speed_mech[31:0]` (rad/s, ponto fixo Q31) |
| Ch2 | `data_valid` (bit[0]: 1 = nova amostra disponível) |

---

## AXI DMA — Registradores S2MM

Base: `0x4040_0000`

| Offset | Registrador | Descrição |
|--------|------------|-----------|
| `+0x030` | `S2MM_DMACR` | Control: bit[0]=RS (run/stop) |
| `+0x034` | `S2MM_DMASR` | Status: bit[12]=IOC_IRQ (transfer complete) |
| `+0x048` | `S2MM_DA` | Destination Address (endereço físico DDR) |
| `+0x058` | `S2MM_LENGTH` | Número de bytes a transferir |

**Fluxo de operação:**

```
1. PS arma o DMA:
   S2MM_DMACR = 0x0001          (RS=1, iniciar)
   S2MM_DA    = 0x3E000000      (endereço físico do buffer DDR)
   S2MM_LENGTH = N * 32         (N amostras × 32 bytes/amostra)

2. PL produz dados (TIM_Solver → HIL_AXI_Top → AXI4-Stream → DMA)

3. PS aguarda conclusão (polling):
   while (S2MM_DMASR & 0x1000 == 0) { /* aguarda IOC_IRQ */ }

4. PS lê buffer DDR via mmap:
   buffer = mmap(0x3E000000, N*32, ...)
   for (i = 0; i < N; i++) {
       HilSample s = buffer[i];
       /* processar s.ialpha, s.ibeta, ... */
   }

5. Repetir: rearmar DMA e aguardar próxima IRQ
```

---

## Layout do Buffer DDR — `HilSample`

Cada amostra ocupa **32 bytes** (256 bits = 1 beat AXI4-Stream):

```
Bits [255:210] — padding (zeros)
Bits [209:168] — speed_mech     (42 bits, Q42 signed)
Bits [167:126] — flux_rotor_beta (42 bits, Q42 signed)
Bits [125: 84] — flux_rotor_alpha (42 bits, Q42 signed)
Bits [ 83: 42] — ibeta           (42 bits, Q42 signed)
Bits [ 41:  0] — ialpha          (42 bits, Q42 signed)
```

Estrutura C equivalente (leitura do buffer DDR):

```c
#include <stdint.h>

typedef struct {
    int64_t ialpha;          /* bits [63:0]   — só 42b válidos, MSB-aligned */
    int64_t ibeta;           /* bits [127:64] */
    int64_t flux_alpha;      /* bits [191:128] */
    int64_t flux_beta;       /* bits [255:192] — apenas 42b válidos */
    /* nota: speed está nos próximos 42b, mas o beat é 256b total */
} __attribute__((packed)) HilSample;

/* Extrair valor real (42b → double):
 * O TIM_Solver usa Q42 com escala parametrizada via MOTOR_* generics.
 * Para converter: valor_real = (double)raw / (1LL << 41);
 * (ajustar conforme escala real do solver)
 */
```

> **Nota:** O mapeamento exato dos bits no beat de 256 bits está em `HIL_AXI_Top.vhd`:
> `axis_tdata_r[41:0]=ialpha`, `[83:42]=ibeta`, `[125:84]=flux_alpha`,
> `[167:126]=flux_beta`, `[209:168]=speed`, `[255:210]=zeros`.

---

## Sincronismo IRQ ↔ NPCModulator

```
Portadora triangular (1 kHz, CARRIER_MAX=25000):

  25000 ┤     /\        /\
        │    /  \      /  \
        │   /    \    /    \
      0 ┤──/──────\──/──────\──► tempo
          ↑        ↑
          valley   valley
          │        │
          ├──► carrier_tick_o = 1 pulso (1 ciclo de clock)
          │    → IRQ_F2P[0] → PS acorda ISR
          │
          └──► NPCModulator trava va/vb/vc do ciclo anterior
               (referencias escritas pelo PS no ciclo anterior)

Latência total: PS escreve refs → PL latch no valley seguinte (~1ms depois)
Isso é intencional: PS tem todo o período entre IRQs para calcular e escrever.
```

**Sequência na ISR do PS:**

```c
void carrier_isr(int sig) {
    theta += 2*M_PI * f0 / 1000.0;    /* 1. atualizar ângulo */
    double va =  A * sin(theta);       /* 2. calcular V/F */
    double vb =  A * sin(theta - 2*M_PI/3);
    double vc =  A * sin(theta + 2*M_PI/3);

    /* 3. escalar para ±CARRIER_MAX = ±25000 */
    int32_t va_q = (int32_t)(va * 25000);
    int32_t vb_q = (int32_t)(vb * 25000);
    int32_t vc_q = (int32_t)(vc * 25000);

    /* 4. escrever via AXI GPIO (devmem/mmap) */
    gpio_vref_ab[0] = va_q;   /* Ch1 */
    gpio_vref_ab[2] = vb_q;   /* Ch2 */
    gpio_vref_c[0]  = vc_q;
}
```

---

## Código C — Acesso aos Periféricos (mmap)

```c
#include <stdio.h>
#include <stdint.h>
#include <fcntl.h>
#include <sys/mman.h>

#define PAGE_SIZE    4096
#define GPIO_VREF_AB 0x40000000
#define GPIO_VREF_C  0x40010000
#define GPIO_VDC_TRQ 0x40020000
#define GPIO_MON1    0x40030000
#define AXI_DMA_BASE 0x40400000
#define DDR_BUF_PHYS 0x3E000000
#define DDR_BUF_SIZE (1024 * 32)   /* 1024 amostras */

static int mem_fd = -1;

void *map_periph(uint32_t base) {
    return mmap(NULL, PAGE_SIZE, PROT_READ|PROT_WRITE, MAP_SHARED,
                mem_fd, base);
}

int main(void) {
    mem_fd = open("/dev/mem", O_RDWR | O_SYNC);

    volatile uint32_t *gpio_vref_ab  = map_periph(GPIO_VREF_AB);
    volatile uint32_t *gpio_vref_c   = map_periph(GPIO_VREF_C);
    volatile uint32_t *gpio_vdc_trq  = map_periph(GPIO_VDC_TRQ);
    volatile uint32_t *gpio_mon1     = map_periph(GPIO_MON1);
    volatile uint32_t *dma           = map_periph(AXI_DMA_BASE);
    volatile uint8_t  *ddr_buf       = mmap(NULL, DDR_BUF_SIZE,
                                            PROT_READ, MAP_SHARED,
                                            mem_fd, DDR_BUF_PHYS);

    /* Configurar vdc e torque iniciais */
    gpio_vdc_trq[0] = 0x40000000;  /* vdc = 0.5 em Q31 ≈ 380 V (ajustar) */
    gpio_vdc_trq[2] = 0x00000000;  /* torque de carga = 0 */

    /* Habilitar PWM */
    gpio_vref_c[2] = 0x00000001;   /* pwm_ctrl: enable=1 */

    /* Armar DMA para 1024 amostras */
    dma[0x030/4] = 0x0001;                 /* S2MM_DMACR: RS=1 */
    dma[0x048/4] = DDR_BUF_PHYS;           /* S2MM_DA */
    dma[0x058/4] = DDR_BUF_SIZE;           /* S2MM_LENGTH */

    /* Loop V/F — normalmente na ISR; aqui simplificado */
    double theta = 0.0, A = 21250.0, f0 = 10.0; /* 10 Hz */
    for (int i = 0; i < 10000; i++) {
        theta += 2*3.14159265 * f0 / 1000.0;
        gpio_vref_ab[0] = (int32_t)(A * sin(theta));
        gpio_vref_ab[2] = (int32_t)(A * sin(theta - 2.094395));
        gpio_vref_c[0]  = (int32_t)(A * sin(theta + 2.094395));
        usleep(1000);  /* 1 ms (substituir por wait na IRQ) */
    }

    /* Aguardar DMA concluir (polling) */
    while ((dma[0x034/4] & 0x1000) == 0);

    /* Ler primeira amostra */
    int64_t *samples = (int64_t *)ddr_buf;
    printf("ialpha raw: %lld\n", samples[0]);

    return 0;
}
```

Compilar no host (cross-compile):
```bash
arm-linux-gnueabihf-gcc -O2 -o hil_ctrl hil_ctrl.c -lm
# Copiar para o target via SCP/SD
```

---

## Device Tree — Reserva de Memória DDR para DMA

Adicionar em `system-user.dtsi` (PetaLinux):

```dts
/ {
    reserved-memory {
        #address-cells = <1>;
        #size-cells = <1>;
        ranges;

        hil_dma_buf: buffer@3e000000 {
            reg = <0x3e000000 0x01000000>;  /* 16 MB reservados */
            no-map;
        };
    };
};
```

O endereço físico `0x3E000000` deve ser usado em `S2MM_DA` e no `mmap` do PS.

---

## Parâmetros do Generics HIL_AXI_Top

| Generic | Valor padrão | Descrição |
|---------|-------------|-----------|
| `CLK_FREQ` | 50_000_000 | Clock do PL (FCLK0 da EBAZ4205) |
| `PWM_FREQ` | 1_000 | Frequência da portadora NPC (Hz) |
| `NPC_DW` | 32 | Largura das referências de tensão |
| `TIM_DW` | 42 | Largura do ponto fixo do solver |
| `DISC_STEP` | 1.0/1000.0 | Passo de discretização do solver (s) |
| `MOTOR_RS` | 0.435 | Resistência do estator (Ω) |
| `MOTOR_RR` | 0.2826 | Resistência do rotor (Ω) |
| `MOTOR_LS` | 3.1364e-3 | Indutância de dispersão do estator (H) |
| `MOTOR_LR` | 6.3264e-3 | Indutância de dispersão do rotor (H) |
| `MOTOR_LM` | 109.9442e-3 | Indutância mútua (H) |
| `MOTOR_J` | 0.192 | Momento de inércia (kg·m²) |
| `MOTOR_NPP` | 2.0 | Número de pares de polos |

---

## Build e Flash

```bash
cd syn/hil

# 1. Recriar projeto Vivado (HIL_AXI_Top + block design completo)
vivado -mode batch -source create_ebaz4205_project.tcl

# 2. Sintetizar, implementar e exportar XSA
vivado -mode batch -source run_impl_export.tcl

# 3. Atualizar PetaLinux com novo hardware
cd ebaz4205_petalinux
petalinux-config --get-hw-description=../ebaz4205.xsa
petalinux-build
petalinux-package boot --force \
    --fsbl ./images/linux/zynq_fsbl.elf \
    --fpga ./images/linux/system.bit \
    --u-boot ./images/linux/u-boot.elf

# 4. Gravar SD
cd ..
sudo ./flash_sd.sh /dev/sdX
```

---

## Limitações e Melhorias Futuras

| Item | Status | Descrição |
|------|--------|-----------|
| Fault readback | Ausente | `fault_o`, `fs_fault_o`, `minw_fault_o` do NPCManager não mapeados no PS |
| DMA interrupt | Polling | `s2mm_introut` não conectado ao IRQ_F2P; PS faz polling em `S2MM_DMASR` |
| DDR reservation | Manual | Endereço `0x3E000000` hardcoded; device tree não gerado automaticamente |
| IRQ-driven VF | ISR Linux | Usar `UIO` ou `signal(SIGIO)` para latência determinística |
| Escala Q real | TBD | Fator de escala exato das saídas do TIM_Solver a confirmar com parâmetros do motor |
