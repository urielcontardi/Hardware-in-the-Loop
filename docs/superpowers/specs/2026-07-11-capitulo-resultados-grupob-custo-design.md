# Capítulo de Resultados — Grupo B e Custo Computacional

## Contexto e motivação

O spec anterior (`docs/superpowers/specs/2026-07-07-capitulo-resultados-design.md`)
cobriu a primeira versão do capítulo de resultados: estrutura, scripts
(`chapter_common.py`, `chapter_tables.py`, `chapter_figures.py`) e conteúdo
para S0 + Grupo A (A1-A7), a partir da `campaign_03`. Ele explicitamente
deixou de fora "rodar Grupo B" porque, na época, o Grupo B ainda não tinha
sido executado.

Desde então, o commit `97ac745` ("adiciona Grupo B (B1-B3) a matriz da
campaign_03") passou a gerar dados de L2 e L3 para B1, B2 e B3
(degraus de carga em regime) na mesma campanha. Esses dados existem em
`verification/results/2026-07-04_campaign_03/B{1,2,3}_*/`, mas nenhum
script/tabela/figura foi gerado a partir deles — a lacuna descrita aqui.

Além disso, nenhum documento até agora consolidou o **custo computacional**
das simulações (tempo de parede necessário para rodar cada cenário L2/L3).
Esse dado existe, mas espalhado em texto solto no
`verification/results/2026-06-29_campaign_01/README.md`; a fonte estruturada
usada aqui é o resumo nativo que o próprio cocotb grava ao final de cada
`run.log` (ver seção 2). Esse dado é o argumento mais direto de "valor do
trabalho": a verificação por cossimulação RTL leva milhares de vezes mais
tempo de parede do que o tempo de motor simulado, o que motiva a necessidade
de execução em FPGA real (L4) para qualquer uso em tempo real.

Este spec cobre duas extensões independentes ao pipeline existente: (1)
Grupo B nas tabelas/figuras do capítulo, e (2) uma tabela/figura nova de
custo computacional cobrindo Grupo A e Grupo B. **Não** cobre Grupo C (sem
dados), L4 real, ou unificação da fórmula de NRMSE entre níveis — essas
lacunas continuam documentadas como limitação/trabalho futuro.

### Correção de rota: duas pipelines divergentes, só uma está viva

Verificação feita durante o planejamento de implementação: os `\includegraphics`
de `4-Resultados.tex` (`HIL_GrupoA03_A1_CorrenteFluxoVelocidade.pdf`,
`..._A7_...`, `..._Sintese_...`) **não** vêm do
`verification/cocotb/scripts/chapter_figures.py` descrito no spec de
2026-07-07 — vêm de um script separado,
`Mestrado_latex/Mestrado/scripts/gerar_figuras_resultados_hil.py`, que lê os
mesmos dados de `campaign_03` só que direto do repo HIL (path absoluto) e
grava direto em `Mestrado/figuras/`, com um layout melhor (grade 5×2:
sobreposição + coluna de erro, decimação da série para ~4500 pontos,
métricas embutidas no subtítulo da figura). A saída de `chapter_figures.py`
(`forma_onda_A1.pdf`, `resumo_l2_vs_l3.pdf`, `resumo_tendencia.pdf` em
`docs/results-chapter/figures/`) não é referenciada em lugar nenhum da
dissertação — ficou órfã.

As **tabelas** não têm esse problema: `metricas_grupo_a.tex`/
`parametros_grupo_a.tex` (gerados por `chapter_tables.py`) são a fonte dos
números que foram manualmente retranscritos (com vírgula decimal) para o
`\quadro` do capítulo — servem como referência confiável, mesmo sem
`\input` direto.

Decisão: as **figuras** novas de Grupo B e custo computacional entram em
`gerar_figuras_resultados_hil.py` (Mestrado_latex), não em
`chapter_figures.py` (HIL). As **tabelas** novas continuam em
`chapter_tables.py`/`chapter_common.py` (HIL), como descrito abaixo — esse
pipeline funciona e é a fonte usada. O `chapter_figures.py` original do
Grupo A não é alterado nem removido por este spec (fora de escopo; fica
como código órfão documentado, não uma regressão introduzida aqui).

## Regra de ouro (herdada do spec anterior)

Os scripts continuam nunca confiando em `status`/`l2_results`/`l3_results`
do `manifest.json` — sempre verificam a existência do arquivo esperado em
disco (`metrics.json`, CSV). Caso ausente é tratado como lacuna ("—" em
tabela, figura pulada com aviso), nunca como erro fatal.

## 1. Extensão do Grupo B

### `chapter_common.py`

- Nova resolução de diretório por grupo: para casos com
  `group == "perturbacao_carga"` (B1-B3, confirmado no `manifest.json` da
  `campaign_03`), o glob de nível usa os padrões observados em disco:
  `glob("l2_step_*")` para L2 e `glob("l3_top_pwm_replay_step_*")` para L3
  (em vez de `l2_vf_*_realts` / `l3_top_pwm_replay_vf_*`, usados no Grupo A).
  A função que hoje resolve diretório por caso passa a receber o padrão de
  glob como parâmetro, dependente do `group` do caso — não duas cópias da
  lógica.
- `load_case_table` passa a aceitar um filtro de grupo (`group="a"` ou
  `group="b"`), reaproveitando o mesmo carregamento de métricas.
- `write_gaps_report` passa a incluir os casos do Grupo B na mesma
  varredura, sem seção separada em `gaps.md` (mesma lista, mais linhas).

### `chapter_tables.py`

- `parametros_grupo_b.tex`: **não** é uma grade t_acc×carga como o Grupo A
  (não se aplica — B varia patamar de carga e sentido do degrau, não
  rampa). É uma tabela simples de 3 linhas: caso, carga inicial (Tn), carga
  final (Tn), sentido (subida/descida). Gerada a partir dos campos do
  `manifest.json`/nome de diretório de cada caso B (`B1_step025_to075` →
  0,25→0,75 Tn subida), não hardcoded.
- `metricas_grupo_b.tex`: mesmo layout de `metricas_grupo_a.tex` (uma linha
  por caso, colunas L2 e L3 lado a lado: NRMSE iα/iβ, MAE fluxo α/β, MAE
  velocidade), célula "—" onde faltar.
- `transiente_grupo_b.tex` (novo, não existe equivalente no Grupo A):
  os `metrics.json` do Grupo B já trazem um bloco `transient` (chaves
  `speed_before_step_rad_s`, `speed_peak_deviation_rad_s`,
  `current_peak_a`, `recovery_time_s`, para VHDL e C separadamente —
  confirmado em `B1_step025_to075/l2_step_1s/metrics.json`, produzido pela
  função `compute_transient_metrics` adicionada com o próprio Grupo B).
  Isso é mais informativo que NRMSE global para um ensaio de degrau: mostra
  o desvio de velocidade após o degrau e o tempo de recuperação,
  comparando VHDL e C lado a lado. Tabela: uma linha por caso×nível,
  colunas `desvio pico velocidade VHDL/C (rad/s)` e
  `tempo de recuperação VHDL/C (s)`. Célula "—" onde o bloco `transient`
  não existir no `metrics.json` (ex.: se um caso futuro não computar essa
  métrica).

Saída em `docs/results-chapter/tables/`, mesma convenção (booktabs,
`\input`-ável).

### `chapter_figures.py`

Todos os três casos do Grupo B recebem figura (não apenas um "caso
representativo" como A1/A7 no Grupo A — aqui os três degraus são
qualitativamente diferentes entre si: magnitude e sentido). Implementado em
`Mestrado_latex/Mestrado/scripts/gerar_figuras_resultados_hil.py`, reaproveitando
`plot_case`/`decimate`/`read_csv`/`read_metrics` já existentes nesse
script (grade 5×2, sobreposição + coluna de erro, decimação a ~4500
pontos, métricas no subtítulo — mesmo estilo do Grupo A):

- `HIL_GrupoB_B1_CorrenteFluxoVelocidade.pdf`, `..._B2_...`, `..._B3_...`:
  chamando `plot_case` com um novo dicionário `CASES_B` (mesma estrutura de
  `CASES`, apontando para `B{1,2,3}_step*/l3_top_pwm_replay_step_1s`),
  janela completa de 1 s.
- `HIL_GrupoB_B1_ZoomDegrau.pdf`, `..._B2_...`, `..._B3_...`: nova função
  `plot_zoom_degrau`, recorte da corrente (iα, iβ) em torno do instante do
  degrau (`t_step=0,6s`, janela 0,45-0,75s — 150 ms antes/depois). Esse
  recorte é o que efetivamente mostra a resposta dinâmica ao degrau; a
  janela cheia de 1 s comprime demais o instante de interesse.
- `HIL_GrupoB_Sintese.pdf`: nova função `plot_summary_b`, barras agrupadas
  (NRMSE iα, iβ) por caso B1-B3, L2 vs L3 — mesmo padrão de
  `plot_summary` (Grupo A), caso B tem grade de comparação própria (não
  reaproveita o gráfico existente, que é hardcoded para os 7 casos A).
- `HIL_GrupoB_Tendencia.pdf`: NRMSE/MAE em função da magnitude do degrau
  (|carga final − carga inicial|) e do sentido (subida: B1, B2; descida:
  B3), evidenciando se a direção do degrau afeta o erro.

Saída direto em `Mestrado_latex/Mestrado/figuras/`, PDF vetorial
(`matplotlib`, backend `Agg`), mesmo estilo/paleta preto-e-cinza do script
existente. `chapter_figures.py` (HIL repo) não é tocado por este spec.

## 2. Custo computacional (novo)

### Fonte de dados: `run.log`, não `sim_benchmark.json`

Investigado durante o planejamento: `verification/cocotb/reports/sim_benchmark.json`
só é alimentado por `test_tim_solver_vf.py` (import confirmado só nesse
arquivo e em `test_tim_solver_sine.py`/`test_tim_solver_reference.py`) — para
a janela de execução da `campaign_03` (2026-07-04) existem apenas **3**
entradas, cobrindo só alguns casos L2 de rampa V/f. Nenhum L3
(`test_top_hil.py`) e nenhum caso do Grupo B tem entrada ali. Usar esse
arquivo deixaria a tabela de custo computacional quase toda "—".

Em vez disso: **todo** `run.log` de teste cocotb (L2 e L3, Grupo A e B)
termina com o resumo nativo do cocotb, por exemplo (confirmado em
`B1_step025_to075/l3_top_pwm_replay_step_1s/run.log`):

```text
** TEST                                           STATUS  SIM TIME (ns)  REAL TIME (s)  RATIO (ns/s) **
** tests.test_top_hil.test_top_hil_pwm_replay_l3   PASS   1001001120.00       12037.30      83158.29  **
** TESTS=1 PASS=1 FAIL=0 SKIP=0                           1001001120.00       12037.31      83158.22  **
```

Confirmado que 26 dos 28 `run.log` da `campaign_03` têm essa linha
`TESTS=`; os 2 que não têm são os casos `l3_fullstack_mock_*` (mock C puro,
não passa pelo cocotb, não tem "tempo de parede de simulação RTL" para
reportar — exclusão correta, não uma lacuna). `SIM TIME (ns)` é o tempo de
motor simulado; `REAL TIME (s)` é o tempo de parede — exatamente os dois
números necessários, sem precisar casar nada por timestamp.

### Novo módulo `chapter_common.py`

- `parse_run_log_timing(run_log_path: Path) -> tuple[float, float] | None`:
  lê o `run.log` do caso, procura a linha que começa com `** TESTS=` via
  regex, retorna `(sim_time_s, wall_time_s)` a partir dos campos
  `SIM TIME (ns)` (convertido para segundos) e `REAL TIME (s)`. Retorna
  `None` se o arquivo não existir ou a linha não for encontrada — nunca
  lança exceção.

### `chapter_tables.py` (HIL repo)

- `tempo_simulacao.tex`: uma linha por caso×nível (S0, A1-A7, B1-B3 × L2/L3
  — todos os grupos já cobertos, não só o novo), colunas: tempo de motor
  simulado (s), tempo de parede (s), fator de desaceleração
  (`wall_time_s / sim_time_s`), a partir de
  `chapter_common.parse_run_log_timing`. Célula "—" onde o `run.log` não
  existir ou não tiver a linha `TESTS=` (ex.: os casos `fullstack_mock`, que
  não são cocotb). Saída em `docs/results-chapter/tables/`, mesma convenção
  das tabelas existentes.

### `gerar_figuras_resultados_hil.py` (Mestrado_latex, não HIL repo)

- `HIL_CustoComputacional.pdf`: nova função `plot_custo_computacional`,
  barras do fator de desaceleração por caso, L2 vs L3, eixo Y em escala
  logarítmica (a ordem de grandeza observada é de milhares×). Cobre todos
  os casos com `run.log` parseável, Grupo A e B juntos. Este script já lê
  `campaign_03` direto (path absoluto `HIL_ROOT`), então repete a mesma
  extração por regex do `run.log` descrita acima, de forma independente/
  self-contained (mesmo padrão do resto do script, que não importa
  `chapter_common` do outro repo). Saída direto em `Mestrado/figuras/`.

### Uso no capítulo

O texto de apoio (fora deste spec, cabe à redação futura) deve registrar
que o fator de desaceleração de milhares× é o argumento central para a
necessidade de execução em FPGA real (L4): a cossimulação RTL usada para
verificação L2/L3 é adequada para validar corretude, mas inviável para
qualquer operação em tempo real — papel que só a FPGA cumpre.

## 3. Organização de diretórios

Nenhuma pasta nova; os arquivos entram nas pastas já versionadas, só que em
dois repositórios diferentes (tabelas no HIL, figuras no Mestrado_latex —
ver correção de rota acima):

```text
# repo Hardware-in-the-Loop
docs/results-chapter/
  tables/
    parametros_grupo_b.tex
    metricas_grupo_b.tex
    transiente_grupo_b.tex
    tempo_simulacao.tex
  gaps.md   (atualizado, agora cobre Grupo B também)

# repo Mestrado_latex
Mestrado/figuras/
  HIL_GrupoB_B1_CorrenteFluxoVelocidade.pdf
  HIL_GrupoB_B2_CorrenteFluxoVelocidade.pdf
  HIL_GrupoB_B3_CorrenteFluxoVelocidade.pdf
  HIL_GrupoB_B1_ZoomDegrau.pdf
  HIL_GrupoB_B2_ZoomDegrau.pdf
  HIL_GrupoB_B3_ZoomDegrau.pdf
  HIL_GrupoB_Sintese.pdf
  HIL_GrupoB_Tendencia.pdf
  HIL_CustoComputacional.pdf
```

## 4. Testes

- `chapter_common.load_case_table(group="b")` sobre um manifest de fixture
  com 2-3 casos B (um deles sem L3 em disco), confirmando resolução correta
  do padrão de glob `l2_step_*`/`l3_top_pwm_replay_step_*` e célula `None`
  quando ausente.
- `chapter_common.parse_run_log_timing` com um `run.log` de fixture contendo
  a linha `TESTS=` real (copiada de um caso existente) confirma que
  `(sim_time_s, wall_time_s)` é extraído corretamente; um `run.log` de
  fixture sem essa linha (simulando `fullstack_mock`) confirma que retorna
  `None`.
- `chapter_tables` gerando `parametros_grupo_b.tex`/`metricas_grupo_b.tex`/
  `tempo_simulacao.tex` a partir das fixtures acima, conferindo célula
  vazia ("—") nos campos sem dado.
- Sem teste automatizado de conteúdo visual para as novas funções de
  `gerar_figuras_resultados_hil.py` (mesma decisão do spec anterior para
  `chapter_figures.py`; esse script já não tem nenhum teste hoje) — a
  verificação é rodar o script contra `campaign_03` de verdade e conferir
  visualmente que os PDFs abrem e fazem sentido.

## Fora de escopo

- Grupo C (sem dados ainda) e validação L4 em hardware real — continuam
  como limitação/trabalho futuro documentado no capítulo, não resolvidos
  aqui.
- Unificar a fórmula de NRMSE entre L2/L3 e L4.
- Rodar novas simulações ou corrigir os casos L2 do Grupo A ainda
  bloqueados por permissão — este spec só consome dado já existente em
  disco.
- Reescrever `build_campaign_dashboard.py` ou os overlays Plotly
  existentes — continuam servindo para inspeção durante o desenvolvimento.
- Texto final em português para o capítulo — este spec cobre
  dados/tabelas/figuras; a redação corrida é etapa posterior, depois que
  os artefatos estiverem confirmados.
