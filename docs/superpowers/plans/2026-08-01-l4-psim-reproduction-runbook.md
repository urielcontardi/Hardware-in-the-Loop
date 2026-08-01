# Runbook — Reproduzir os 6 cenários da campanha L4 no PSIM

## Contexto do projeto

Este repositório valida um modelo de motor de indução (VHDL `TIM_Solver`, rodando
numa FPGA EBAZ4205) comparando-o contra um modelo de referência em C/C++
(`extras/induction-motor-model/src/IM_Model.c`). A validação é feita em camadas
(ver `docs/experimental-validation-plan.md`):

- **L1**: PSIM vs C/C++ — valida a formulação matemática/numérica do modelo.
- **L2**: C/C++ vs VHDL do solver isolado.
- **L3**: Top_HIL simulado (VHDL com modulador/PWM) vs C/C++.
- **L4**: FPGA real vs C/C++ offline — já executado, campanha
  `verification/results/2026-07-25_campaign_l4_final`, 6 casos (`S0, A1, A3, A5,
  B1, B2`), mesmos parâmetros de L2/L3 (campanha `campaign_03`).

**Objetivo desta tarefa**: reproduzir os mesmos 6 cenários da campanha L4 real
dentro do PSIM (`extras/induction-motor-model/psim/2_pwmModelValidation/NPC_Inverter.psimsch`),
pra comparar o resultado do PSIM contra as capturas reais da FPGA.

**Ressalva metodológica importante**: isso não é um L2/L3 clássico — é
essencialmente PSIM (papel de L1) comparado direto contra L4 real, pulando o
isolamento intermediário. Serve como validação geral (bate ou não bate), mas
se divergir, não dá pra atribuir sozinho a causa (modelo vs. ponto fixo vs.
modulador vs. hardware) sem rodar L2/L3 também. Tudo bem pro objetivo atual,
só não deve ser vendido como equivalente a L2/L3 na dissertação.

## Estado atual do schematic (`NPC_Inverter.psimsch`)

Já foi feito nesta sessão anterior, antes deste runbook:

1. **Fonte de carga**: um bloco **"Step (2-level)"** (em `Sources → Voltage` — no
   PSIM não existe uma categoria "Control" separada para fontes; sources de
   Voltage/Current servem tanto pro circuito de potência quanto pra sinais de
   controle, dependendo de onde você liga o fio). Esse bloco tem os campos
   `Vstep1` (valor antes do degrau), `Vstep2` (valor depois), `Tstep` (instante
   do degrau) — diferente do "Step" simples, que só vai de 0 a um valor fixo.
2. Esse Step (2-level) está ligado, via net-label (`Tload` ou `Load`,
   confirmar o nome usado no schematic), em dois lugares:
   - Pino `TLOAD`/"Load1" do bloco DLL ("Induction Motor C/C++ Model").
   - Terminal de controle do bloco **`MLOAD_EXT1`** ("Mechanical Load (ext.
     controlled)"), do lado do motor PSIM nativo — com `Speed Flag = 0` (sinal de
     controle = torque, não velocidade) e `Moment of Inertia = 0` (pra não
     somar inércia duplicada, já que o modelo C já usa `inertia` do
     `parameters.txt`).
3. **Campo `Model` do bloco DLL = `2`** (equivale a `MODEL_B2` no enum
   `IMType` de `extras/induction-motor-model/src/IM_Model.h`). Esse é o modelo
   usado em todo o resto do projeto para comparação (`verification/cocotb/models/im_reference_model.py`,
   `scripts/validate_hil_pwm.py`, `scripts/hil_fullstack_mock.py`,
   `verification/cocotb/scripts/top_fullstack_mock.py` — todos usam
   `MODEL_B2`). **Não mudar esse valor.**
4. **`parameters.txt`** (nesta mesma pasta `2_pwmModelValidation/`) foi editado
   com as variáveis abaixo. **Atenção ao encoding**: esse arquivo é **UTF-16LE
   com BOM (`FF FE`) e quebra de linha CRLF** — é o formato que o PSIM espera.
   Se for reescrever esse arquivo por script, não salvar como UTF-8 comum, ou
   o PSIM não vai conseguir ler.

   ```
   // Motor parameters
   w_nominal = 2*pi*60
   w_ref = 2*pi*60
   accRamp = 1

   // LVP (760V)
   Vrms = 760
   rs = 0.4396
   ls = 3.1364m
   rr = 0.2826
   lr = 6.3264m
   lm = 109.9442m
   npp = 2
   inertia = 0.4

   // DC Link
   vdc = 1240

   // Load torque (Step 2-level, wired identically on PSIM motor and C model)
   Tload_init = 0
   Tload_final = 0
   Tload_step_time = 0
   ```

   Os valores de `vdc` (1240, não 1600 — valor antigo errado) e o modelo motor
   (`rs, ls, rr, lr, lm, npp, inertia`) já batem com o resto do projeto. Os
   `Tload_*` ficam sobrescritos a cada caso (ver tabela abaixo).

## Problema conhecido, ainda sem solução definitiva

**O bloco "Simulation Control" (Total Time, Print Time, Print Step) NÃO lê
variáveis do `parameters.txt`.** Foi testado empiricamente: colocar o nome de
uma variável (`duration_s`) no campo "Total Time" não resolveu — o campo
continuou efetivamente em `0`. Isso é diferente dos parâmetros de componentes
normais (`rs`, `Tload_init` etc.), que resolvem variáveis do arquivo
normalmente.

**Consequência prática**: o campo **"Total Time" precisa ser digitado
manualmente, como número literal, em cada rodada**, direto no bloco Simulation
Control — não dá pra automatizar isso só editando `parameters.txt`. Se for
automatizar via `PsimCmd.exe`, verificar antes se essa ferramenta tem uma flag
própria pra sobrescrever o tempo total de simulação (rodar `PsimCmd.exe -?`
pra ver as opções) — isso nunca foi confirmado.

Se não houver essa flag, a alternativa é fixar "Total Time" em `7.0` (o maior
caso, A5) pra todos os 6 casos, e truncar/filtrar os dados de cada CSV de
saída no tempo real do caso antes de comparar (ver coluna "Total Time" da
tabela abaixo pros valores reais).

## Os 6 cenários

Fonte de verdade: `verification/cocotb/scripts/run_l4_campaign.py:30-49`
(campanha real `2026-07-25_campaign_l4_final`). Fixos em todos os casos:
`vdc=1240`, `w_ref=2*pi*60`, `model = 2`.

| Caso | `accRamp` (s) | `Tload_init` (Nm) | `Tload_final` (Nm) | `Tload_step_time` (s) | **Total Time** (s) |
|---|---|---|---|---|---|
| S0 | 1.0 | 0 | 0 | — (irrelevante) | 3.0 |
| A1 | 0.5 | 0 | 0 | — | 2.5 |
| A3 | 1.0 | 58.3568124670283 | 58.3568124670283 | — | 3.0 |
| A5 | 5.0 | 0 | 0 | — | 7.0 |
| B1 | 0.5 | 29.17840623351415 | 87.53521870054244 | 0.6 | 1.5 |
| B2 | 0.5 | 58.3568124670283 | 116.7136249340566 | 0.6 | 1.5 |

Nos casos sem degrau (S0, A1, A3, A5), `Tload_init = Tload_final`, então o
`Step (2-level)` produz um valor constante — `Tload_step_time` pode ficar `0`.

`Tn` (torque nominal do motor) = 116.7136249340566 Nm — os valores de carga
acima são frações dele (0, 0.25, 0.5, 0.75, 1.0 Tn).

## Procedimento por caso (repetir 6x)

1. Abrir `parameters.txt` (nesta pasta), editar `accRamp`, `Tload_init`,
   `Tload_final`, `Tload_step_time` com os valores da linha correspondente da
   tabela. Salvar mantendo o encoding UTF-16LE.
2. No PSIM, com `NPC_Inverter.psimsch` aberto: fechar e reabrir o arquivo pra
   garantir que os novos valores do `parameters.txt` foram relidos (não há
   confirmação de que o PSIM recarrega isso automaticamente em tempo real).
3. Abrir o bloco "Simulation Control": digitar o "Total Time" daquele caso
   (coluna da tabela) como número literal. "Print Time" deve ficar `0` (senão
   aparece o aviso "Print Time >= Total Time" e a simulação não salva nada).
   "Print Step" pode ficar num valor decimado (ex. `10`) pra não gerar um CSV
   gigante, já que o Time Step do solver é fino (`1E-06`).
4. Rodar a simulação.
5. **Confirmar que não apareceu nenhum warning/erro** (nem o de Print Time,
   nem erro de nó/terminal desconectado).
6. Conferir visualmente no SIMVIEW: motor acelera de forma plausível; nos
   casos B1/B2, checar que o degrau de corrente aparece no instante `0.6s`.
7. Exportar os dados (SIMVIEW → File → Export, ou usar o `.txt` que o PSIM
   gera automaticamente com o nome do schematic).
8. **Renomear o arquivo de saída imediatamente** para `<caso>_l1_psim.txt`
   (ex. `S0_l1_psim.txt`) antes de rodar o próximo caso — senão o próximo run
   sobrescreve o anterior.

**Ordem recomendada**: S0 primeiro (mais simples, é o teste de sanidade — se
não fechar limpo, não adianta seguir). Depois A1 → A3 → A5 (mesma família,
variando só a rampa). Por último B1 → B2 (únicos com degrau, mais fácil de
errar a fiação).

## Onde salvar os resultados

Criar, ao lado do schematic:

```
extras/induction-motor-model/psim/2_pwmModelValidation/
  results/
    S0_l1_psim.txt
    A1_l1_psim.txt
    A3_l1_psim.txt
    A5_l1_psim.txt
    B1_l1_psim.txt
    B2_l1_psim.txt
    run_notes.txt        <- data/hora de cada run, warnings encontrados, etc.
```

Depois, mover esses 6 arquivos pra dentro de
`verification/results/<data>_campaign_l1_psim/<caso>/`, seguindo o mesmo
padrão de pasta que a campanha L4 real (`verification/results/2026-07-25_campaign_l4_final/<caso>_l4/`)
já usa — isso facilita comparar os dois lado a lado depois (mesmo agente ou
outro pode escrever um script comparador, mapeando as colunas do PSIM —
`IuSim1, IvSim1, IwSim1, Wr1, Wmec1, motorSpeedSim, v_alpha_sim, v_beta_sim` —
pros nomes já usados nas métricas de L2/L3/L4, tipo `i_alpha`, `i_beta`,
`speed`).

## Itens em aberto (não bloqueiam este runbook, mas ficam pendentes)

- **Sincronização de arquivo**: o `parameters.txt` é editado neste repositório
  (ambiente Linux), mas o PSIM roda numa máquina Windows separada. Não há um
  mecanismo confirmado de sincronização automática (SSH foi mencionado como
  possível, mas nunca testado/conectado). Quem for executar precisa garantir
  manualmente que o arquivo usado pelo PSIM bate com o conteúdo acima antes de
  cada rodada — já aconteceu de ficar desatualizado (`vdc=1600` em vez de
  `1240`) por esse motivo.
- **Automação via `PsimCmd.exe`**: discutida mas nunca testada de fato. Se for
  tentar automatizar depois de validar os 6 casos manualmente, checar a
  sintaxe real com `PsimCmd.exe -?` antes de escrever qualquer script.
