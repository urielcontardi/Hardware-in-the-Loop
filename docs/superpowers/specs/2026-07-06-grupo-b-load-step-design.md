# Grupo B — Degrau de Carga em Regime Permanente (B1-B3)

## Contexto e motivação

A `campaign_03` (S0 + Grupo A, A1-A7) validou partida/aceleração sob carga
estática (carga presente desde t=0, junto com a rampa). Ela não testa o que
o próprio `docs/experimental-validation-plan.md` chama de "o critério mais
direto de qualidade de um simulador HIL": a resposta a uma **mudança** de
carga com o motor já em regime permanente (Grupo B do plano original).

Hoje o torque de carga é um valor único e constante, aplicado do início ao
fim da simulação — não existe suporte a variá-lo no tempo, nem em L2
(`tests/test_tim_solver_vf.py`) nem em L3 (`tests/test_top_hil.py`). Este
documento especifica a extensão mínima necessária para rodar B1-B3 (degrau
único de carga) nos dois níveis, reaproveitando a `campaign_03` e o
orquestrador já existente (`run_campaign_matrix.py`) sem modificá-lo.

Grupo B completo (B1-B5, incluindo perfis periódicos B4/B5) fica fora de
escopo — este documento cobre só B1-B3 (degrau único), por decisão explícita
do usuário.

## Casos (B1-B3)

Cada caso: rampa curta até 60 Hz com a carga pré-degrau já presente, breve
acomodação em regime, degrau de carga, janela de observação do transitório.

| Fase | Janela |
|---|---|
| Rampa 0→60 Hz (com carga pré-degrau) | 0 – 0,5 s |
| Acomodação em regime | 0,5 – 0,6 s |
| **Degrau de carga** (`t_step`) | em t = 0,6 s |
| Transitório + recuperação | 0,6 – 1,0 s |

`vf_base_hz = 60.0`, `vf_acc_hz_s = 120.0` (t_acc=0,5 s), `duration_s = 1.0`,
`initial_theta_rad = 0.7853981633974483` — mesmos valores/convenções já
usados em toda a `campaign_03`.

| Caso | Carga pré (`tload_nm`) | Carga pós (`tload_step_nm`) |
|---|---:|---:|
| B1 | 29.17840623351415 (0,25 Tn) | 87.53521870054244 (0,75 Tn) |
| B2 | 58.3568124670283 (0,50 Tn) | 116.7136249340566 (1,00 Tn) |
| B3 | 87.53521870054244 (0,75 Tn) | 29.17840623351415 (0,25 Tn) |

`Tn = 116.7136249340566` N·m (mesma constante usada no Grupo A).

Cada caso roda em L2 e L3 (6 experimentos: `B1_l2`, `B1_l3`, `B2_l2`,
`B2_l3`, `B3_l2`, `B3_l3`), seguindo o mesmo padrão de nomeação/`output_dir`
do Grupo A.

## Mudanças de código necessárias

### `tests/test_tim_solver_vf.py` (L2)

Duas novas variáveis de ambiente, opcionais (comportamento atual preservado
quando ausentes — nenhum experimento existente do Grupo A/S0 é afetado):

- `HIL_VF_TLOAD_STEP_NM` (`float | None`, default `None` = sem degrau)
- `HIL_VF_TLOAD_STEP_TIME_S` (`float | None`, default `None`)

No laço principal, onde hoje `tload = vf.tload` é lido uma vez por batch
(linha ~262), passa a checar o tempo atual do batch (`step * TS_S`, já
disponível) contra `HIL_VF_TLOAD_STEP_TIME_S` e substituir `tload` pelo
valor pós-degrau quando alcançado — aplicado igual em VHDL
(`dut.torque_load_i.value`, já existente) e no modelo C (`ref.step(va, vb,
vc, tload)`, já recebe `tload` como parâmetro a cada chamada), então não há
assimetria entre os dois lados.

### `tests/test_top_hil.py` (L3)

Mesmas duas variáveis, com prefixo `HIL_L3_`:

- `HIL_L3_TLOAD_STEP_NM`
- `HIL_L3_TLOAD_STEP_TIME_S`

Hoje `await sm.set_torque_load(real_to_fp(tload_nm))` (linha ~467) só é
chamado uma vez, antes do laço principal — a carga nunca muda depois disso
no lado VHDL. Adiciona uma segunda chamada, disparada uma única vez dentro
do laço quando `t_s >= HIL_L3_TLOAD_STEP_TIME_S`, análoga ao padrão já usado
pelo `vf_irq_driver` (uma flag para não disparar de novo). No lado C,
`tload_nm` já é passado a `ref_model.step(va, vb, vc, tload_nm)` a cada
iteração (linha ~559) — como é uma variável Python comum, reatribuí-la no
mesmo ponto do laço já propaga o degrau para o próximo passo do modelo C
sem mudança adicional.

## Métricas novas de transitório

Módulo novo, `verification/cocotb/models/transient_metrics.py`, com uma
função pura reutilizada pelos dois testes:

```python
def compute_transient_metrics(
    t: list[float], speed: list[float], i_alpha: list[float], i_beta: list[float],
    t_step: float, settle_tol_frac: float = 0.05,
) -> dict:
    """Retorna speed_before_step, speed_peak_deviation_rad_s,
    current_peak_a, recovery_time_s (None se nao assentar na janela)."""
```

Chamada duas vezes ao final de cada teste (uma para as séries VHDL, outra
para as séries C, ambas já coletadas em `rows`/`errors_*` durante o laço
existente — nenhuma mudança no laço além da aplicação do degrau em si) e
gravada em `metrics.json` sob `metrics["transient"]["vhdl"]` e
`metrics["transient"]["c"]`, lado a lado para comparação direta na
dissertação. As métricas de regime (NRMSE/MAE) continuam calculadas do
jeito que já são, sobre a série inteira.

## Onde entra na campanha

Estende os artefatos já existentes da `campaign_03` (não cria campanha
nova):

- `verification/results/2026-07-04_campaign_03/manifest.json`: adiciona 3
  casos (`B1`, `B2`, `B3`) com `group: "perturbacao_carga"`.
- `verification/results/2026-07-04_campaign_03/campaign_story.json`:
  adiciona grupo `"B"` (label "Degrau de Carga em Regime") ao `matrix`, com
  os 3 casos e suas colunas (`condicao`, `perturbacao`, `objetivo` — o
  dashboard já sabe renderizar esse formato de tabela, usado para Grupo B no
  layout original).
- `verification/cocotb/campaigns/campaign_03_full_matrix.json`: adiciona os
  6 experimentos (`B1_l2`, `B1_l3`, `B2_l2`, `B2_l3`, `B3_l2`, `B3_l3`),
  `runner: "cocotb"`, `record_interval: 962` (mesmo alvo de ~8000 linhas dos
  demais casos de 1,0 s).
- `run_campaign_matrix.py` **não muda** — `build_l2_env`/`build_l3_env`
  (Task 5/Task 4 da campanha anterior) precisam só repassar os dois campos
  novos (`tload_step_nm`, `tload_step_time_s`) como as env vars
  correspondentes, do mesmo jeito que já repassam `tload_nm` hoje.

## Testes

- `test_transient_metrics.py` (novo): testa `compute_transient_metrics` com
  séries sintéticas (degrau conhecido, pico e tempo de recuperação
  calculáveis à mão) — TDD, sem simulador.
- `test_run_campaign_matrix.py`: estende `test_build_l2_env_vf_mode`/
  equivalente para L3, confirmando que `tload_step_nm`/`tload_step_time_s`
  viram as env vars certas quando presentes no experimento, e que ficam
  ausentes (comportamento atual preservado) quando não presentes.
- Smoke test real: rodar `B1_l2` e `B1_l3` de verdade (o caso mais barato,
  igual ao padrão da campanha anterior) antes de rodar B2/B3, para validar
  que o degrau realmente acontece no VHDL e que as métricas de transitório
  saem com valores plausíveis (ex: `speed_peak_deviation_rad_s` compatível
  com magnitude de degrau de carga observada nos casos formais do Grupo A).

## Fora de escopo

- B4/B5 (perfis periódicos de carga — triangular/senoidal).
- Grupo C (desaceleração, reversão de sentido, mudança de setpoint em
  patamares).
- Qualquer mudança em `run_campaign_matrix.py`, `run_campaign.py` ou
  `prime_c_model.py` além de passar os 2 campos novos pelos env builders.
