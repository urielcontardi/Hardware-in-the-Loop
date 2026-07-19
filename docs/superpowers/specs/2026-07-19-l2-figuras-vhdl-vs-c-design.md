# Design — Figuras da Validação L2 (Solver VHDL vs. Modelo C)

Data: 2026-07-19
Autor: Uriel Contardi (com assistência)

## 1. Contexto e objetivo

A seção `\section{Validação L2}` (`sec:resultados-l2`) da dissertação
(`Mestrado_latex/Mestrado/chapters/4-Resultados.tex`) precisa ser refeita: ela
está "pobre" (poucas figuras) e, pior, **os números da tabela atual vêm da
campanha errada**.

Objetivo desta fase: construir um **gerador de figuras dirigido por caso** que
produza, no estilo visual já usado nas figuras L1 da tese, um conjunto rico de
plots comparando o solver VHDL (`TIM_Solver`) contra o modelo C de referência,
mais o recálculo das métricas a partir dos CSVs brutos.

Reescrita da prosa e das tabelas do `.tex` fica para uma **fase posterior**
(fora do escopo deste spec).

## 2. Fonte de dados canônica

Confirmado por três fontes independentes no repositório que a campanha correta é
**`verification/results/2026-07-04_campaign_03`** (motor real Rs=0,4396, J=0,4,
IRQ real pico+vale). A `campaign_01` (Rs=0,435, J=0,192) foi **invalidada** e
deve ser ignorada — é dela que vêm os números errados da tabela atual.

- `src/rtl/HIL_AXI_Top.vhd:73` — "Corrigido em 2026-07-04: valores anteriores (Rs=0.435, J=0.192)..."
- `models/im_reference_model.py:46` — "defaults (rs=0.435, j=0.192) diverged from that motor"
- `campaign_03/campaign_story.json` — "correções que invalidaram todos os resultados anteriores"

Os 3 cenários L2 (subcasos de S0, `S0_tacc1s_load000/`):

| Cenário | Pasta | CSV | Regime |
|---|---|---|---|
| Seno 60 Hz | `l2_sine_60hz_realts` | `sine_vhdl_vs_c.csv` | permanente (~3 ciclos, 50 ms, ~384k linhas) |
| V/f 50 ms | `l2_vf_50ms_realts` | `vf_vhdl_vs_c.csv` | transitório curto |
| V/f 2 s | `l2_vf_2s_realts` | `vf_vhdl_vs_c.csv` | transitório longo (8000 linhas) |

### Colunas do CSV
`step, t_us, va, vb, vc, f_ref_hz, vhdl_i_alpha, vhdl_i_beta, vhdl_flux_alpha,
vhdl_flux_beta, vhdl_speed, ref_i_alpha, ref_i_beta, ref_flux_alpha,
ref_flux_beta, ref_speed`

(Coluna de tempo é `t_us` em microssegundos para L2. Correntes de fase são
reconstruídas de α/β por Clarke inversa, assumindo `ia+ib+ic=0`.)

## 3. Métricas (recalculadas do CSV)

Recalculadas diretamente do CSV — não apenas lidas do `metrics.json` — para
(a) poder incluir R² e erro máximo, que não estão no JSON, e (b) garantir
auto-consistência. O NRMSE recalculado é conferido contra o `metrics.json` como
sanity-check (tolerância relativa 1e-3).

Definições:
- `NRMSE = rms(vhdl-ref) / rms(ref)`, onde `rms(x)=sqrt(mean(x^2))`
  (**normalizado pela RMS da referência** — é a definição usada nos testes
  `test_tim_solver_*.py` que geram o `metrics.json` do L2, e é a que o texto do
  Grupo A descreve como "em relação à energia RMS da própria referência").
  Atenção: **não** é a definição por `range` (max−min) usada no `fpga_vs_c.py`
  (L4). Usar a versão RMS para casar com o `metrics.json` existente.
- `R2 = 1 - SS_res/SS_tot`, com `SS_tot` sobre a média da referência.
- `max_abs_err = max(|vhdl-ref|)`, em unidade física.
- `MAE = mean(|vhdl-ref|)`, em unidade física.

Aplicação por sinal:

| Sinal | NRMSE | R² | Erro máx | MAE |
|---|---|---|---|---|
| `i_alpha`, `i_beta` (A) | ✓ | ✓ | ✓ (A) | — |
| `flux_alpha`, `flux_beta` (Wb) | — | ✓ | ✓ (Wb) | ✓ (Wb) |
| `speed` (rad/s, rpm) | — | ✓ | ✓ | ✓ |

Nota de redação (fase posterior): no fluxo/velocidade em rampa o R² vem
altíssimo (0,999…); ancorar sempre junto ao MAE/erro-máximo para não parecer que
o R² mascara erro.

## 4. Estilo visual

Casar com a linguagem das figuras L1 existentes (`image.png`, `image copy.png`,
`image copy 2.png` na raiz do repo):

- Paleta colorida (matplotlib tab10). Fases: azul `ia`, laranja `ib`, verde `ic`.
- **VHDL sólido, C tracejado** (mesma cor por par de sinais) OU, quando ajudar a
  leitura, cores distintas por modelo. Escolha por plot, priorizando clareza.
- Subtítulo por subplot; legenda interna; grid leve.
- Zoom com **regiões sombreadas** (`axvspan`) no painel completo + painéis de
  zoom abaixo (réplica do layout de `image copy 2.png`).
- `font.family: serif` para casar com o corpo do texto LaTeX.
- Saída: **PDF vetorial** (para a tese) **e PNG** (preview rápido de revisão),
  mesmo nome-base.

## 5. Inventário de figuras (por cenário)

Genérico, mas o gerador escolhe o conjunto conforme o tipo de cenário.

### Seno 60 Hz (regime)
- `HIL_L2_Sine_Overlay` — A: correntes trifásicas (ia/ib/ic) + módulo de fluxo +
  velocidade, VHDL vs C.
- `HIL_L2_Sine_Lissajous` — B: trajetória iβ×iα (círculo), VHDL vs C sobrepostos
  (subamostrar p/ tamanho de arquivo).
- `HIL_L2_Sine_PhaseZoom` — C: `ia` completa + regiões sombreadas + painéis de
  zoom (~2 ciclos).

### V/f 50 ms (transitório curto)
- `HIL_L2_VF50ms_Overlay` — A.
- `HIL_L2_VF50ms_Residual` — D: erro ε(t)=VHDL−C das correntes e da velocidade.

### V/f 2 s (transitório longo)
- `HIL_L2_VF2s_Overlay` — A (substitui a figura antiga).
- `HIL_L2_VF2s_Lissajous` — B: espiral crescente.
- `HIL_L2_VF2s_Residual` — D: ε(t) ao longo dos 2 s.
- `HIL_L2_VF2s_WindowNRMSE` — F: barras de NRMSE por janela (0–0,05; 0,05–0,5;
  0,5–1,0; 1,0–1,5; 1,5–2,0 s) (substitui a figura antiga).
- `HIL_L2_VF2s_SteadyZoom` — C: zoom em regime (1,9–2,0 s).

### Resumo
- `HIL_L2_MetricsBar` — barras (log) das métricas por cenário/sinal, no estilo de
  `image copy.png` (R², RMSE/MAE, erro máx), como figura-síntese opcional.

## 6. Arquitetura do script

Novo arquivo: `verification/cocotb/scripts/l2_figures.py`.

- **Dirigido por manifesto**: um dict/lista mapeia cada caso →
  `(pasta, nome_csv, tipo_cenario, conjunto_de_plots, janelas_de_zoom)`.
- **Reuso**: `chapter_common.load_csv_columns` (loader de CSV) e
  `chapter_figures.inverse_clarke` (Clarke inversa) já existem; extrair
  `inverse_clarke` para `chapter_common` se facilitar o reuso.
- Funções isoladas e testáveis:
  - `compute_metrics(data) -> dict` (NRMSE, R², max_abs, MAE por sinal)
  - `plot_overlay`, `plot_lissajous`, `plot_phase_zoom`, `plot_residual`,
    `plot_window_nrmse`, `plot_metrics_bar`
  - `save_fig(fig, out_base)` → grava `.pdf` e `.png`
- **CLI**: `l2_figures.py [--campaign DIR] [--out DIR] [--case ID ...]`
  - `--campaign` default: `2026-07-04_campaign_03` (mais recente compatível).
  - `--out` default: `docs/results-chapter/figures/l2/` (repo).
  - `--case` default: os 3 casos S0 do L2.
- Genérico o suficiente para, depois, apontar para pastas `l2_*_realts` dos
  Grupos A/B (reuso no restante do capítulo).
- Emite também `l2_metrics.json` consolidado (base para a tabela do `.tex` na
  fase posterior — sem digitação manual).

Seguir a skill `dataviz` ao escrever o código dos gráficos (paleta, legibilidade,
consistência claro/escuro não se aplica — é PDF impresso, mas manter contraste).

## 7. Saída

`docs/results-chapter/figures/l2/` no repo HIL: PDFs (vetorial) + PNGs (preview)
+ `l2_metrics.json`. Cópia para `Mestrado_latex/Mestrado/figuras/` é passo
manual posterior, após revisão visual pelo usuário.

## 8. Testes

- Teste unitário de `compute_metrics`: NRMSE recalculado bate com `metrics.json`
  dos 3 casos (tolerância relativa 1e-3).
- Teste de fumaça: gerar as figuras dos 3 casos sem exceção; conferir que os
  arquivos PDF/PNG esperados foram criados e não estão vazios.
- (matplotlib `Agg`, sem display.)

## 9. Não-objetivos / fases futuras

- Reescrita da prosa/tabelas do `.tex` (fase posterior).
- Figuras dos Grupos A/B e L3 (o gerador fica preparado, mas não é acionado aqui).
- Validação L4 / hardware real.
