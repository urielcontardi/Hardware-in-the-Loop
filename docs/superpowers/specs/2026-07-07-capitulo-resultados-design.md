# Capítulo de Resultados — Conteúdo e Ferramenta de Geração

## Contexto e motivação

A `campaign_03` (2026-07-04, S0 + Grupo A, A1-A7) é a primeira campanha com
parâmetros de motor corretos e sincronismo V/f-PWM real (ver
`verification/results/2026-07-04_campaign_03/manifest.json`). Ela já produz
`metrics.json` por caso/nível e um dashboard automático, mas:

- não existe nenhum texto nem estrutura definida para o capítulo de
  resultados da dissertação;
- os únicos gráficos existentes são HTML interativo (Plotly, tema escuro),
  só para L3, inutilizáveis em LaTeX/Overleaf;
- não existe nenhum script que produza tabelas/figuras padronizadas e
  reprodutíveis a partir dos dados da campanha;
- `docs/experimental-validation-plan.md` já define formalmente os níveis
  L1-L4, os Grupos A/B/C e as métricas — este documento não repete essa
  definição, apenas organiza como ela vira capítulo + ferramenta.

Este spec cobre duas coisas: (1) a estrutura de conteúdo do capítulo de
resultados, e (2) os scripts que geram as tabelas/figuras desse capítulo a
partir dos dados já existentes em `verification/results/`. **Não** cobre
rodar Grupo B, corrigir os casos L2 bloqueados por permissão, capturar dados
L4 reais, ou unificar a fórmula de NRMSE entre L2/L3 e L4 — essas lacunas são
documentadas no capítulo como limitações/trabalho futuro, não resolvidas
aqui.

## Regra de ouro: arquivo em disco é a fonte da verdade

Foi observado que `manifest.json` e `campaign_dashboard/summary.csv` ficam
desatualizados (ex.: A7 aparece como `partial_generated` no manifest, mas
tem `metrics.json` completo de L2 e L3 em disco). Os scripts descritos abaixo
**nunca** confiam no campo `status` do manifest ou do summary.csv para decidir
o que existe — eles sempre checam a existência do arquivo `metrics.json`
esperado no diretório do caso. Um caso sem o arquivo é tratado como ausente
("—" em tabela, case pulado em figura), nunca como erro fatal do script.

## 1. Estrutura do capítulo

1. **Metodologia**
   - Diagrama D2 da sequência S0 → Grupo A → Grupo B (com status por cor:
     feito/verde, pendente/vermelho tracejado).
   - Tabela da matriz de parâmetros do Grupo A (t_acc × carga → A1-A7),
     gerada pelo script a partir do `manifest.json` (não hardcoded).
   - Definição de NRMSE/MAE conforme usadas em L2/L3, com nota de rodapé
     explícita: "L4 usa uma normalização diferente (pico-a-pico); os dois
     não devem ser comparados numericamente até unificar a fórmula."
2. **Resultados L2 vs L3 (Grupo A)**
   - Tabela por caso: NRMSE iα/iβ (%), MAE fluxo α/β (Wb), MAE velocidade
     (rad/s), para L2 e L3 lado a lado. Células sem dado: "—".
   - Duas figuras de forma de onda (i_alpha, i_beta, velocidade — VHDL vs
     referência C — três sub-eixos empilhados): caso **A1** (base, sem
     carga, rampa rápida) e caso **A7** (sobrecarga, pior caso de margem
     numérica). Se A7 não tiver dado no momento da geração, a figura é
     pulada e o gap listado (ver `chapter_common.py` abaixo) — o capítulo
     não trava por isso.
   - Gráfico-resumo 1: barras agrupadas L2 vs L3 (NRMSE iα, iβ) por caso
     A1-A7, só com os casos que têm ambos os níveis.
   - Gráfico-resumo 2: NRMSE/MAE em função de t_acc e de carga (dois
     subplots, ou séries coloridas por carga/t_acc), incluindo os casos
     parciais (só L2).
3. **Achados metodológicos**
   - Texto reaproveitando conclusões já registradas em
     `docs/experimental-validation-plan.md` (erro concentrado no
     acoplamento eletromecânico, não no PWM; L2≈L3 na janela crítica de
     partida) e em `docs/metrics-gap-analysis.md` (atraso ≈ 0 entre VHDL/C
     via `space_vector_metrics.py`). Sem gráfico novo nesta seção — cita os
     números já existentes nesses documentos.
4. **Limitações e trabalho futuro**
   - Lista gerada automaticamente pelo script (`gaps.json`/`gaps.md`, ver
     abaixo): quais células da matriz A1-A7 não têm L2 e/ou L3 no momento
     da geração.
   - Texto fixo (não gerado): Grupo B implementado mas não executado, L4
     pendente de captura em bancada, fórmula de NRMSE inconsistente entre
     L2/L3 e L4.

## 2. Diagrama D2

Novo arquivo `docs/diagrams/06-validation-groups.d2`, seguindo a convenção
já estabelecida em `docs/diagrams/README.md` (fonte `.d2` versionada, saída
`img/06-validation-groups.{svg,png}` via `build.sh`, estilo monocromático
acadêmico, `direction: right`). Conteúdo: três blocos (S0, Grupo A, Grupo B)
em sequência, coloridos por status (verde = executado, vermelho tracejado =
pendente), sem detalhar parâmetros internos (isso fica na tabela).
`docs/diagrams/README.md` ganha uma linha na tabela de figuras.

## 3. Scripts geradores

Local: `verification/cocotb/scripts/`, mesma pasta dos scripts de análise
existentes (`build_campaign_dashboard.py`, `space_vector_metrics.py`).

### `chapter_common.py`

Módulo compartilhado, sem CLI própria. Responsabilidades:

- `load_campaign(campaign_dir: Path) -> CampaignData`: lê `manifest.json`,
  monta uma lista de casos com `id`, `t_acc_s`, `load_tn`, `group`.
- Para cada caso, resolve os caminhos esperados de `l2_.../metrics.json` e
  `l3_.../metrics.json` a partir das chaves `l2_results`/`l3_results` do
  próprio manifest (que já apontam para os subdiretórios reais).
- `load_metrics(path: Path) -> dict | None`: retorna `None` se o arquivo não
  existir (nunca lança exceção por ausência).
- `load_case_table(campaign_dir) -> list[CaseRow]`: uma linha por
  caso×nível, com as métricas relevantes já extraídas (`nrmse_i_alpha`,
  `nrmse_i_beta`, `mae_flux_alpha_wb`, `mae_flux_beta_wb`,
  `mae_speed_rad_s`) ou `None` por campo ausente.
- `write_gaps_report(rows, out_path)`: escreve `gaps.md` listando, por
  caso, quais níveis (L2/L3) estão faltando — insumo direto da seção
  "Limitações".

Segue o padrão já usado em `build_campaign_dashboard.py`
(`REPO_ROOT = Path(__file__).resolve().parents[3]`, descoberta automática da
campanha mais recente em `verification/results/*_campaign_*/` com opção de
override via `--campaign`).

### `chapter_tables.py`

CLI (`argparse`) que usa `chapter_common`. Duas saídas `.tex` (booktabs,
`\input`-áveis direto no Overleaf):

- `parametros_grupo_a.tex`: matriz t_acc (linhas: 0.5/1.0/2.0/5.0 s) × carga
  (colunas: 0/0.5/1.0/1.1 Tn), célula = ID do caso ou vazio. Gerada
  agrupando os `t_acc_s`/`load_tn` únicos encontrados no manifest — se um
  novo caso for adicionado à campanha (ex. mais um ponto de carga), a
  tabela cresce sozinha, não precisa editar o script.
- `metricas_grupo_a.tex`: uma linha por caso, colunas L2/L3 lado a lado
  (NRMSE iα, NRMSE iβ, MAE fluxo, MAE velocidade), célula "—" onde faltar.

Saída em `docs/results-chapter/tables/`.

### `chapter_figures.py`

CLI (`argparse`) que usa `chapter_common`. Matplotlib, backend `Agg`, saída
PDF vetorial, estilo consistente (mesma paleta preto/cinza dos diagramas D2
existentes — ver convenção em `docs/diagrams/README.md`).

- `--case A1 --case A7` (default): para cada caso pedido, se o CSV
  correspondente (`vf_vhdl_vs_c.csv` para L2 ou `top_pwm_replay_vs_c.csv`
  para L3, o que estiver disponível — L3 preferido por incluir o PWM)
  existir, gera `forma_onda_<caso>.pdf` com 3 sub-eixos empilhados
  (i_alpha, i_beta, velocidade), série VHDL (`vhdl_*`) vs referência
  (`ref_*`), eixo x em tempo (`t_us`/1e6 para L2, `t_s` para L3). Caso
  ausente: aviso no stderr, não interrompe a execução dos demais.
- `resumo_l2_vs_l3.pdf`: barras agrupadas (NRMSE iα, iβ) por caso, uma cor
  por nível, só casos com ambos L2 e L3.
- `resumo_tendencia.pdf`: dois subplots. (a) NRMSE/MAE vs t_acc, usando os
  pares com carga=0 (A1 t_acc=0,5s, A5 t_acc=5s). (b) NRMSE/MAE vs carga,
  agrupado por t_acc igual: `t_acc=0,5s` (A1 carga=0, A2 carga=1,0 Tn),
  `t_acc=2,0s` (A4 carga=1,0 Tn, A7 carga=1,1 Tn), `t_acc=5,0s` (A5 carga=0,
  A6 carga=1,0 Tn) — uma linha/série por valor de t_acc. A3 (t_acc=1,0s,
  carga=0,5 Tn) não tem par de mesma rampa e aparece só como ponto de
  referência solto, não como série. Ambos os subplots usam todos os casos
  com pelo menos L2 disponível.

Saída em `docs/results-chapter/figures/`.

## 4. Organização de diretórios (novo, versionado)

```text
docs/results-chapter/
  figures/
    forma_onda_A1.pdf
    forma_onda_A7.pdf
    resumo_l2_vs_l3.pdf
    resumo_tendencia.pdf
  tables/
    parametros_grupo_a.tex
    metricas_grupo_a.tex
  gaps.md
```

Diferente de `verification/results/` (gitignored, dados brutos de
simulação), esta pasta é **versionada**: são os artefatos finais que
alimentam o Overleaf, pequenos (PDF vetorial + `.tex`) e determinísticos a
partir do que já está commitado/gerado.

## 5. Testes

- Teste unitário de `chapter_common.load_case_table` com um manifest de
  fixture (2-3 casos, um deles com L3 ausente) confirmando que a linha
  correspondente vem com `None` nos campos de L3, não lança exceção.
- Teste unitário de `chapter_tables` gerando a tabela de parâmetros a partir
  da mesma fixture, conferindo que células sem caso ficam vazias e células
  com caso mostram o ID certo.
- Sem teste automatizado para `chapter_figures` além de "roda sem lançar
  exceção sobre a fixture e produz um PDF não vazio" — conteúdo visual não
  é verificável por asserção simples.

## Fora de escopo

- Rodar Grupo B, destravar os L2 bloqueados do Grupo A, ou capturar dados
  L4 — ficam documentados como limitação, não resolvidos aqui.
- Unificar a fórmula de NRMSE entre L2/L3 e L4 — vira nota de rodapé no
  capítulo, correção de código é item futuro separado (já rastreado em
  `docs/metrics-gap-analysis.md`).
- Reescrever ou substituir `build_campaign_dashboard.py`/os overlays Plotly
  existentes — continuam servindo para inspeção rápida durante o
  desenvolvimento, não para o texto final.
- Texto final em português pronto para colar no Overleaf — este spec cobre
  estrutura/dados/figuras; a redação corrida fica para depois que os dados
  estiverem confirmados.
