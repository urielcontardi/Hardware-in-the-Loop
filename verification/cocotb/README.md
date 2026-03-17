# Plano de Validação — TIM_Solver (VHDL)

Este documento descreve a estratégia de verificação e validação do solver VHDL de
motor de indução (`TIM_Solver`), desde testes unitários até integração final na FPGA.

---

## Filosofia de Validação

A confiança no modelo VHDL é construída em camadas.  O modelo C/C++ é a **referência
dourada** (já validado contra resultados analíticos/PSIM).  O VHDL é o **DUT**.
O Python (cocotb) é o orquestrador: aplica os **mesmos estímulos** a ambos e compara
as saídas passo a passo.

```
                     ┌─────────────────────────────────────────┐
                     │            Python (cocotb)              │
                     │                                         │
  VFControl ─────────┼──► va, vb, vc, tload (step n)          │
  (estímulo)         │        │                  │             │
                     │        ▼                  ▼             │
                     │  C model (.so)      VHDL/GHDL           │
                     │  (ctypes)           (TIM_Solver)        │
                     │  ref_state          vhdl_state          │
                     │        │                  │             │
                     │        └────────┬─────────┘             │
                     │                 ▼                       │
                     │          Comparação (NRMSE, MAE)        │
                     │          CSV  →  HTML report            │
                     └─────────────────────────────────────────┘
```

**Premissa central:** se o modelo VHDL (aritmética em ponto-fixo Q14.28, 42 bits)
divergir do modelo C (ponto-flutuante double), a diferença vem de erros de
quantização ou de lógica incorreta no solver — e **não** de um modelo de referência
duvidoso.

---

## Hierarquia de Testes

| Nível | Escopo | DUT | Arquivo |
|-------|--------|-----|---------|
| L1 — Unidade | Transformada de Clarke | `ClarkeTransform.vhd` | `test_clarke_transform.py` |
| L1 — Unidade | Solver bilinear linha única | `BilinearSolverUnit.vhd` | `test_bilinear_solver.py` |
| L2 — Sub-sistema | Motor vs modelo C (estímulo estático) | `TIM_Solver.vhd` | `test_tim_solver_reference.py` |
| L2 — Sub-sistema | Motor vs modelo C (estímulo V/F) | `TIM_Solver.vhd` | `test_tim_solver_vf.py` |
| L3 — Integração | Cadeia completa via UART | `Top_HIL.vhd` | `test_top_hil.py` |
| L4 — Hardware | Deploy FPGA + GUI telemetria | FPGA real | — |

---

## L1 — Testes Unitários

### Clarke Transform (`test_clarke_transform.py`)

Verifica a conversão `abc → αβ` (transformada de Concordia) isoladamente.

| Caso | Descrição | Critério |
|------|-----------|---------|
| T1 | Trifásico balanceado, θ=0 (excita só α) | `v_beta ≈ 0`, `v_alpha = Va` |
| T2 | Trifásico balanceado, θ=90° (excita só β) | `v_alpha ≈ 0`, `v_beta ≠ 0` |
| T3 | Componente de sequência zero | Saídas ≈ 0 |
| T4 | Latência de pipeline | Exatamente 3 ciclos de clock |
| T5 | Sweep de 20 pontos aleatórios | Erro ≤ 1 LSB (Q14.28) |
| T6 | Amplitude máxima (near full-scale) | Sem overflow |

```bash
cd verification/cocotb
uv run python run.py --top clarke_transform
```

### Bilinear Solver Unit (`test_bilinear_solver.py`)

Verifica o núcleo aritmético do integrador bilinear linha por linha.

| Caso | Descrição | Critério |
|------|-----------|---------|
| T1 | Matriz A identidade, sem entrada B | Estado propaga sem variação |
| T2 | Apenas entrada B (sem acoplamento A) | Saída = integral de B·u |
| T3 | Termo bilinear (produto cruzado A·x) | Saída corresponde ao cálculo manual |
| T4 | Sinal `busy` durante cálculo | Busy alto durante latência, baixo ao final |
| T5 | Todos os estados não-nulos | Nenhuma saída inesperadamente zero |

```bash
cd verification/cocotb
uv run python run.py --top bilinear_solver
```

---

## L2 — Testes de Sub-sistema (TIM_Solver vs Modelo C)

### Motivação

O `TIM_Solver.vhd` implementa o modelo B2 do motor de indução via solver bilinear
em ponto-fixo Q14.28.  O modelo C (`IM_Model.c`, compilado como `.so`) usa o mesmo
algoritmo em ponto-flutuante `double`.  Os dois devem convergir para as mesmas
trajetórias dentro da tolerância de quantização.

### Como funciona a comparação

```python
# A cada passo de simulação (Ts = 100 ns):
va, vb, vc = vf.step()                      # mesmo estímulo para os dois

# Modelo C (ponto-flutuante, referência)
ref_state = c_model.step(va, vb, vc, tload)

# Modelo VHDL (ponto-fixo Q14.28, DUT)
dut.va_i.value = real_to_fp(va)
await wait_data_valid(dut)
vhdl_i_alpha = signal_fp_to_real(dut.ialpha_o)

# Erro passo-a-passo
err = vhdl_i_alpha - ref_state.i_alpha
```

### Teste 1 — Estímulo estático em malha aberta (`test_tim_solver_reference.py`)

Dois vetores de tensão constantes por partes, 500 passos (50 µs).

```bash
cd verification/cocotb
uv run python run.py --top tim_solver --test reference
# ou, da raiz:
make cocotb-tim-ref
```

Critérios de aceite:

| Variável | Métrica | Limite |
|----------|---------|--------|
| `i_alpha` | NRMSE | < 10 % |
| `i_beta` | NRMSE | < 10 % |
| `flux_alpha` | MAE | < 1 × 10⁻³ Wb |
| `flux_beta` | MAE | < 1 × 10⁻³ Wb |
| `speed_mech` | MAE | < 2,0 rad/s |

### Teste 2 — Estímulo V/F (partida do motor) (`test_tim_solver_vf.py`)

Rampa de frequência linear (5000 Hz/s) com relação V/f constante.  3000 passos
(300 µs) de tempo de motor.  Este é o teste **mais realista** — reproduz o
comportamento de partida que será visto na FPGA.

```bash
cd verification/cocotb
uv run python run.py --top tim_solver --test vf
# ou, da raiz:
make cocotb-tim-vf     # (adicione o alvo se ainda não existir)
```

Ao final do teste, um CSV é exportado para `reports/vf_vhdl_vs_ref.csv`.

Critérios de aceite: **idênticos** ao Teste 1 acima.

> **Dica:** o estímulo V/F usa `initial_theta = π/4` para garantir que os dois eixos
> α e β sejam excitados desde o passo 0.  Sem isso, a métrica NRMSE em β seria
> calculada sobre valores próximos de zero e daria falsos positivos.

---

## Geração de Relatório HTML

O script `scripts/vf_report.py` roda o modelo C por um tempo mais longo (padrão 2 s
de tempo de motor) e gera um relatório interativo em Plotly.

```
reports/
├── vf_ref_model.csv        ← C model (2 s, decimado)
├── vf_vhdl_vs_ref.csv      ← VHDL cocotb (300 µs, passo-a-passo)
└── vf_report.html          ← Relatório interativo
```

### Apenas modelo C (referência)

```bash
cd verification/cocotb
uv run python scripts/vf_report.py --duration 2.0
```

### Modelo C + overlay VHDL (comparação)

Requer que o `test_tim_solver_vf.py` já tenha rodado e gerado o CSV.

```bash
# 1. Gerar CSV do VHDL (cocotb + GHDL)
uv run python run.py --top tim_solver --test vf

# 2. Gerar relatório com overlay
uv run python scripts/vf_report.py --overlay
```

O relatório contém 7 subplots quando o overlay está ativo:

| Subplot | Conteúdo |
|---------|---------|
| 1 | Correntes de fase ia, ib, ic (modelo C) |
| 2 | Correntes αβ — C (linha) + VHDL (pontos) sobrepostos |
| 3 | Fluxo rotórico ψα, ψβ — C + VHDL sobrepostos |
| 4 | Velocidade mecânica ωm — C + VHDL sobrepostos |
| 5 | Torque eletromagnético Te (modelo C) |
| 6 | Excitação V/F: Va e f_ref |
| 7 | **Erro absoluto** (VHDL − C): iα e iβ |

---

## L3 — Teste de Integração Full-Chain (`test_top_hil.py`)

Testa o sistema completo: configuração via UART → NPCManager (PWM) → TIM_Solver →
leitura dos registros via UART.

```bash
cd verification/cocotb
uv run python run.py --top top_hil
```

| Teste | O que verifica |
|-------|---------------|
| `test_write_read_vdc_bus` | Registro R/W pelo protocolo UART/SerialManager |
| `test_write_read_torque_load` | Idem para torque de carga |
| `test_read_all_registers` | ReadAll: 10 registros em uma única transação |
| `test_pwm_enable` | Habilitação do PWM e atividade nos gates NPC |
| `test_full_chain_motor_outputs` | Config → PWM → motor → leitura de saída (cadeia completa) |

---

## Fluxo Completo de Validação

```
┌─────────────────────────────────────────────────────────┐
│  Passo 1 — Setup                                        │
│  make cocotb-setup                                      │
│  (instala cocotb, plotly e compila o modelo C)          │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  Passo 2 — Testes Unitários (L1)                        │
│  make cocotb TOP=clarke_transform                       │
│  make cocotb TOP=bilinear_solver                        │
│  Todos devem passar antes de continuar                  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  Passo 3 — Validação TIM_Solver vs Modelo C (L2)        │
│  make cocotb-tim-ref                  (estático)        │
│  uv run python run.py --top tim_solver --test vf        │
│  uv run python scripts/vf_report.py --overlay          │
│  → Inspecionar reports/vf_report.html                  │
│    (formas de onda sobrepostas + subplot de erro)       │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  Passo 4 — Integração (L3)                              │
│  make cocotb                                            │
│  (testa cadeia completa UART → NPC → TIM → UART)       │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  Passo 5 — Síntese e Deploy (L4)                        │
│  Abrir syn/HIL.xpr no Vivado                           │
│  Sintetizar → Implementation → Generate Bitstream      │
│  Programar FPGA                                        │
│  Validar com GUI (apps/hil-gui-tauri)                  │
└─────────────────────────────────────────────────────────┘
```

---

## Tolerâncias e Justificativas

### Por que NRMSE < 10% e não < 1%?

O `TIM_Solver` usa Q14.28 (42 bits, 28 bits fracionários ≈ 3,7 × 10⁻⁹ de resolução).
A quantização dos coeficientes da matriz e dos estados acumula erro a cada passo.
Em 300 µs (3000 passos × Ts = 100 ns) os erros integram.  10% é um limite
conservador que garante comportamento funcional sem rejeitar o design por ruído de
quantização normal.

| Variável | Por que MAE e não NRMSE? |
|----------|--------------------------|
| Fluxo rotórico | Em 300 µs o motor mal saiu do repouso; NRMSE sobre valores ~0 é instável |
| Velocidade | Idem — cresce muito lentamente nessa janela de tempo |

### Ajuste de critérios

Se os testes falharem consistentemente mas as formas de onda no relatório parecerem
corretas (trajetórias sobrepostas), os limites podem ser afrouxados gradualmente.
Documente qualquer mudança aqui com justificativa.

---

## Representação em Ponto-Fixo (Q14.28)

Todos os sinais de 42 bits usam o formato **Q14.28** (complemento de dois):

```
Bit 41 (MSB) — sinal
Bits 40..28 — parte inteira (13 bits)
Bits 27..0  — parte fracionária (28 bits)

Conversões Python:
  real → fixo:  int(round(value * (1 << 28)))
  fixo → real:  signed_value / (1 << 28)

Resolução: 2⁻²⁸ ≈ 3,7 × 10⁻⁹
Faixa:     ±8192 (≈ ±2¹³)
```

---

## Estrutura de Arquivos

```
verification/cocotb/
├── README.md                        ← este arquivo
├── run.py                           ← runner (cocotb_tools API)
├── Makefile                         ← atalhos de build
├── pyproject.toml                   ← dependências Python (uv)
│
├── models/
│   ├── im_reference_model.py        ← wrapper C model (.so) + fallback Python
│   └── vf_control.py                ← gerador de estímulo V/F
│
├── drivers/
│   ├── uart_driver.py               ← driver UART (TX/RX bit-a-bit)
│   └── serial_manager_driver.py     ← protocolo de registros (Write/Read/ReadAll)
│
├── tests/s
│   ├── test_clarke_transform.py     ← L1: unidade Clarke
│   ├── test_bilinear_solver.py      ← L1: unidade solver bilinear
│   ├── test_tim_solver_reference.py ← L2: TIM_Solver vs C (estático)
│   ├── test_tim_solver_vf.py        ← L2: TIM_Solver vs C (V/F) ← principal
│   └── test_top_hil.py              ← L3: integração UART full-chain
│
├── scripts/
│   └── vf_report.py                 ← gerador do relatório HTML (Plotly)
│
├── hdl/
│   └── BilinearSolverUnitTB.vhd     ← wrapper VHDL para testes unitários
│
└── reports/                         ← saídas geradas (CSV, HTML)
    ├── vf_ref_model.csv
    ├── vf_vhdl_vs_ref.csv
    └── vf_report.html
```

---

## Próximos Passos

- [ ] Aumentar janela de simulação V/F (> 300 µs) para cobrir regime permanente
- [ ] Adicionar subplot de torque no overlay do relatório
- [ ] Testar com torque de carga não-nulo (`TLOAD_NM > 0`)
- [ ] Validar em hardware com GUI após deploy na FPGA
- [ ] Adicionar teste de regressão de corner-case: velocidade máxima, tensão mínima
