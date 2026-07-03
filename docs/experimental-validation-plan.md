# Planejamento de Ensaios e Validacao Experimental

Este documento resume o plano operacional para extrair resultados da plataforma
HIL e organizar os artefatos gerados. A ideia e separar a validacao em camadas,
para que cada comparacao responda uma pergunta especifica e nao misture erro de
modelo, erro numerico, erro de modulacao e erro de sincronismo.

## Objetivo

Validar se o modelo de motor de inducao implementado em FPGA reproduz, em tempo
real, o comportamento obtido por referencias offline. Os resultados devem gerar
metricas quantitativas e figuras utilizaveis na dissertacao.

## Regra Obrigatoria de Consistencia

Antes de iniciar qualquer simulacao, captura ou comparacao, todos os ambientes
devem usar os mesmos parametros fisicos e de excitacao. Uma comparacao so e
valida se os itens abaixo forem iguais entre FPGA, C/C++, VHDL, PSIM e scripts
offline, ou se a diferenca for explicitamente registrada como parte do ensaio:

- parametros do motor: `Rs`, `Rr`, `Ls`, `Lr`, `Lm`, `J`, `npp`;
- passo de integracao ou periodo equivalente do solver;
- tensao do barramento CC `Vdc`;
- torque de carga inicial e perfil de carga;
- frequencia alvo;
- rampa de aceleracao `t_acc`;
- lei V/f: `base_freq_hz`, `max_v_pu` e eventual boost;
- estado inicial do motor ou procedimento de reset;
- fase/alinhamento inicial, quando aplicavel;
- filtro/decimacao usado antes da comparacao.

Checklist minimo antes de rodar um caso:

1. salvar os parametros do motor no arquivo de metadados do caso;
2. confirmar `Vdc` usado pelo firmware e pelo modelo offline;
3. confirmar `t_acc`, frequencia alvo e torque;
4. registrar o commit, bitstream e versao do executavel;
5. registrar se houve alinhamento de fase ou tempo;
6. rejeitar a comparacao se algum parametro essencial estiver ausente.

Esta regra evita repetir o erro de comparar uma captura gerada com `Vdc=1240 V`
contra uma simulacao offline assumindo `Vdc=300 V`, ou comparar a FPGA com um
modelo C/C++ usando inercia/motor diferentes.

## Cadeia de Validacao

| Nivel | Comparacao | Finalidade | Status |
| --- | --- | --- | --- |
| L1 | PSIM vs C/C++ | Validar formulacao matematica e integracao numerica. | Base teorica/previa |
| L2 | C/C++ vs VHDL/Vivado | Medir erro de ponto fixo e discretizacao do solver. | Cocotb ja cobre parte |
| L3 | Top_HIL simulado vs C/C++ | Validar cadeia integrada: V/F, modulador, Clarke/gates e solver. | Proximo bloco |
| L4 | FPGA real vs offline | Validar plataforma em tempo real via `.hilbin`, DMA e PWM capturado. | Em andamento |

Regra de interpretacao: cada nivel deve introduzir uma nova fonte de erro. Se um
erro aparece em L4, mas nao aparece em L2, ele provavelmente vem da integracao em
hardware, telemetria, PWM, sincronismo ou protocolo de captura.

## Fluxos Cocotb Existentes

Os scripts antigos em `verification/cocotb` continuam sendo a base para a
validacao L2. Eles permitem rodar a simulacao VHDL com GHDL ou NVC e, no mesmo
testbench cocotb, executar o modelo C/C++ como referencia.

| Comando | Nivel | O que compara | Observacao |
| --- | --- | --- | --- |
| `make tim-ref` | L2 | `TIM_Solver.vhd` vs `extras/induction-motor-model` | Estimulo por partes em `va/vb/vc`; bom sanity check numerico. |
| `make tim-ref SIM=nvc` | L2 | Igual ao anterior, usando NVC | Mesmo teste, simulador mais rapido quando instalado. |
| `make tim-sine SIM=nvc` | L2 | `TIM_Solver.vhd` vs C/C++ com seno trifasico ideal | Remove PWM e V/f; valida solver com entrada senoidal. |
| `make tim-vf SIM=nvc` | L2/L2+ | `TIM_Solver.vhd` vs C/C++ com rampa V/f ideal | Ainda injeta `va/vb/vc` direto no solver; nao inclui modulador PWM real. |
| `make test TOP=top_hil SIM=nvc` | L3 parcial | Integra UART, PWM, NPC, Clarke/gates e solver | Hoje verifica atividade/consistencia, mas nao gera metrica completa contra C/C++. |

Portanto, o fluxo "VHDL no NVC + C/C++ controlado pelo cocotb" e exatamente o
que deve ser usado para L2. O que ainda falta para L3 e transformar o teste
`top_hil` em uma comparacao quantitativa contra um full-stack C/C++ equivalente,
exportando os sinais da simulacao VHDL e calculando as mesmas metricas usadas
em L2 e L4.


## Observacao Metodologica - Sincronismo V/f e PWM

Na implementacao atual da plataforma fisica, as referencias trifasicas do comando V/f sao atualizadas pelo PS a `10 kHz`, por interrupcao de timer, enquanto a portadora PWM de `1 kHz` e gerada no PL. Como esses dois eventos nao compartilham um travamento explicito de fase, existe uma incerteza no instante relativo entre a atualizacao da referencia e a comparacao com a portadora.

Essa diferenca nao altera a frequencia nominal do PWM, mas pode introduzir jitter de fase referencia--portadora. Em consequencia, parte da discrepancia observada nos niveis L3 e L4 pode estar associada ao sincronismo entre modulador e referencia, e nao somente ao modelo do motor ou ao solver.

A interpretacao dos resultados deve separar tres situacoes:

1. L2: nao inclui PWM nem atualizacao PS--PL; portanto nao mede esse efeito.
2. L3 PWM replay: o C/C++ recebe as tensoes efetivamente amostradas do caminho interno do `Top_HIL`; esse ensaio reduz a ambiguidade de fase e isola melhor solver/cadeia integrada.
3. L3/L4 full-stack: quando C/C++ replica V/f, portadora e gate-driver de forma independente, a fase relativa entre referencia e portadora deve ser registrada ou varrida, pois ela pode afetar a comparacao.

Para resultados finais, todo ensaio L3/L4 deve registrar: taxa de atualizacao V/f, frequencia PWM, origem temporal da portadora, fase inicial assumida, metodo de alinhamento e se houve replay das tensoes/PWM ou geracao independente do modulador.

## Comparacoes Que Devem Ser Reportadas

1. Solver isolado
   - Entrada: `va/vb/vc` definida e igual para C/C++ e VHDL.
   - Saida: `i_alpha`, `i_beta`, `flux_alpha`, `flux_beta`, `speed`.
   - Objetivo: provar equivalencia numerica do solver.

2. FPGA real com PWM capturado
   - Entrada do C/C++: PWM real do `.hilbin`.
   - Saida da FPGA: telemetria DMA do `.hilbin`.
   - Objetivo: validar o solver real em hardware sob excitacao real.
   - Observacao: quando possivel, melhorar registrando tambem `va/vb/vc` usados pelo solver.

3. Full-stack mock
   - Entrada do C/C++: V/F + portadora + NPCGateDriver + modelo C.
   - Saida da FPGA: telemetria DMA do `.hilbin`.
   - Objetivo: validar comportamento completo da plataforma.
   - Observacao: exige alinhamento de fase/tempo documentado.

## Roteiro de Execucao por Nivel

Esta secao define o passo a passo operacional. A ordem deve ser preservada:
primeiro validar o modelo matematico, depois o solver em hardware simulado,
depois a cadeia integrada simulada e, por fim, a FPGA real. Isso evita concluir
que um erro e da FPGA quando ele ja existia no modelo ou no procedimento de
alinhamento.

### L1: PSIM vs C/C++

Pergunta respondida: o modelo C/C++ representa corretamente o modelo de motor
usado como referencia offline?

Entradas:

- parametros do motor;
- passo de integracao;
- perfil de tensao ou perfil V/f;
- torque de carga;
- arquivo de referencia exportado do PSIM.

Procedimento:

1. Fixar um conjunto de parametros do motor.
2. Rodar o caso no PSIM.
3. Exportar `i_alpha`, `i_beta`, `flux_alpha`, `flux_beta` e `speed`, ou
   variaveis equivalentes que possam ser transformadas.
4. Rodar o modelo C/C++ com os mesmos parametros, passo e entradas.
5. Alinhar os vetores no tempo apenas se houver diferenca de origem temporal
   documentada.
6. Calcular MAE, RMSE e NRMSE por sinal.
7. Salvar `metrics.json`, `overlay.png`, `overlay.html` e `traces.csv`.

Artefatos esperados:

```text
verification/results/<campaign>/<case>/l1_psim_vs_c/
  psim_export.csv
  c_reference.csv
  metrics.json
  overlay.png
  overlay.html
```

```text
ID: L3-S3
Diretorio: verification/results/2026-06-29_campaign_01/S0_tacc1s_load000/l3_top_pwm_replay_vf_2s/
Estimulo: Top_HIL com rampa V/F 60 Hz/s, janela 0--2 s, PWM 1 kHz, Vdc=1240 V, carga nula
Clock: 200 MHz, 26 ciclos, Ts=130 ns
Metodo: PWM replay; o C recebe va/vb/vc instantaneos do caminho interno NPC->tensao do Top_HIL
Tempo de parede: 6,35 h
CSV: 19.232 linhas, decimado com record_interval=800
Metricas globais: i_alpha NRMSE=5.66%, i_beta NRMSE=5.76%, flux_alpha MAE=5.21e-3 Wb, flux_beta MAE=5.31e-3 Wb, speed MAE=0.478 rad/s
Metricas em regime 1.5--2.0 s no CSV decimado: i_alpha NRMSE=3.36%, i_beta NRMSE=3.36%, flux_alpha MAE=5.60e-4 Wb, flux_beta MAE=5.85e-4 Wb
Artefatos: metrics.json, window_metrics_decimated.json, top_pwm_replay_vs_c.csv, overlay.html, README.md
Observacao: paralelo L3 do caso L2 V/F 2 s. As metricas globais foram calculadas em todos os passos validos; as metricas por janela foram calculadas no CSV decimado.
```

Criterio de aceite:

- correntes e fluxos devem apresentar erro compativel com a diferenca de passo
  numerico entre PSIM e C/C++;
- se L1 falhar, nenhum resultado L2-L4 deve ser usado como validacao do HIL.

### L2: C/C++ vs VHDL do Solver

Pergunta respondida: a implementacao VHDL do solver reproduz o modelo C/C++ sem
a influencia do modulador e da telemetria?

Entradas:

- sequencia imposta de `va`, `vb`, `vc`;
- torque de carga;
- parametros do motor;
- estado inicial conhecido.

Procedimento:

1. Definir um estimulo simples para `va/vb/vc`:
   - degrau DC em eixo alpha;
   - seno trifasico balanceado;
   - perfil por partes para excitar partida e regime.
2. Rodar o modelo C/C++ com a mesma entrada e mesmo passo efetivo.
3. Rodar o testbench VHDL/cocotb do `TIM_Solver`.
4. Comparar somente as saidas do solver:
   `i_alpha`, `i_beta`, `flux_alpha`, `flux_beta`, `speed`.
5. Calcular metricas no transitorio e em regime.
6. Registrar tambem erro maximo e erro de quantizacao esperado.

Comando/base atual:

```bash
cd verification/cocotb
make tim-ref
```

Decisao metodologica para L2:

- os resultados principais de L2 devem usar o mesmo passo do solver real:
  `CLOCK_FREQUENCY=200 MHz`, `SOLVER_STEP_CYCLES=26` e `Ts=130 ns`;
- o objetivo de L2 e defender a equivalencia numerica do `TIM_Solver.vhd` que
  sera sintetizado/executado na FPGA. Portanto, alterar `Ts` invalida o ensaio
  como metrica principal, mesmo que o C/C++ use o mesmo `Ts` alterado;
- simulacoes longas com NVC em 200 MHz sao caras, entao a matriz principal de
  L2 deve ser pequena e forte: poucos casos, bem escolhidos, todos no clock
  real;
- ensaios com clock reduzido podem existir apenas como diagnostico de custo ou
  estresse numerico. Eles devem ficar marcados como exploratorios e nao devem
  entrar na tabela principal de erro da dissertacao;
- nunca usar `SOLVER_STEP_CYCLES=1` para acelerar o `TIM_Solver`: o solver nao
  conclui uma iteracao em um ciclo e o timer passa a atropelar o
  `BilinearSolverHandler`.



Casos L2 principais recomendados:

| ID | Estimulo | Clock/passo | Finalidade | Status |
| --- | --- | --- | --- | --- |
| L2-S0 | degrau/trecho por partes (`make tim-ref SIM=nvc`) | `200 MHz`, `26 ciclos`, `Ts=130 ns` | sanity numerico do solver e ponto fixo | executado, passou |
| L2-S1 | seno trifasico 60 Hz (`make tim-sine SIM=nvc`) | `200 MHz`, `26 ciclos`, `Ts=130 ns` | regime senoidal sem V/f e sem PWM | executado, passou: `iα` NRMSE 5.9e-5, `iβ` NRMSE 4.0e-5 |
| L2-S1b | seno trifasico 60 Hz por um ciclo eletrico completo | `200 MHz`, `26 ciclos`, `Ts=130 ns` | diagnostico de acumulacao em janela longa | executado, gerou dados; assert de fluxo excedido |
| L2-S2 | janela curta V/f 0--50 ms | `200 MHz`, `26 ciclos`, `Ts=130 ns` | inicio de partida no passo real | executado, passou: `iα` NRMSE 3.65e-4, `iβ` NRMSE 2.84e-4 |
| L2-S3 | V/f completo 0--2 s, caso unico | `200 MHz`, `26 ciclos`, `Ts=130 ns` | caso golden de partida completa | executado, passou: global `iα` NRMSE 5.82%, `iβ` 5.71%; regime 1.5--2.0 s `iα` 3.42%, `iβ` 3.43% |

Resultado principal L2-S1 ja executado:

```text
Diretorio: verification/results/2026-06-29_campaign_01/S0_tacc1s_load000/l2_sine_60hz_realts/
Estimulo: seno trifasico ideal, 60 Hz, 620 V pico de fase, sem carga
Clock: 200 MHz, 26 ciclos, Ts=130 ns
Metricas: i_alpha NRMSE=5.9e-5, i_beta NRMSE=4.0e-5, flux_alpha MAE=1.10e-5 Wb, flux_beta MAE=1.19e-5 Wb
Artefatos: metrics.json, sine_vhdl_vs_c.csv, overlay.html
```

Resultado diagnostico L2-S1b executado:

```text
Diretorio: verification/results/2026-06-29_campaign_01/S0_tacc1s_load000/l2_sine_1cycle_realts/
Estimulo: seno trifasico ideal, 60 Hz, 620 V pico de fase, sem carga, um ciclo eletrico completo
Clock: 200 MHz, 26 ciclos, Ts=130 ns
Metricas: i_alpha NRMSE=5.83e-4, i_beta NRMSE=6.92e-4, flux_alpha MAE=6.43e-3 Wb, flux_beta MAE=8.29e-3 Wb, speed MAE=0.133 rad/s
Artefatos: metrics.json, sine_vhdl_vs_c.csv, overlay.html
Observacao: o testbench marcou falha porque o limite automatico de fluxo era 1e-3 Wb. Como a corrente permanece com erro menor que 0.1%, este caso deve ser usado como diagnostico de acumulacao/estado em janela longa, nao como rejeicao do solver.
```

Resultado principal L2-S2 ja executado:

```text
Diretorio: verification/results/2026-06-29_campaign_01/S0_tacc1s_load000/l2_vf_50ms_realts/
Estimulo: rampa V/f de 60 Hz/s, janela 0--50 ms, sem carga
Clock: 200 MHz, 26 ciclos, Ts=130 ns
Metricas: i_alpha NRMSE=3.65e-4, i_beta NRMSE=2.84e-4, flux_alpha MAE=1.11e-3 Wb, flux_beta MAE=1.39e-3 Wb
Artefatos: metrics.json, vf_vhdl_vs_c.csv, overlay.html
```

Resultado principal L2-S3 ja executado:

```text
Diretorio: verification/results/2026-06-29_campaign_01/S0_tacc1s_load000/l2_vf_2s_realts/
Estimulo: rampa V/f de 60 Hz/s, 0--60 Hz em 1 s, regime ate 2 s, sem carga
Clock: 200 MHz, 26 ciclos, Ts=130 ns
Metricas globais: i_alpha NRMSE=5.82%, i_beta NRMSE=5.71%, flux_alpha MAE=5.27e-3 Wb, flux_beta MAE=5.21e-3 Wb, speed MAE=0.478 rad/s
Metricas em regime 1.5--2.0 s: i_alpha NRMSE=3.42%, i_beta NRMSE=3.43%, flux_alpha MAE=5.37e-4 Wb, flux_beta MAE=5.61e-4 Wb
Artefatos: metrics.json, window_metrics.json, vf_vhdl_vs_c.csv, overlay.html
Observacao: reportar metricas por janela, pois o erro global e maior no transitorio intermediario.
```

Resultado exploratorio ja executado, nao usar como metrica principal:

```bash
IM_RS=0.435 IM_J=0.192 \
IM_CLOCK_FREQUENCY=7692308 IM_SOLVER_STEP_CYCLES=26 \
HIL_VF_DURATION_S=2.0 HIL_VF_ACC_RAMP_HZ_S=60 HIL_VF_TLOAD_NM=0 \
make tim-vf SIM=nvc
```

Esse ensaio usa `Ts≈3,38 us`, nao `Ts=130 ns`. Ele passou, mas apresentou erro
de corrente em regime da ordem de 10% por janela, mostrando que aumentar o passo
contamina a metrica. O resultado fica documentado somente como diagnostico de
custo/sensibilidade numerica.

Artefatos esperados:

```text
verification/results/<campaign>/<case>/l2_solver/
  ref_vhdl_vs_c.csv
  metrics.json
  overlay.png
  overlay.html
```

Criterio de aceite:

- erro pequeno e explicavel por ponto fixo/discretizacao;
- velocidade pode ser menos informativa em janelas curtas se a carga for nula,
  mas correntes e fluxos devem acompanhar a referencia.

### L3: Top_HIL Simulado vs C/C++

Pergunta respondida: a cadeia integrada simulada em VHDL, incluindo modulacao e
conversao de tensao, reproduz a cadeia C/C++ equivalente?

Entradas:

- comando V/f;
- portadora PWM;
- `NPCModulator`;
- `NPCGateDriver`;
- mapeamento de estados NPC para `va/vb/vc`;
- solver.

Procedimento:

1. Rodar uma simulacao do `Top_HIL` ou wrapper equivalente com o mesmo perfil de
   comando usado no C/C++.
2. No C/C++, rodar o mock full-stack:
   `V/F -> carrier -> NPCGateDriver -> IM_Model.c`.
3. Garantir que o modo do mock corresponde ao VHDL:
   - `--gate-mode gated`;
   - `Vdc` igual;
   - `freq_hz`, `base_freq_hz`, `accel_time_s` iguais;
   - mesmos parametros do motor.
4. Se a origem de fase nao for identica, aplicar alinhamento controlado:
   `theta0`, fase da portadora e fase do tick V/f.
5. Calibrar fase em uma janela curta de regime.
6. Reportar metricas em uma janela diferente.

Comando/base atual do mock:

```bash
python3 scripts/hil_fullstack_mock.py \
  <capture_or_reference.hilbin> \
  --freq-hz 60 --vdc 1240 --gate-mode gated \
  --theta0-deg <theta> \
  --out <results>/fullstack_mock/traces.csv \
  --png <results>/fullstack_mock/overlay.png
```

Observacao: hoje o mock usa `.hilbin` como referencia de tempo/telemetria. Para
L3 puro, o ideal e criar tambem um exportador CSV da simulacao VHDL e comparar
contra esse CSV, sem depender de captura real.

Artefatos esperados:

```text
verification/results/<campaign>/<case>/l3_top_sim/
  vhdl_top.csv
  c_fullstack.csv
  alignment.json
  metrics.json
  overlay.png
  overlay.html
```

Resultados L3 ja executados:

```text
Diretorio: verification/results/2026-06-29_campaign_01/S0_tacc1s_load000/l3_top_pwm_replay_sine_6ms/
Estimulo: Top_HIL com referencia externa senoidal 60 Hz, PWM 1 kHz, Vdc=1240 V, carga nula
Clock: 200 MHz, 26 ciclos, Ts=130 ns
Metodo: PWM replay; o C recebe va/vb/vc amostrados do caminho interno NPC->tensao do Top_HIL
Metricas: i_alpha NRMSE=4.04e-5, i_beta NRMSE=1.69e-4, flux_alpha MAE=1.53e-3 Wb, flux_beta MAE=7.67e-4 Wb, speed MAE=8.89e-4 rad/s
Artefatos: metrics.json, top_pwm_replay_vs_c.csv, overlay.html, README.md
Observacao: este resultado valida a cadeia integrada simulada sem erro de fase da portadora. O proximo L3 deve ser full-stack C, no qual o C/C++ tambem gera portadora e gate driver.
```

```text
ID: L3-S2
Diretorio: verification/results/2026-06-29_campaign_01/S0_tacc1s_load000/l3_top_pwm_replay_vf_50ms/
Estimulo: Top_HIL com rampa V/F 60 Hz/s, janela 0--50 ms, PWM 1 kHz, Vdc=1240 V, carga nula
Clock: 200 MHz, 26 ciclos, Ts=130 ns
Metodo: PWM replay; o C recebe va/vb/vc instantaneos do caminho interno NPC->tensao do Top_HIL
Metricas: i_alpha NRMSE=0.139%, i_beta NRMSE=0.101%, flux_alpha MAE=1.42e-3 Wb, flux_beta MAE=1.06e-3 Wb, speed MAE=3.18e-4 rad/s
Artefatos: metrics.json, top_pwm_replay_vs_c.csv, overlay.html, README.md
Observacao: paralelo L3 do caso L2 V/F 50 ms. Como a janela chega apenas a cerca de 3 Hz, serve para partida inicial, nao regime.
```

Criterio de aceite:

- em regime, corrente e fluxo devem ter erro baixo apos alinhamento;
- na partida, alem de erro ponto-a-ponto, reportar metricas de envelope, pico e
  tempo de subida;
- se L3 falhar, L4 provavelmente tambem falhara.

### L4-A: FPGA Real vs C/C++ com PWM Capturado

Pergunta respondida: o solver real da FPGA, sob o PWM realmente gerado, produz
as mesmas grandezas do modelo C/C++?

Esta e a comparacao mais importante para validar o HIL real sem depender de
replicar perfeitamente o modulador offline.

Entradas:

- arquivo `.hilbin` capturado;
- telemetria DMA;
- eventos PWM capturados;
- metadados de `Vdc`, motor, rampa e torque.

Procedimento:

1. Executar a captura real do cenario.
2. Confirmar no `.hilbin`:
   - taxa de telemetria proxima de `100 kHz`;
   - eventos PWM presentes;
   - `Vdc` e parametros do motor registrados;
   - ausencia de gaps longos de PWM.
3. Rodar o comparador offline usando PWM capturado.
4. O C/C++ deve receber as tensoes reconstruidas a partir do PWM real.
5. Comparar contra a telemetria da FPGA.
6. Reportar metricas de partida e regime separadamente.

Comando/base atual:

```bash
cd verification/cocotb
python3 scripts/hilbin_vs_c.py \
  ../../apps/hil-go/runs/<capture>.hilbin \
  --vdc <vdc> \
  --window 0.5 \
  --out reports/<case>/
```

Artefatos esperados:

```text
verification/results/<campaign>/<case>/l4_pwm_replay/
  capture.hilbin
  metrics.json
  partida.png
  regime.png
  partida.html
  regime.html
  traces_partida.npz
  traces_regime.npz
```

Criterio de aceite:

- regime deve apresentar erro baixo de corrente/fluxo;
- partida deve ser avaliada tambem por envelope e indicadores de pico, nao
  apenas erro ponto-a-ponto;
- qualquer divergencia deve ser cruzada com L2 e L3 para identificar origem.

### L4-B: FPGA Real vs Full-Stack C/C++

Pergunta respondida: a plataforma completa em FPGA, incluindo V/f, portadora,
gate driver e solver, reproduz o mesmo comportamento do full-stack C/C++?

Esta comparacao e util para demonstrar comportamento de sistema, mas e a mais
sensivel a sincronismo. Ela deve ser apresentada com cuidado metodologico.

Entradas:

- `.hilbin` real;
- mock C/C++ full-stack;
- parametros de alinhamento;
- metadados completos do ensaio.

Procedimento:

1. Rodar o mock em modo `gated`.
2. Varrer `theta0`, fase da portadora e fase do tick V/f.
3. Usar uma janela de calibracao em regime permanente.
4. Salvar o melhor alinhamento em `alignment.json`.
5. Gerar CSV/HTML/PNG com o alinhamento escolhido.
6. Calcular metricas finais em janela distinta.
7. Reportar partida e regime separadamente.

Comando/base atual:

```bash
python3 scripts/hil_fullstack_mock.py \
  apps/hil-go/runs/<capture>.hilbin \
  --freq-hz 60 \
  --vdc 1240 \
  --gate-mode gated \
  --theta0-deg <theta> \
  --skip <t_start_metrics> \
  --out verification/results/<campaign>/<case>/fullstack_mock/traces.csv \
  --png verification/results/<campaign>/<case>/fullstack_mock/overlay.png
```

Artefatos esperados:

```text
verification/results/<campaign>/<case>/fullstack_mock/
  alignment.json
  metrics.json
  traces.csv
  overlay.png
  overlay.html
```

Criterio de aceite:

- em regime, apos alinhamento, corrente e fluxo devem acompanhar fase e
  amplitude;
- na partida, avaliar metricas de envelope/pico/tempo de subida;
- declarar explicitamente que houve alinhamento de fase para compensar ausencia
  de referencia absoluta entre simulacao offline e captura real.

### L4-C: FPGA Real com `va/vb/vc` do Solver

Pergunta respondida: quando o C/C++ recebe exatamente a tensao que entrou no
solver da FPGA, qual e o erro residual?

Esta e a comparacao ideal para separar erro do solver de erro de modulador e
sincronismo. Ainda precisa ser implementada na telemetria.

Procedimento futuro:

1. Adicionar ao stream DMA ou a um stream auxiliar os sinais:
   `va_motor_solver`, `vb_motor_solver`, `vc_motor_solver`, ou estados NPC ja
   amostrados no tick do solver.
2. Registrar esses sinais no `.hilbin`.
3. Rodar o C/C++ alimentado diretamente por essas entradas.
4. Comparar contra `i_alpha`, `i_beta`, `flux_alpha`, `flux_beta`, `speed`.

Resultado esperado:

- erro residual deve representar majoritariamente ponto fixo, discretizacao e
  filtro de telemetria, nao mais sincronismo de PWM.

## Variaveis de Ensaio

| Variavel | Valores principais | Observacao |
| --- | --- | --- |
| Frequencia base | `60 Hz` | Perfil nominal V/f. |
| Vdc | registrar no `.hilbin` | Default atual do firmware: `1240 V`. |
| Rampa `t_acc` | `0.5 s`, `1 s`, `2 s`, `5 s` | Cobre partida rapida, nominal e quase-estatica. |
| Torque de carga | `0`, `0.25 Tn`, `0.5 Tn`, `0.75 Tn`, `1.0 Tn`, `1.1 Tn` | `1.1 Tn` somente em janela curta. |
| Fase/alinhamento | `theta0`, fase da portadora, fase do tick V/F | Usado apenas na comparacao full-stack. |

## Grupos de Teste

### Grupo A: Partida e Aceleracao

| ID | Rampa | Carga | Objetivo |
| --- | --- | --- | --- |
| A1 | `0.5 s` | `0 Tn` | Corrente de partida e fluxo a vazio. |
| A2 | `0.5 s` | `1.0 Tn` | Pior caso de corrente com rampa rapida. |
| A3 | `1.0 s` | `0.5 Tn` | Caso base do HIL. |
| A4 | `2.0 s` | `1.0 Tn` | Partida suave sob carga nominal. |
| A5 | `5.0 s` | `0 Tn` | Erro acumulado e estabilidade. |
| A6 | `5.0 s` | `1.0 Tn` | Torque com baixa aceleracao. |
| A7 | `2.0 s` | `1.1 Tn` | Sobrecarga curta e margem numerica. |

### Grupo B: Perturbacao de Carga em Regime

| ID | Condicao inicial | Perturbacao | Metricas centrais |
| --- | --- | --- | --- |
| B1 | `60 Hz`, `0.25 Tn` | `0.25 -> 0.75 Tn` | Queda de velocidade, pico de corrente, recuperacao. |
| B2 | `60 Hz`, `0.50 Tn` | `0.50 -> 1.00 Tn` | Resposta a carga nominal. |
| B3 | `60 Hz`, `0.75 Tn` | `0.75 -> 0.25 Tn` | Sobressinal apos alivio de carga. |
| B4 | `60 Hz`, `0.50 Tn` | triangular `0.25..0.75 Tn` | Seguimento periodico. |
| B5 | `60 Hz`, `0.50 Tn` | senoidal `0.25..0.75 Tn` | Erro de fase e amplitude. |

### Grupo C: Dinamica Adicional

| ID | Acao | Carga | Objetivo |
| --- | --- | --- | --- |
| C1 | `60 Hz -> 0 Hz` em `1 s` | `0.5 Tn` | Desaceleracao e corrente transitoria. |
| C2 | `+60 Hz -> -60 Hz` | `0.5 Tn` | Passagem por zero e pico de torque. |
| C3 | `0 -> 30 Hz -> 60 Hz` | `0.75 Tn` | Mudanca de setpoint em dois patamares. |
| C4 | `60 Hz` constante | torque pulsante | Carga periodica. |

## Metricas

Metricas por sinal:

- MAE.
- RMSE.
- NRMSE.
- erro maximo absoluto.
- erro de amplitude fundamental de corrente.
- erro de fase fundamental de corrente.

Metricas especificas de partida:

- pico de corrente.
- tempo ate `90%` da velocidade final.
- overshoot de corrente.
- erro RMS por envelope.
- erro de velocidade durante a rampa.

Metricas especificas de perturbacao de carga:

- queda maxima de velocidade.
- pico de corrente apos degrau.
- tempo de recuperacao.
- erro de amplitude e fase para perturbacoes periodicas.

## Protocolo de Alinhamento

Para comparacoes full-stack, a fase inicial nao e observavel diretamente na
captura. O alinhamento deve ser tratado como parte do metodo experimental.

Procedimento:

1. Definir uma janela de calibracao em regime permanente.
2. Varrer `theta0`, fase da portadora e fase do tick V/F.
3. Escolher o conjunto que minimiza uma metrica definida, por exemplo
   `NRMSE(i_alpha) + NRMSE(i_beta)`.
4. Reportar as metricas finais em uma janela diferente da usada na calibracao.
5. Registrar os parametros escolhidos em `alignment.json`.

Nao usar a mesma janela para calibracao e para reportar resultado final, exceto
quando o objetivo for apenas diagnostico.

## Protocolo de Aquisicao L4

Para cada ensaio:

1. Programar parametros do motor.
2. Programar `Vdc`, frequencia, rampa, torque e destino de telemetria.
3. Executar `run`.
4. Aguardar evento ou tempo definido pelo cenario.
5. Aplicar perturbacao quando houver.
6. Executar `stop` ou `detach`.
7. Salvar `.hilbin` com metadados completos.
8. Gerar relatorios offline.

Metadados minimos por captura:

- ID do cenario.
- data/hora.
- commit git.
- bitstream/versao FPGA.
- versao PS/gateway.
- parametros do motor.
- `Vdc`.
- frequencia alvo.
- rampa `t_acc`.
- torque inicial e perfil de torque.
- taxa de telemetria.
- decimacao DMA.
- observacoes de alinhamento.

## Custo de Simulacao Observado

Os tempos abaixo foram medidos durante a campanha `2026-06-29_campaign_01` e
devem orientar a escolha dos proximos ensaios. Eles variam com a maquina, mas a
ordem de grandeza e importante para o planejamento.

| Caso | Nivel | Tempo fisico simulado | Tempo de parede observado | Uso recomendado |
| --- | --- | ---: | ---: | --- |
| `l2_sine_1cycle_realts` | L2 | 16,7 ms | ~174 s | Diagnostico de acumulacao em seno ideal. |
| `l2_vf_50ms_realts` | L2 | 50 ms | ~237 s | Comparacao curta do solver isolado. |
| `l2_vf_2s_realts` | L2 | 2,0 s | ~3,13 h | Resultado L2 principal de partida completa. |
| `l3_top_pwm_replay_sine_6ms` | L3 | 5,2 ms uteis + startup PWM | ~71 s | Diagnostico L3 senoidal. |
| `l3_top_pwm_replay_vf_50ms` | L3 | 50 ms uteis + startup PWM | ~588 s | Resultado L3 V/F curto. |

O caso `L3 V/F 2 s` foi executado e levou `6,35 h` nesta maquina com `record_interval=800`. A execucao gerou `19.232` linhas CSV e calculou metricas em `15.384.215` amostras validas. Sem decimacao, o mesmo caso geraria cerca de `15,4 milhoes` de linhas CSV. Casos longos devem permanecer com decimacao de CSV e metricas acumuladas em todos os passos.


## Organizacao dos Dados

Diretorio recomendado:

```text
verification/results/
  2026-06-29_campaign_01/
    manifest.json
    A3_tacc1s_load050/
      raw/
        capture.hilbin
        metadata.json
      l2_solver/
        metrics.json
        overlay.png
        overlay.html
      l4_pwm_replay/
        metrics.json
        overlay.png
        overlay.html
      fullstack_mock/
        alignment.json
        metrics.json
        overlay.png
        overlay.html
        traces.csv
      notes.md
```

`manifest.json` deve listar todos os cenarios executados, caminhos dos arquivos,
parametros principais e status (`ok`, `repeat`, `invalid`).

## Arquivos Atuais de Diagnostico

Captura usada ate agora:

```text
apps/hil-go/runs/capture_20260629_012810.828.hilbin
```

Relatorios gerados:

```text
verification/cocotb/reports/hilbin_vdc1240_grid_full/
verification/cocotb/reports/fullstack_mock/capture_20260629_012810.828/
```

Mock full-stack atual:

```text
scripts/hil_fullstack_mock.py
```

Melhor alinhamento diagnostico encontrado:

```text
gate_mode = gated
theta0_deg = 64
freq_hz = 60
vdc = 1240
skip = 2.366
```

Metricas do mock gated nessa captura:

```text
i_alpha NRMSE ~= 7.55%
i_beta  NRMSE ~= 8.73%
flux_a  NRMSE ~= 0.50%
flux_b  NRMSE ~= 0.50%
speed MAE ~= 0.557 rad/s
```

## Proximos Passos

1. Consolidar scripts para gerar `metrics.json`, `overlay.html` e `overlay.png`
   com nomes padronizados.
2. Criar `manifest.json` da campanha.
3. Repetir o caso A3 com `.hilbin` novo contendo metadados completos.
4. Executar comparacao L4 via PWM capturado.
5. Executar comparacao full-stack com varredura de fase.
6. Validar um subconjunto do `NPCGateDriver` C contra VHDL para declarar a
   fidelidade do mock.
7. Rodar matriz reduzida A1, A2, A3, A4 e B2 antes da matriz completa.


## Registro Atual - L3 Full-Stack Mock

Alem do L3 PWM replay, foi criado um diagnostico L3 full-stack offline em
`verification/cocotb/scripts/top_fullstack_mock.py`. Esse script recebe um CSV
previamente gerado pelo `Top_HIL` em cocotb/NVC e executa um mock C/C++ que gera
independentemente a rampa V/f, a portadora triangular, os comandos PWM, a logica
do gate-driver e o modelo do motor. Assim, ele nao usa `va/vb/vc` do VHDL como
entrada do motor C; a comparacao e feita contra as correntes, fluxos e velocidade
do `Top_HIL` exportados no CSV.

Resultados adicionados ao caso S0:

```text
verification/results/2026-06-29_campaign_01/S0_tacc1s_load000/l3_fullstack_mock_vf_50ms/
verification/results/2026-06-29_campaign_01/S0_tacc1s_load000/l3_fullstack_mock_vf_2s/
```

No V/F de 50 ms, o mock full-stack apresentou `i_alpha` NRMSE de aproximadamente
0,143% e `i_beta` NRMSE de 0,133%, coerente com o L3 PWM replay curto. No V/F de
2 s, calculado sobre o CSV decimado da simulacao longa, o erro global foi
aproximadamente 5,67% em `i_alpha` e 5,77% em `i_beta`. A decomposicao temporal
mostra que o pior trecho esta na aceleracao entre 0,05 s e 0,5 s, enquanto em
regime entre 1,5 s e 2,0 s o erro cai para cerca de 3,35%--3,36% nas correntes e
o erro medio de fluxo fica da ordem de `5e-4 Wb`.

Interpretacao metodologica: para a dissertacao, esses resultados devem ser
separados por janela temporal. A metrica global de partida mistura erro de fase,
transitorio eletromecanico e acumulacao de pequenas diferencas de modulacao; por
isso ela nao deve ser a unica evidencia. O texto deve reportar pelo menos:
partida inicial, aceleracao, aproximacao ao regime e regime permanente. O mesmo
conjunto de parametros de motor, `Vdc`, frequencia PWM, clock e passo do solver
deve ser repetido em todo ensaio antes de qualquer comparacao quantitativa.

### Varredura de Fase da Portadora no L3 Full-Stack

Foi executada uma varredura de `carrier_phase_cycles` no mock full-stack usando o CSV L3 V/F de 2 s. As fases avaliadas foram `0`, `6250`, `12500`, `25000`, `37500`, `50000`, `62500`, `75000`, `87500` e `99999` ciclos de clock, cobrindo a portadora de 1 kHz em 200 MHz. A melhor fase foi `0` ciclos; as demais aumentaram o erro global e tambem pioraram o regime permanente. Portanto, para esta campanha, o desalinhamento grosseiro da fase da portadora nao explica a diferenca de partida.

Resultado registrado em:

```text
verification/results/2026-06-29_campaign_01/S0_tacc1s_load000/l3_fullstack_phase_sweep_vf_2s/
```

Proxima investigacao recomendada: comparar explicitamente as leis de inicializacao do V/F, acumulador de angulo, habilitacao inicial do gate-driver, estados iniciais de fluxo/corrente e tempo efetivo de aplicacao de tensao antes do primeiro ponto registrado.

### Regra Obrigatoria de Parametros Identicos

Durante a geracao do L3 V/F instrumentado de 100 ms foi identificada uma fonte concreta de erro metodologico: defaults diferentes entre o `Top_HIL` e o modelo C de referencia. Quando `IM_RS` e `IM_J` nao eram explicitados, o `Top_HIL` podia operar com `Rs=0.435` e `J=0.192`, enquanto o modelo C podia usar `Rs=0.4396` e `J=0.4`. Essa diferenca sozinha elevou o erro de `i_beta` no trecho 0--100 ms para aproximadamente 5,04%.

Apos corrigir os defaults e rerodar com parametros explicitos, o mesmo caso caiu para `i_alpha` NRMSE de aproximadamente 0,080% e `i_beta` NRMSE de 0,868%, com velocidade MAE de `0,0318 rad/s`. Portanto, nenhum resultado deve ser usado na dissertacao sem registrar no respectivo `metrics.json` os parametros do motor e sem conferir que C, VHDL, mock, PSIM e FPGA usam o mesmo conjunto numerico.

Caso valido registrado em:

```text
verification/results/2026-06-29_campaign_01/S0_tacc1s_load000/l3_top_pwm_replay_vf_100ms_instrumented_matched_params/
```


### Comparacao L2 vs L3 na Janela Critica de Partida

Para isolar a origem da divergencia observada no L3 instrumentado, foi executado um L2 V/F de 300 ms com os mesmos parametros de motor, `Ts=130 ns`, `V_peak=620 V`, rampa de 60 Hz/s e carga nula. O ensaio L2 falhou apenas no assert automatico de fluxo (`flux_alpha MAE=0,0197 Wb`), mas os dados foram salvos e sao validos para diagnostico.

A comparacao mostrou:

```text
L2 300 ms: i_alpha NRMSE = 5,35%, i_beta NRMSE = 5,40%, speed MAE = 0,265 rad/s
L3 300 ms: i_alpha NRMSE = 5,42%, i_beta NRMSE = 5,33%, speed MAE = 0,265 rad/s
```

Portanto, a maior parcela do erro de partida ja esta presente no solver isolado. A cadeia PWM/modulador/tensao do L3 nao aumenta substancialmente o erro nessa janela. A proxima investigacao deve focar a equivalencia numerica entre o modelo C/C++ e o solver VHDL durante rampas V/F de baixa frequencia, incluindo integrador, atualizacao de coeficientes, representacao de estados e diferencas entre entrada ideal continua e entrada discretizada por passo.


### Ensaio L2 em 12 Hz Constante

Para separar o efeito da rampa V/f do efeito de baixa frequencia, foi executado um L2 de 300 ms com frequencia praticamente constante em 12 Hz e tensao de pico de 124 V, mantendo os mesmos parametros de motor. O caso apresentou `i_alpha` NRMSE de 4,07% e `i_beta` NRMSE de 3,77%, menor que a rampa V/f de 300 ms (`5,35%` e `5,40%`), mas ainda significativo.

Conclusao: a rampa intensifica e redistribui o erro entre os eixos, mas a divergencia entre C e VHDL ja aparece no solver isolado durante transientes de baixa frequencia. Os proximos ensaios devem avaliar frequencias constantes adicionais e/ou inicializacao de fluxo para separar erro de modelo, erro de integrador e erro de estado inicial.


### Ensaio L2 com Rotor Praticamente Travado

Foi executado um ensaio L2 em 12 Hz/124 V com `J=1e6`, mantendo os demais parametros do motor. O objetivo foi congelar a dinamica mecanica e observar apenas a resposta eletrica do solver. Nessa condicao, o erro de corrente caiu para `i_alpha` NRMSE de 0,0565% e `i_beta` NRMSE de 0,0602%, enquanto o caso normal em 12 Hz apresentava 4,07% e 3,77%.

Conclusao: o nucleo eletrico do solver esta coerente com o C quando a velocidade fica praticamente fixa. A divergencia de partida esta associada principalmente ao acoplamento mecanico, isto e, torque eletromagnetico, atualizacao de velocidade, escorregamento e realimentacao da velocidade nas equacoes eletricas.
