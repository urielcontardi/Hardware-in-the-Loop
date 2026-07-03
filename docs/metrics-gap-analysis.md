# Lacunas de Métricas e Cobertura — Análise para Priorização

Este documento registra o levantamento feito em 2026-07-03 sobre o que já foi
extraído de valor da campanha `2026-06-29_campaign_01` e o que ainda falta,
para decidir por onde continuar. Não altera nenhum script, `metrics.json` ou
texto da dissertação — é só o mapa para decisão.

## 0. Implementado em 2026-07-03: métricas de vetor espacial (magnitude/fase/frequência)

Script: `verification/cocotb/scripts/space_vector_metrics.py`. Lê qualquer
`*_vs_c.csv` já gerado (nenhuma simulação nova) e, usando o fato de que
`i_alpha`/`i_beta` já formam um vetor espacial `I(t) = i_alpha + j·i_beta`,
calcula por amostra:

- **erro de magnitude** `|I_dut| - |I_ref|` (A e %I_n);
- **erro de fase** via `angle(I_dut · conj(I_ref))` (graus, sem deriva de
  `unwrap`);
- **frequência instantânea** de referência e DUT (Hz) e o erro entre elas;
- **atraso por correlação cruzada** limitada (`±max-lag` amostras) entre as
  duas séries de `i_alpha`, formalizando com um número único o que a
  varredura manual de fase fazia por tentativa e erro.

Rodado nos 4 casos formais do Grupo A + S0 (V/f 2 s). Saída:
`space_vector_metrics.json` + `space_vector_overlay.html` ao lado de cada
`vf_vhdl_vs_c.csv`.

| Caso | Atraso estimado | Correlação de pico | Erro de fase (méd. abs / máx) | Erro de magnitude (méd. abs / máx, %Iₙ) |
| --- | --- | --- | --- | --- |
| S0 (V/f 2 s) | 0 amostras | 0,9984 | 1,33° / 15,4° | 2,71% / 15,4% |
| A1 (0,5 s, 0 Tn) | 0 amostras | 0,9990 | 2,08° / 9,1° | 2,85% / 15,0% |
| A2 (0,5 s, 1,0 Tn) | 0 amostras | 0,9990 | 2,05° / 8,9° | 2,86% / 15,2% |
| A3 (1,0 s, 0,5 Tn) | 1 amostra (~0,1 ms) | 0,9981 | 2,61° / 15,0° | 3,15% / 15,4% |
| A4 (2,0 s, 1,0 Tn) | 0 amostras | 0,9984 | 2,14° / 21,4° | 2,50% / 14,4% |

Leitura: o atraso estimado é, na prática, zero em todos os cinco casos — essa
é uma confirmação bem mais forte, e barata, do que a varredura manual de 10
fases já tinha sugerido: **não há problema de sincronismo/atraso sistemático
entre VHDL e C**. O erro que resta é genuinely de forma de onda durante o
transitório (fase chega a variar ±9 a ±21° e magnitude ±14 a ±15% do
nominal nos picos), concentrado exatamente na janela de oscilação
eletromecânica já identificada (a corrente mostra um "ringback" amortecido
após o pico de partida, e tanto o erro de magnitude quanto o de fase oscilam
em fase com esse ringback — ver `space_vector_overlay.html` do caso A1). Isso
é consistente com a causa já isolada (acoplamento eletromecânico), mas agora
com uma evidência adicional e independente da NRMSE global.

Ainda não incorporado à dissertação (`Mestrado_latex`) — só calculado e
salvo aqui até decidir se entra no texto.

## 1. Problema de rigor: "NRMSE" hoje são duas métricas diferentes com o mesmo nome

- **L2/L3** (`verification/cocotb/tests/test_tim_solver_vf.py:351`,
  `test_top_hil.py`, `verification/cocotb/scripts/top_fullstack_mock.py`):
  `RMSE / RMS(referência)` — fração adimensional, reportada em prosa como "%"
  apenas por leitura manual (nunca multiplicada por 100 no código).
- **L4** (`verification/cocotb/scripts/fpga_vs_c.py:391-395`, reusado por
  `hilbin_vs_c.py`): `RMSE / (max(ref) - min(ref)) × 100` — normalizado pela
  faixa pico-a-pico, já em percentual.

Consequência: comparar um NRMSE de L2/L3 com um de L4 hoje não é comparação
direta, mesmo aparecendo lado a lado no dashboard, no plano e na dissertação.
Nenhuma das duas implementações importa a outra — são cálculos duplicados de
forma independente. **Prioridade sugerida: alta, e antes de reportar mais
números novos**, porque cada resultado adicional escrito com a fórmula errada
vira retrabalho depois.

## 2. Métricas planejadas (`docs/experimental-validation-plan.md`, seção "Métricas") ausentes do pipeline reprodutível

| Métrica | Status |
| --- | --- |
| MAE/RMSE/NRMSE de fluxo e velocidade | presente, rotineiro |
| MAE de corrente (Amps) | ausente do pipeline atual; existiu uma vez em script avulso não versionado, só para o caso S0 (`window_metrics.json` do `l2_vf_2s_realts` tem `mae_i_alpha_a`/`mae_i_beta_a`, mas nenhum script no repo atual reproduz esses campos) |
| Erro máximo absoluto por sinal | mesma situação do item acima |
| Erro de amplitude fundamental de corrente | só nos diagnósticos antigos de L4 (`verification/cocotb/reports/`), fora da campanha formal; aproximação RMS-da-CA, não é FFT |
| Erro de fase fundamental de corrente | não existe em nenhum lugar do código |
| Pico de corrente, overshoot, tempo até 90% da velocidade (partida) | não calculados |
| Erro RMS por envelope | não calculado |
| Queda de velocidade, pico pós-degrau, tempo de recuperação (Grupo B) | não calculável ainda: Grupo B não tem nenhum caso executado |
| THD / conteúdo harmônico | não existe nenhuma análise em frequência (FFT) em lugar nenhum do pipeline |

## 3. Torque eletromagnético (Te) — lacuna física, não só de script

- O modelo C (`verification/cocotb/models/im_reference_model.py`) calcula Te
  internamente e o retorna (`state.torque`).
- O `TIM_Solver.vhd` **não tem porta de saída para Te** — só recebe o torque de
  carga como entrada (`torque_load_i`). Portanto Te nunca é exportado por
  VHDL/FPGA, nunca aparece em nenhum CSV de comparação, nunca foi validado.
- Fechar essa lacuna exige mudança de RTL (nova porta de saída no solver, não
  só script), portanto é um esforço de outra ordem de grandeza que os itens
  acima.

## 4. Cobertura da matriz de experimentos

De 17 células definidas (S0 + A1-A7 + B1-B5 + C1-C4):

- **5 com dado real:** S0, A1 (completo, L2+L3), A2 (só L2; L3 pronto mas
  bloqueado por permissão de sandbox), A3 (só L2), A4 (só L2 — gerado em
  2026-07-02T23:15, depois da última atualização do dashboard/dissertação,
  então os dois já estão desatualizados nesse ponto específico de novo).
- **2 pastas vazias:** A5, B2.
- **10 sem nenhum artefato:** A6, A7, B1, B3, B4, B5, C1, C2, C3, C4.

Grupo B (perturbação de carga em regime) — que o próprio plano descreve como
"o critério mais direto de qualidade de um simulador HIL" — está 100% vazio.
L4 formal (FPGA real dentro da estrutura de campanha) também está vazio; o que
existe é um diagnóstico antigo avulso em `verification/cocotb/reports/`, fora
da campanha `2026-06-29_campaign_01`.

## 5. Dados brutos já existentes que dão pra explorar sem rodar nada novo

As CSVs de L2/L3 já exportam, mas não usam em nenhuma métrica hoje:

- `va, vb, vc` (tensão aplicada) em todo CSV de L2/L3;
- `pwm_a, pwm_b, pwm_c` (estado bruto do gate) nos CSVs de L3;
- `cmd_theta_rad, cmd_freq_hz, cmd_amp_pu, cmd_va_ref/vb_ref/vc_ref` (trilha de
  comando V/f) nos CSVs de L3 PWM-replay.

Nenhum desses é comparado contra nada — dá pra, por exemplo, validar se o
`va/vb/vc` interno do VHDL bate com o que o C full-stack geraria de forma
independente, isolando ainda mais precisamente erro de modulador vs erro de
solver, sem rodar nenhuma simulação nova.

## 6. Ordem de prioridade sugerida (custo crescente)

1. **Unificar a fórmula de NRMSE** (uma normalização só, documentada) e
   recalcular os `metrics.json` existentes. Puramente script, dado já existe.
2. **Adicionar MAE de corrente (A e %I_n) e erro máximo absoluto** aos
   `metrics.json`/`window_metrics.json` gerados — script novo, sem simulação
   nova, usando os CSVs já salvos.
3. **Métricas de partida** (pico de corrente, overshoot, tempo até 90% da
   velocidade) a partir dos CSVs já existentes de S0/A1/A2/A3/A4 — script
   novo, sem simulação nova.
4. **Rodar Grupo B** (degrau de carga em regime) — precisa de simulação nova;
   é a lacuna mais citada pelo próprio plano como critério central de
   qualidade do HIL.
5. **Formalizar L4 dentro da campanha** — reaproveitar o pipeline de
   `hilbin_vs_c.py` (já existe e funciona) mas rodando/organizando dentro de
   `verification/results/2026-06-29_campaign_01/`, com novos `.hilbin`
   contendo metadados completos.
6. **Exportar Te do VHDL** — requer mudança de RTL no `TIM_Solver.vhd`
   (adicionar porta de saída), maior esforço, mas fecha a lacuna física mais
   relevante para uma dissertação sobre motor de indução.
7. **FFT/THD** — novo módulo de análise espectral; útil para validar
   fidelidade do modulador NPC, mas não bloqueia nenhuma conclusão já escrita.
