# Explorador Interativo de Resultados HIL

## Contexto e motivação

Os dados gerados pelas campanhas de validação (`verification/results/*_campaign_*/`)
já alimentam duas ferramentas de saída **estática**: `chapter_figures.py`/
`chapter_tables.py` (PDFs/`.tex` do capítulo de resultados, Grupo A) e
`build_campaign_dashboard.py` (dashboard HTML por campanha). Nenhuma delas
serve para explorar dado bruto: escolher um caso, dar zoom num trecho
específico do tempo, comparar canais à vontade. Esse é o uso que falta —
navegar pelas séries temporais de todas as campanhas/casos/runs já
capturadas em disco, para decidir quais trechos/figuras valem a pena virar
material formal da dissertação.

Este spec cobre só isso: um app local de exploração interativa. **Não**
substitui `chapter_figures.py`/`chapter_tables.py` (saída final para o
Overleaf) nem `build_campaign_dashboard.py` (dashboard estático) — os três
continuam existindo com propósitos diferentes.

## Escopo

- Fonte de dados: apenas `verification/results/*_campaign_*/` (campanhas
  HIL). Não cobre `verification/cocotb/reports/hilbin*` (capturas de
  bancada) nem nada do repositório `Mestrado_latex`.
- Função: só o viewer de série temporal com zoom (campanha → caso → run →
  canais) mais a tabela de métricas do run selecionado. Sem aba de
  comparação entre casos (isso já existe, de forma estática, em
  `chapter_figures.py::plot_resumo_l2_vs_l3`).
- Uso local, pessoal, sem autenticação/deploy — `streamlit run` na máquina
  do usuário.

## Regra de ouro: disco é a fonte da verdade

Mesma convenção já estabelecida em `chapter_common.py`
(`docs/superpowers/specs/2026-07-07-capitulo-resultados-design.md`): a
lista de casos de uma campanha vem das subpastas de `campaign_dir` em
disco, não do `manifest.json` (confirmado desatualizado — `l2_results`/
`l3_results` vazios para vários casos mesmo com dado presente). A lista de
runs de um caso vem das subpastas do caso — isso também dá suporte
automático a S0, que tem várias pastas L2/L3 por rodada (ao contrário do
Grupo A, que tem no máximo uma por nível), sem tratamento especial.

## Arquitetura

Dois arquivos novos em `verification/cocotb/scripts/`, seguindo o padrão
já usado por `chapter_common.py`/`chapter_tables.py`/`chapter_figures.py`
(`REPO_ROOT = Path(__file__).resolve().parents[3]`):

- **`results_explorer_data.py`** — lógica pura, sem import de `streamlit`,
  testável com `pytest` isoladamente:
  - `list_campaigns() -> list[Path]`: subpastas de `verification/results/`
    que casam com `*campaign*`, ordenadas (a mais recente por último, pelo
    prefixo de data no nome).
  - `list_cases(campaign_dir: Path) -> list[Path]`: subpastas diretas de
    `campaign_dir`, excluindo `campaign_dashboard` e entradas ocultas.
  - `list_runs(case_dir: Path) -> list[Path]`: subpastas diretas do caso.
  - `find_timeseries_csv(run_dir: Path) -> Path | None`: primeiro arquivo
    encontrado, nesta ordem, dentre `vf_vhdl_vs_c.csv`,
    `top_pwm_replay_vs_c.csv`, `sine_vhdl_vs_c.csv`, `ref_vhdl_vs_c.csv`,
    `fullstack_vs_top.csv`. Nenhum encontrado: `None`.
  - `detect_channel_pairs(csv_path: Path) -> list[ChannelPair]`: lê só o
    cabeçalho (`pandas.read_csv(..., nrows=0)` ou `csv.reader` na primeira
    linha). Para cada coluna `vhdl_<suffix>`, procura `ref_<suffix>` (ou,
    se ausente, `c_<suffix>` — caso do `fullstack_vs_top.csv`). Cada par
    encontrado vira um `ChannelPair(suffix, vhdl_col, ref_col)`. Colunas
    `vhdl_*` sem par correspondente são ignoradas (sem crash).
  - `detect_time_column(csv_path: Path) -> tuple[str, float]`: `("t_s",
    1.0)` se a coluna existir, senão `("t_us", 1e-6)`.
  - `load_metrics(run_dir: Path) -> dict | None`: lê `metrics.json`,
    devolve a sub-chave `"metrics"` se existir, senão o dict inteiro,
    senão `None` (arquivo ausente/malformado — nunca lança exceção).

- **`results_explorer_app.py`** — UI Streamlit, importa
  `results_explorer_data`:
  - Sidebar: três `st.selectbox` em cascata (campanha, default a mais
    recente → caso → run), populados pelas funções acima.
  - `st.multiselect` de canais, opções vindas de `detect_channel_pairs`,
    todos selecionados por padrão.
  - Gráfico: `plotly.graph_objects`, um subplot por canal selecionado
    (`make_subplots(rows=N, cols=1, shared_xaxes=True)`), traço de
    referência e traço VHDL por canal usando `Scattergl` (CSVs chegam a
    ~380 mil linhas — `sine_vhdl_vs_c.csv` da S0 — `Scattergl` mantém o
    zoom fluido). Renderizado via `st.plotly_chart`, que já dá zoom por
    arrasto e reset por duplo-clique sem código extra.
  - Leitura do CSV via `pandas.read_csv`, só as colunas necessárias
    (tempo + canais selecionados), cacheada com `st.cache_data` chaveada
    em `(csv_path, mtime)` — trocar de canal não relê o arquivo se o CSV
    já estiver em cache; trocar de run lê o novo arquivo.
  - Tabela de métricas: `st.table`/`st.dataframe` a partir de
    `load_metrics`, abaixo do gráfico.

## Tratamento de erros

Nunca lança exceção visível ao usuário — sempre degrada com mensagem:

- Nenhuma campanha em `verification/results/`: `st.error` e para.
- Caso/run sem subpastas: `st.info("Nada encontrado aqui")`, seletor
  seguinte fica vazio/desabilitado.
- Run sem CSV reconhecido (`find_timeseries_csv` retorna `None`): pula o
  gráfico, mostra só a tabela de métricas (se houver) ou uma nota.
- `metrics.json` ausente ou malformado: pula a tabela, sem exceção.
- Nenhum canal com par `vhdl_*`/`ref_*` (ou `c_*`) detectado no CSV: aviso
  "sem canais reconhecidos neste CSV", sem tentar plotar.

## Dependência nova

`pandas` em `verification/cocotb/pyproject.toml` (via `uv add pandas`) —
necessário para leitura eficiente de CSVs de até ~380 mil linhas; o
`csv.DictReader` usado em `chapter_common.py` é rápido o bastante só para
os CSVs pequenos do Grupo A (milhares de linhas), não para os de S0.
`streamlit` também vira dependência nova.

## Como roda

```bash
cd verification/cocotb
uv run streamlit run scripts/results_explorer_app.py
```

Abre no navegador local (`localhost:8501` por padrão do Streamlit).

## Testes

`pytest` em `results_explorer_data.py`, com fixtures `tmp_path` no mesmo
estilo de `test_chapter_common.py`:

- `list_campaigns`/`list_cases`/`list_runs` sobre uma árvore de diretórios
  fabricada, confirmando que `campaign_dashboard` e entradas ocultas são
  excluídas da lista de casos.
- `find_timeseries_csv` encontrando o candidato certo por prioridade, e
  retornando `None` quando nenhum candidato existe.
- `detect_channel_pairs` sobre um cabeçalho CSV fixture com colunas
  `vhdl_i_alpha`/`ref_i_alpha`/`vhdl_x_sem_par` — confirma que o par
  completo é detectado e a coluna sem par é ignorada; outro teste com
  prefixo `c_` (caso `fullstack_vs_top.csv`).
- `load_metrics` com arquivo ausente devolvendo `None`, e com arquivo
  presente devolvendo a sub-chave `"metrics"`.

Sem teste automatizado para `results_explorer_app.py` (UI Streamlit) —
verificação manual: abrir o app, navegar por pelo menos uma campanha/
caso/run de cada nível (L2, L3) e confirmar que o gráfico renderiza e o
zoom funciona.

## Fora de escopo

- Aba de comparação entre casos (já coberta, de forma estática, por
  `chapter_figures.py`).
- Dados de `verification/cocotb/reports/hilbin*` (capturas de bancada) e
  qualquer coisa do repositório `Mestrado_latex`.
- Autenticação, deploy remoto, multiusuário — uso local e pessoal.
- Editar/gerar novos `metrics.json`/CSVs — o app só lê o que já existe em
  disco.
