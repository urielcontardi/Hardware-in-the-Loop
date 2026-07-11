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
Esse dado existe, mas espalhado: em texto solto no
`verification/results/2026-06-29_campaign_01/README.md` e, de forma
estruturada, em `verification/cocotb/reports/sim_benchmark.json` — um log
único, append-only, alimentado por `models/sim_benchmark.py` a cada execução
de teste cocotb (campo `wall_time_s`, `sim_duration_s`, `test_name`, `date`,
sem referência direta ao caso/campanha). Esse dado é o argumento mais direto
de "valor do trabalho": a verificação por cossimulação RTL leva milhares de
vezes mais tempo de parede do que o tempo de motor simulado, o que motiva a
necessidade de execução em FPGA real (L4) para qualquer uso em tempo real.

Este spec cobre duas extensões independentes ao pipeline existente: (1)
Grupo B nas tabelas/figuras do capítulo, e (2) uma tabela/figura nova de
custo computacional cobrindo Grupo A e Grupo B. **Não** cobre Grupo C (sem
dados), L4 real, ou unificação da fórmula de NRMSE entre níveis — essas
lacunas continuam documentadas como limitação/trabalho futuro.

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

Saída em `docs/results-chapter/tables/`, mesma convenção (booktabs,
`\input`-ável).

### `chapter_figures.py`

Todos os três casos do Grupo B recebem figura (não apenas um "caso
representativo" como A1/A7 no Grupo A — aqui os três degraus são
qualitativamente diferentes entre si: magnitude e sentido):

- `forma_onda_B1.pdf`, `forma_onda_B2.pdf`, `forma_onda_B3.pdf`: mesmo
  formato do Grupo A (3 sub-eixos empilhados: iα, iβ, velocidade; VHDL vs
  referência C), janela completa de 1 s. Reaproveita a função de plot já
  usada para `forma_onda_A1`/`forma_onda_A7`, apenas apontando para o
  diretório L3 do caso B correspondente (preferindo L3 sobre L2, mesma
  regra do Grupo A, por incluir o PWM).
- `zoom_degrau_B1.pdf`, `zoom_degrau_B2.pdf`, `zoom_degrau_B3.pdf`: zoom na
  corrente (iα, iβ) em torno do instante do degrau (`t_step=0,6s`, janela
  0,45-0,75 s — 150 ms antes/depois), no mesmo estilo `zoom_multipanel` já
  usado nas figuras L1 (regime transiente/permanente). Esse recorte é o que
  efetivamente mostra a resposta dinâmica ao degrau; a janela cheia de 1 s
  comprime demais o instante de interesse.
- `resumo_l2_vs_l3_grupob.pdf`: barras agrupadas (NRMSE iα, iβ) por caso
  B1-B3, uma cor por nível — mesmo padrão de `resumo_l2_vs_l3.pdf`, arquivo
  separado para não alterar o que o capítulo já referencia para o Grupo A.
- `resumo_tendencia_grupob.pdf`: NRMSE/MAE em função da magnitude do degrau
  (|carga final − carga inicial|) e do sentido (subida: B1, B2; descida:
  B3), evidenciando se a direção do degrau afeta o erro.

Saída em `docs/results-chapter/figures/`, PDF vetorial (`matplotlib`,
backend `Agg`), mesma paleta preto/cinza já usada nas figuras existentes.

## 2. Custo computacional (novo)

### Fonte de dados e problema de correlação

`verification/cocotb/reports/sim_benchmark.json` é um log único (todas as
execuções de teste cocotb já rodadas, de qualquer campanha), sem campo de
caso/campanha — só `test_name`, `sim_duration_s`, `wall_time_s`,
`msteps_per_s`, `date`. `sim_duration_s` sozinho não desambigua (ex.: A1 e
A2 têm a mesma duração de janela, 0,5 s, mas são execuções e casos
diferentes).

Estratégia de casamento: para cada caso×nível da `campaign_03`, tomar o
horário de modificação (`mtime`) do `metrics.json` em disco (já confiável,
é a mesma regra de "arquivo em disco é fonte da verdade") e casar com a
entrada de `sim_benchmark.json` cujo campo `date` esteja mais próxima
(tolerância de 5 minutos). Se nenhuma entrada cair dentro da tolerância, o
caso fica sem dado de custo computacional (célula "—"), sem interromper o
script. Casos com mais de uma entrada dentro da tolerância: usa a mais
próxima em tempo absoluto, registra aviso no stderr.

### Novo módulo `chapter_common.py`

- `load_benchmark_log(path) -> list[BenchmarkEntry]`: lê
  `sim_benchmark.json`, retorna lista vazia se o arquivo não existir.
- `match_benchmark(entries, target_mtime, tolerance_s=300) -> BenchmarkEntry | None`:
  implementa o casamento por proximidade de timestamp descrito acima.

### `chapter_tables.py`

- `tempo_simulacao.tex`: uma linha por caso×nível (S0, A1-A7, B1-B3 × L2/L3
  — todos os grupos já cobertos, não só o novo), colunas: tempo de motor
  simulado (s), tempo de parede (s), fator de desaceleração
  (`wall_time_s / sim_duration_s`). Célula "—" onde não houver casamento de
  benchmark.

### `chapter_figures.py`

- `custo_computacional.pdf`: barras do fator de desaceleração por caso,
  L2 vs L3, eixo Y em escala logarítmica (a ordem de grandeza observada é
  de milhares×). Cobre todos os casos com dado de custo disponível, Grupo A
  e B juntos.

### Uso no capítulo

O texto de apoio (fora deste spec, cabe à redação futura) deve registrar
que o fator de desaceleração de milhares× é o argumento central para a
necessidade de execução em FPGA real (L4): a cossimulação RTL usada para
verificação L2/L3 é adequada para validar corretude, mas inviável para
qualquer operação em tempo real — papel que só a FPGA cumpre.

## 3. Organização de diretórios

Nenhuma pasta nova; os arquivos entram nas pastas já versionadas:

```text
docs/results-chapter/
  figures/
    forma_onda_B1.pdf
    forma_onda_B2.pdf
    forma_onda_B3.pdf
    zoom_degrau_B1.pdf
    zoom_degrau_B2.pdf
    zoom_degrau_B3.pdf
    resumo_l2_vs_l3_grupob.pdf
    resumo_tendencia_grupob.pdf
    custo_computacional.pdf
  tables/
    parametros_grupo_b.tex
    metricas_grupo_b.tex
    tempo_simulacao.tex
  gaps.md   (atualizado, agora cobre Grupo B também)
```

## 4. Testes

- `chapter_common.load_case_table(group="b")` sobre um manifest de fixture
  com 2-3 casos B (um deles sem L3 em disco), confirmando resolução correta
  do padrão de glob `l2_step_*`/`l3_top_pwm_replay_step_*` e célula `None`
  quando ausente.
- `chapter_common.match_benchmark` com uma lista de entradas sintéticas de
  benchmark e um `target_mtime` de fixture: confirma que a entrada mais
  próxima dentro da tolerância é escolhida, e que `None` retorna quando
  nada cai dentro da tolerância.
- `chapter_tables` gerando `parametros_grupo_b.tex`/`metricas_grupo_b.tex`/
  `tempo_simulacao.tex` a partir das fixtures acima, conferindo célula
  vazia ("—") nos campos sem dado.
- Sem teste automatizado de conteúdo visual para `chapter_figures` (mesma
  decisão do spec anterior) — só "roda sem exceção sobre a fixture e
  produz PDF não vazio" para cada figura nova.

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
