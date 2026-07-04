# Campanha 03 — Matriz Completa S0+Grupo A com Orquestrador Paralelo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rodar, numa única bateria orquestrada e paralela, os 22 casos L2/L3 (S0 + Grupo A1-A7) já com os parâmetros de motor corretos e o sincronismo IRQ pico+vale, gerando `metrics.json`/`overlay.html`/README por caso e um dashboard consolidado — sem repetir os pontos de corrida (work library do simulador e `.so` do modelo C) que existem hoje no código quando duas execuções cocotb rodam ao mesmo tempo.

**Architecture:** Um arquivo JSON (`campaign_03_full_matrix.json`) descreve os 22 experimentos; um orquestrador Python novo (`run_campaign_matrix.py`) resolve variáveis de ambiente por caso, isola a work library do simulador por `--build-dir` único, faz um "priming" serial do `.so` do modelo C antes de abrir o pool paralelo, roda os casos com um `ThreadPoolExecutor` limitado, atualiza `manifest.json`/`summary.csv` ao vivo, e ao final regenera o dashboard já existente (`build_campaign_dashboard.py`). Duas correções pontuais em `run_campaign.py` (hoje só usado para L3) fecham os dois pontos de corrida e um bug de variável de ambiente ausente (`HIL_L3_TLOAD_NM`), e o orquestrador novo reaproveita essas funções por import em vez de duplicá-las.

**Tech Stack:** Python 3.12, `uv run`, cocotb + NVC, `pytest`, `concurrent.futures.ThreadPoolExecutor`, `subprocess`.

## Global Constraints

- Todos os comandos Python rodam com `uv run python ...` a partir de `verification/cocotb/`.
- Testes Python: `uv run pytest scripts/tests/ -v` a partir de `verification/cocotb/`.
- Parâmetros de motor corretos (fixos em todo o JSON/env, não usar override manual): `Rs=0.4396`, `Rr=0.2826`, `Ls=0.0031364`, `Lr=0.0063264`, `Lm=0.1099442`, `J=0.4`, `Npp=2.0` (motor "LVP 760V", ~22kW — ver `verification/results/2026-07-04_campaign_02/manifest.json`).
- `Ts = SOLVER_STEP_CYCLES / CLOCK_FREQUENCY = 26 / 200_000_000 = 1.3e-7 s` — nunca alterar esses dois valores na matriz principal (invalida a métrica como já registrado em `docs/experimental-validation-plan.md`).
- Torque nominal `Tn = 116.7136249340566 N·m` (já usado nos scripts A1-A5 existentes) — reutilizar esse valor exato para 1.0 Tn, `0.5 * Tn` para 0.5 Tn, `1.1 * Tn` para 1.1 Tn.
- `initial_theta_rad = math.pi / 4 = 0.7853981633974483` em todos os casos L2/L3 vf/sine (convenção já usada nos scripts existentes).
- `Vdc = 1240.0`, `HIL_PWM_FREQUENCY = 1000`, `HIL_UART_BAUD = 1_000_000` fixos.
- Nunca passar `--test top_hil` para `run.py` — `--test` só é válido com `--top tim_solver` (choices `reference`/`vf`/`sine`); o script `verification/cocotb/campaigns/run_a2_l3_vf_500ms.sh` tem esse bug hoje (nunca rodou com sucesso) — não copiar esse padrão.
- Cada caso cocotb roda com `--build-dir sim_build/<id>` próprio (isolamento de work library) — nunca reusar o `sim_build` default entre execuções paralelas.
- O `.so` do modelo C (`verification/cocotb/sim_build/reference_model/libim_model.so`, caminho hardcoded em `models/im_reference_model.py:171`) deve estar compilado e atualizado *antes* de abrir o pool paralelo (via `prime_c_model.py`) — nunca deixar duas execuções paralelas caírem na primeira compilação ao mesmo tempo.

---

## File Map

| Ação | Caminho | Responsabilidade |
|---|---|---|
| CREATE | `verification/results/2026-07-04_campaign_03/manifest.json` | Estado da campanha: 22 casos, status ao vivo |
| CREATE | `verification/results/2026-07-04_campaign_03/campaign_story.json` | Narrativa para o dashboard (níveis, matriz, roadmap) |
| CREATE | `verification/cocotb/campaigns/campaign_03_full_matrix.json` | Definição dos 22 experimentos (parâmetros, saída) |
| CREATE | `verification/cocotb/scripts/prime_c_model.py` | Compila `libim_model.so` uma vez, serialmente |
| CREATE | `verification/cocotb/scripts/tests/test_prime_c_model.py` | Testes do priming |
| MODIFY | `verification/cocotb/scripts/run_campaign.py` | `--build-dir` isolado, `--test` para L2, fix `HIL_L3_TLOAD_NM` |
| CREATE | `verification/cocotb/scripts/tests/test_run_campaign_env.py` | Testes das mudanças acima |
| CREATE | `verification/cocotb/scripts/run_campaign_matrix.py` | Orquestrador: env L2, manifest, summary.csv, pool paralelo, dashboard |
| CREATE | `verification/cocotb/scripts/tests/test_run_campaign_matrix.py` | Testes do orquestrador (subprocess mockado) |

---

## Task 1: Esqueleto da campanha — manifest e narrativa

**Files:**
- Create: `verification/results/2026-07-04_campaign_03/manifest.json`
- Create: `verification/results/2026-07-04_campaign_03/campaign_story.json`

**Interfaces:**
- Produces: `manifest.json` com `cases: [{id, dir, group, freq_hz, t_acc_s, load_tn, status, l2_results: {}, l3_results: {}}]` — Task 5/6 vão popular `l2_results`/`l3_results` e atualizar `status`.
- Produces: `campaign_story.json` com seção `matrix` cujos `cases[].id` batem exatamente com os `id` de `manifest.json.cases` (S0, A1-A7) — consumido por `build_campaign_dashboard.py` sem modificação.

- [ ] **Step 1: Criar o diretório da campanha**

```bash
mkdir -p /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/results/2026-07-04_campaign_03
```

- [ ] **Step 2: Escrever `manifest.json`**

```json
{
  "campaign_id": "2026-07-04_campaign_03",
  "created_at": "2026-07-04T00:00:00+00:00",
  "supersedes": ["2026-06-29_campaign_01", "2026-07-04_campaign_02"],
  "reason": "Campanha nasce ja com as duas correcoes que invalidaram os resultados anteriores: (1) parametros de motor Rs=0.435/J=0.192 divergentes do motor real, corrigidos para Rs=0.4396/J=0.4 no commit e0e6907; (2) arquitetura sem sincronismo real pico+vale da portadora (V/f atualizado por relogio de software livre), corrigida nos commits f84ff87..60b0401 (plano docs/superpowers/plans/2026-07-04-vf-pwm-irq-sync.md). A campaign_02 foi criada so para a correcao 1 e nunca rodou nada (status not_started); esta campanha substitui as duas.",
  "motor_source_of_truth": {
    "file": "extras/induction-motor-model/psim/1_modelValidation/paramSim.txt",
    "label": "LVP 760V, ~22kW",
    "rs": 0.4396,
    "rr": 0.2826,
    "ls": 0.0031364,
    "lr": 0.0063264,
    "lm": 0.1099442,
    "j": 0.4,
    "npp": 2.0,
    "vrms": 760.0
  },
  "sync_fix": {
    "description": "Referencia V/f do PS passa a ser escrita somente na borda de sample_tick_o (IRQ real, pico+vale da portadora), nao mais por relogio de software livre.",
    "plan": "docs/superpowers/plans/2026-07-04-vf-pwm-irq-sync.md",
    "commits": ["f84ff87", "726f4e8", "b56fc4e", "4a01574", "9e493b3", "60b0401"]
  },
  "defaults": {
    "im_clock_frequency": 200000000,
    "im_solver_step_cycles": 26,
    "hil_pwm_frequency": 1000,
    "vdc_v": 1240.0,
    "torque_nominal_nm": 116.7136249340566
  },
  "status": "not_started",
  "cases": [
    {"id": "S0", "dir": "S0_tacc1s_load000", "group": "sanity", "freq_hz": 60.0, "t_acc_s": 1.0, "load_tn": 0.0, "status": "pending", "l2_results": {}, "l3_results": {}},
    {"id": "A1", "dir": "A1_tacc0p5s_load000", "group": "partida_aceleracao", "freq_hz": 60.0, "t_acc_s": 0.5, "load_tn": 0.0, "status": "pending", "l2_results": {}, "l3_results": {}},
    {"id": "A2", "dir": "A2_tacc0p5s_load100", "group": "partida_aceleracao", "freq_hz": 60.0, "t_acc_s": 0.5, "load_tn": 1.0, "status": "pending", "l2_results": {}, "l3_results": {}},
    {"id": "A3", "dir": "A3_tacc1s_load050", "group": "partida_aceleracao", "freq_hz": 60.0, "t_acc_s": 1.0, "load_tn": 0.5, "status": "pending", "l2_results": {}, "l3_results": {}},
    {"id": "A4", "dir": "A4_tacc2s_load100", "group": "partida_aceleracao", "freq_hz": 60.0, "t_acc_s": 2.0, "load_tn": 1.0, "status": "pending", "l2_results": {}, "l3_results": {}},
    {"id": "A5", "dir": "A5_tacc5s_load000", "group": "partida_aceleracao", "freq_hz": 60.0, "t_acc_s": 5.0, "load_tn": 0.0, "status": "pending", "l2_results": {}, "l3_results": {}},
    {"id": "A6", "dir": "A6_tacc5s_load100", "group": "partida_aceleracao", "freq_hz": 60.0, "t_acc_s": 5.0, "load_tn": 1.0, "status": "pending", "l2_results": {}, "l3_results": {}},
    {"id": "A7", "dir": "A7_tacc2s_load110", "group": "partida_aceleracao", "freq_hz": 60.0, "t_acc_s": 2.0, "load_tn": 1.1, "status": "pending", "l2_results": {}, "l3_results": {}}
  ]
}
```

- [ ] **Step 3: Escrever `campaign_story.json`**

```json
{
  "campaign_label": "Campanha 2026-07-04 — Matriz completa S0+Grupo A",
  "intro": "Esta campanha reexecuta o estudo metodologico (S0) e a matriz de partida/aceleracao (Grupo A, A1-A7) apos duas correcoes que invalidaram todos os resultados anteriores: parametros de motor divergentes (Rs/J) e ausencia de sincronismo real pico+vale entre a referencia V/f e a portadora PWM. Cada resultado aqui usa o motor real (Rs=0.4396, J=0.4) e a IRQ real da portadora.",
  "levels": [
    {
      "id": "L1",
      "title": "PSIM vs C/C++",
      "question": "O modelo C/C++ representa corretamente o motor de inducao usado como referencia offline?",
      "note": "Base teorica/previa, nao reexecutada nesta campanha."
    },
    {
      "id": "L2",
      "title": "C/C++ vs VHDL do Solver",
      "question": "O TIM_Solver.vhd reproduz o modelo C/C++ sem a influencia do modulador PWM nem da telemetria?",
      "note": "Reexecutado para S0 e todos os 7 casos do Grupo A, ja com Rs/J corretos."
    },
    {
      "id": "L3",
      "title": "Top_HIL Simulado vs C/C++",
      "question": "A cadeia integrada (V/f, portadora, NPC, gate driver, solver) simulada em VHDL reproduz o full-stack C/C++ equivalente, agora com a referencia V/f travada na IRQ real (pico+vale)?",
      "note": "Reexecutado para S0 (PWM replay + full-stack mock) e todos os 7 casos do Grupo A (PWM replay)."
    },
    {
      "id": "L4",
      "title": "FPGA Real vs Offline",
      "question": "A placa real, sob o PWM efetivamente gerado, produz as mesmas grandezas do modelo C/C++?",
      "note": "Fora de escopo desta campanha — depende de nova captura .hilbin em hardware."
    }
  ],
  "matrix": {
    "S": {
      "label": "Sanity / Metodologico",
      "description": "Casos usados para validar o fluxo L2/L3 (solver isolado, PWM replay, mock full-stack) com os parametros e sincronismo corretos, antes de reportar a matriz formal.",
      "cases": [
        {"id": "S0", "rampa": "1.0 s", "carga": "0 Tn", "objetivo": "Validar o pipeline L2/L3 completo (solver, PWM replay, mock full-stack) com Rs/J corretos e IRQ real."}
      ]
    },
    "A": {
      "label": "Partida e Aceleracao",
      "description": "Varre rampa de aceleracao (t_acc) e torque de carga durante a partida V/f, cobrindo do vazio a sobrecarga.",
      "cases": [
        {"id": "A1", "rampa": "0.5 s", "carga": "0 Tn", "objetivo": "Corrente de partida e fluxo a vazio."},
        {"id": "A2", "rampa": "0.5 s", "carga": "1.0 Tn", "objetivo": "Pior caso de corrente com rampa rapida."},
        {"id": "A3", "rampa": "1.0 s", "carga": "0.5 Tn", "objetivo": "Caso base do HIL."},
        {"id": "A4", "rampa": "2.0 s", "carga": "1.0 Tn", "objetivo": "Partida suave sob carga nominal."},
        {"id": "A5", "rampa": "5.0 s", "carga": "0 Tn", "objetivo": "Erro acumulado e estabilidade."},
        {"id": "A6", "rampa": "5.0 s", "carga": "1.0 Tn", "objetivo": "Torque com baixa aceleracao."},
        {"id": "A7", "rampa": "2.0 s", "carga": "1.1 Tn", "objetivo": "Sobrecarga curta e margem numerica."}
      ]
    }
  },
  "roadmap": [
    "Rodar a matriz S0+Grupo A completa (este orquestrador).",
    "Regenerar o dashboard e conferir os 22 casos com status 'executado'.",
    "Atualizar o capitulo de resultados da dissertacao com as metricas desta campanha.",
    "Formalizar Grupo B (degrau de carga) e Grupo C (dinamica adicional) em campanha futura."
  ],
  "findings": []
}
```

- [ ] **Step 4: Validar os dois JSON e a consistência de IDs**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
python3 -c "
import json
m = json.load(open('verification/results/2026-07-04_campaign_03/manifest.json'))
s = json.load(open('verification/results/2026-07-04_campaign_03/campaign_story.json'))
manifest_ids = {c['id'] for c in m['cases']}
story_ids = {c['id'] for g in s['matrix'].values() for c in g['cases']}
assert manifest_ids == story_ids, (manifest_ids, story_ids)
assert len(m['cases']) == 8
print('OK:', sorted(manifest_ids))
"
```

Expected: `OK: ['A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7', 'S0']`

- [ ] **Step 5: No commit — these files stay untracked**

`verification/*` in `.gitignore` intentionally excludes `verification/results/`
(campaign output is never versioned — `campaign_01`/`campaign_02` weren't
either). Do not `git add` or `git commit` the two files created in Step 2;
leave them on disk only. Skip straight to Task 2.

---

## Task 2: Matriz de 22 experimentos

**Files:**
- Create: `verification/cocotb/campaigns/campaign_03_full_matrix.json`

**Interfaces:**
- Produces: um dict com `campaign_id`, `case_root`, `defaults`, e `experiments: list[dict]` de 22 entradas. Cada entrada tem `id`, `case_id` (S0/A1.../A7), `result_key`, `level` (`l2`/`l3`), `runner` (`cocotb` ou `fullstack_mock`), `output_dir`. Task 5 consome esses campos exatamente com esses nomes.
- Consumes: nenhum (arquivo de dados puro).

- [ ] **Step 1: Escrever o JSON completo**

```json
{
  "campaign_id": "2026-07-04_campaign_03",
  "case_root": "verification/results/2026-07-04_campaign_03",
  "defaults": {
    "im_clock_frequency": 200000000,
    "im_solver_step_cycles": 26,
    "hil_pwm_frequency": 1000,
    "hil_uart_baud": 1000000,
    "motor": {
      "rs": 0.4396, "rr": 0.2826, "ls": 0.0031364, "lr": 0.0063264,
      "lm": 0.1099442, "j": 0.4, "npp": 2.0
    },
    "vdc": 1240.0,
    "v_peak": 620.0,
    "initial_theta_rad": 0.7853981633974483,
    "warmup_steps": 400
  },
  "experiments": [
    {
      "id": "S0_l2_sine_60hz_realts", "case_id": "S0", "result_key": "sine_60hz_realts",
      "level": "l2", "runner": "cocotb", "test_mode": "sine", "enabled": true,
      "description": "Seno trifasico ideal 60 Hz, 620 V pico de fase, sem carga.",
      "duration_s": 0.20, "record_interval": 192, "sine_freq_hz": 60.0, "tload_nm": 0.0,
      "output_dir": "S0_tacc1s_load000/l2_sine_60hz_realts"
    },
    {
      "id": "S0_l2_vf_50ms_realts", "case_id": "S0", "result_key": "vf_50ms_realts",
      "level": "l2", "runner": "cocotb", "test_mode": "vf", "enabled": true,
      "description": "Rampa V/f 60 Hz/s, janela 0-50 ms, sem carga.",
      "duration_s": 0.05, "record_interval": 48, "vf_base_hz": 60.0, "vf_acc_hz_s": 60.0, "tload_nm": 0.0,
      "output_dir": "S0_tacc1s_load000/l2_vf_50ms_realts"
    },
    {
      "id": "S0_l2_vf_2s_realts", "case_id": "S0", "result_key": "vf_2s_realts",
      "level": "l2", "runner": "cocotb", "test_mode": "vf", "enabled": true,
      "description": "Rampa V/f completa 0-2 s (0-60 Hz em 1 s, regime ate 2 s), sem carga.",
      "duration_s": 2.00, "record_interval": 1923, "vf_base_hz": 60.0, "vf_acc_hz_s": 60.0, "tload_nm": 0.0,
      "output_dir": "S0_tacc1s_load000/l2_vf_2s_realts"
    },
    {
      "id": "S0_l3_pwm_replay_sine_6ms", "case_id": "S0", "result_key": "pwm_replay_sine_6ms",
      "level": "l3", "runner": "cocotb", "top": "top_hil", "testcase": "test_top_hil_pwm_replay_l3", "enabled": true,
      "description": "Top_HIL com referencia externa senoidal 60 Hz, PWM replay, carga nula.",
      "duration_s": 0.006, "record_interval": 6, "ref_mode": "fixed", "ref_freq_hz": 60.0,
      "modulation": 1.0, "tload_nm": 0.0,
      "output_dir": "S0_tacc1s_load000/l3_top_pwm_replay_sine_6ms"
    },
    {
      "id": "S0_l3_pwm_replay_vf_50ms", "case_id": "S0", "result_key": "pwm_replay_vf_50ms",
      "level": "l3", "runner": "cocotb", "top": "top_hil", "testcase": "test_top_hil_pwm_replay_l3", "enabled": true,
      "description": "Top_HIL com rampa V/F 60 Hz/s, janela 0-50 ms, PWM replay, carga nula.",
      "duration_s": 0.05, "record_interval": 48, "ref_mode": "vf", "vf_base_hz": 60.0, "vf_acc_hz_s": 60.0,
      "modulation": 1.0, "tload_nm": 0.0,
      "output_dir": "S0_tacc1s_load000/l3_top_pwm_replay_vf_50ms"
    },
    {
      "id": "S0_l3_pwm_replay_vf_2s", "case_id": "S0", "result_key": "pwm_replay_vf_2s",
      "level": "l3", "runner": "cocotb", "top": "top_hil", "testcase": "test_top_hil_pwm_replay_l3", "enabled": true,
      "description": "Top_HIL com rampa V/F 60 Hz/s, 0-2 s, PWM replay, carga nula.",
      "duration_s": 2.00, "record_interval": 1923, "ref_mode": "vf", "vf_base_hz": 60.0, "vf_acc_hz_s": 60.0,
      "modulation": 1.0, "tload_nm": 0.0,
      "output_dir": "S0_tacc1s_load000/l3_top_pwm_replay_vf_2s"
    },
    {
      "id": "S0_l3_fullstack_vf_50ms", "case_id": "S0", "result_key": "fullstack_mock_vf_50ms",
      "level": "l3", "runner": "fullstack_mock", "enabled": true,
      "description": "Mock full-stack C independente (V/f+portadora+gate driver) sobre o CSV do PWM replay vf_50ms.",
      "depends_on": "S0_l3_pwm_replay_vf_50ms", "warmup_s": 0.001, "record_interval": 1, "skip_s": 0.0,
      "output_dir": "S0_tacc1s_load000/l3_fullstack_mock_vf_50ms"
    },
    {
      "id": "S0_l3_fullstack_vf_2s", "case_id": "S0", "result_key": "fullstack_mock_vf_2s",
      "level": "l3", "runner": "fullstack_mock", "enabled": true,
      "description": "Mock full-stack C independente sobre o CSV do PWM replay vf_2s.",
      "depends_on": "S0_l3_pwm_replay_vf_2s", "warmup_s": 0.001, "record_interval": 1, "skip_s": 0.0,
      "output_dir": "S0_tacc1s_load000/l3_fullstack_mock_vf_2s"
    },
    {
      "id": "A1_l2", "case_id": "A1", "result_key": "vf_500ms_realts",
      "level": "l2", "runner": "cocotb", "test_mode": "vf", "enabled": true,
      "description": "A1: rampa 0.5 s, 0 Tn — corrente de partida e fluxo a vazio.",
      "duration_s": 0.5, "record_interval": 481, "vf_base_hz": 60.0, "vf_acc_hz_s": 120.0, "tload_nm": 0.0,
      "output_dir": "A1_tacc0p5s_load000/l2_vf_500ms_realts"
    },
    {
      "id": "A1_l3", "case_id": "A1", "result_key": "pwm_replay_vf_500ms",
      "level": "l3", "runner": "cocotb", "top": "top_hil", "testcase": "test_top_hil_pwm_replay_l3", "enabled": true,
      "description": "A1 L3: mesma janela do A1 L2, PWM replay.",
      "duration_s": 0.5, "record_interval": 481, "ref_mode": "vf", "vf_base_hz": 60.0, "vf_acc_hz_s": 120.0,
      "modulation": 1.0, "tload_nm": 0.0,
      "output_dir": "A1_tacc0p5s_load000/l3_top_pwm_replay_vf_500ms"
    },
    {
      "id": "A2_l2", "case_id": "A2", "result_key": "vf_500ms_realts",
      "level": "l2", "runner": "cocotb", "test_mode": "vf", "enabled": true,
      "description": "A2: rampa 0.5 s, 1.0 Tn — pior caso de corrente com rampa rapida.",
      "duration_s": 0.5, "record_interval": 481, "vf_base_hz": 60.0, "vf_acc_hz_s": 120.0, "tload_nm": 116.7136249340566,
      "output_dir": "A2_tacc0p5s_load100/l2_vf_500ms_realts"
    },
    {
      "id": "A2_l3", "case_id": "A2", "result_key": "pwm_replay_vf_500ms",
      "level": "l3", "runner": "cocotb", "top": "top_hil", "testcase": "test_top_hil_pwm_replay_l3", "enabled": true,
      "description": "A2 L3: mesma janela do A2 L2, PWM replay.",
      "duration_s": 0.5, "record_interval": 481, "ref_mode": "vf", "vf_base_hz": 60.0, "vf_acc_hz_s": 120.0,
      "modulation": 1.0, "tload_nm": 116.7136249340566,
      "output_dir": "A2_tacc0p5s_load100/l3_top_pwm_replay_vf_500ms"
    },
    {
      "id": "A3_l2", "case_id": "A3", "result_key": "vf_1s_realts",
      "level": "l2", "runner": "cocotb", "test_mode": "vf", "enabled": true,
      "description": "A3: rampa 1.0 s, 0.5 Tn — caso base do HIL.",
      "duration_s": 1.0, "record_interval": 962, "vf_base_hz": 60.0, "vf_acc_hz_s": 60.0, "tload_nm": 58.3568124670283,
      "output_dir": "A3_tacc1s_load050/l2_vf_1s_realts"
    },
    {
      "id": "A3_l3", "case_id": "A3", "result_key": "pwm_replay_vf_1s",
      "level": "l3", "runner": "cocotb", "top": "top_hil", "testcase": "test_top_hil_pwm_replay_l3", "enabled": true,
      "description": "A3 L3: mesma janela do A3 L2, PWM replay.",
      "duration_s": 1.0, "record_interval": 962, "ref_mode": "vf", "vf_base_hz": 60.0, "vf_acc_hz_s": 60.0,
      "modulation": 1.0, "tload_nm": 58.3568124670283,
      "output_dir": "A3_tacc1s_load050/l3_top_pwm_replay_vf_1s"
    },
    {
      "id": "A4_l2", "case_id": "A4", "result_key": "vf_2s_realts",
      "level": "l2", "runner": "cocotb", "test_mode": "vf", "enabled": true,
      "description": "A4: rampa 2.0 s, 1.0 Tn — partida suave sob carga nominal.",
      "duration_s": 2.0, "record_interval": 1923, "vf_base_hz": 60.0, "vf_acc_hz_s": 30.0, "tload_nm": 116.7136249340566,
      "output_dir": "A4_tacc2s_load100/l2_vf_2s_realts"
    },
    {
      "id": "A4_l3", "case_id": "A4", "result_key": "pwm_replay_vf_2s",
      "level": "l3", "runner": "cocotb", "top": "top_hil", "testcase": "test_top_hil_pwm_replay_l3", "enabled": true,
      "description": "A4 L3: mesma janela do A4 L2, PWM replay.",
      "duration_s": 2.0, "record_interval": 1923, "ref_mode": "vf", "vf_base_hz": 60.0, "vf_acc_hz_s": 30.0,
      "modulation": 1.0, "tload_nm": 116.7136249340566,
      "output_dir": "A4_tacc2s_load100/l3_top_pwm_replay_vf_2s"
    },
    {
      "id": "A5_l2", "case_id": "A5", "result_key": "vf_5s_realts",
      "level": "l2", "runner": "cocotb", "test_mode": "vf", "enabled": true,
      "description": "A5: rampa 5.0 s, 0 Tn — erro acumulado e estabilidade.",
      "duration_s": 5.0, "record_interval": 4808, "vf_base_hz": 60.0, "vf_acc_hz_s": 12.0, "tload_nm": 0.0,
      "output_dir": "A5_tacc5s_load000/l2_vf_5s_realts"
    },
    {
      "id": "A5_l3", "case_id": "A5", "result_key": "pwm_replay_vf_5s",
      "level": "l3", "runner": "cocotb", "top": "top_hil", "testcase": "test_top_hil_pwm_replay_l3", "enabled": true,
      "description": "A5 L3: mesma janela do A5 L2, PWM replay.",
      "duration_s": 5.0, "record_interval": 4808, "ref_mode": "vf", "vf_base_hz": 60.0, "vf_acc_hz_s": 12.0,
      "modulation": 1.0, "tload_nm": 0.0,
      "output_dir": "A5_tacc5s_load000/l3_top_pwm_replay_vf_5s"
    },
    {
      "id": "A6_l2", "case_id": "A6", "result_key": "vf_5s_realts",
      "level": "l2", "runner": "cocotb", "test_mode": "vf", "enabled": true,
      "description": "A6: rampa 5.0 s, 1.0 Tn — torque com baixa aceleracao.",
      "duration_s": 5.0, "record_interval": 4808, "vf_base_hz": 60.0, "vf_acc_hz_s": 12.0, "tload_nm": 116.7136249340566,
      "output_dir": "A6_tacc5s_load100/l2_vf_5s_realts"
    },
    {
      "id": "A6_l3", "case_id": "A6", "result_key": "pwm_replay_vf_5s",
      "level": "l3", "runner": "cocotb", "top": "top_hil", "testcase": "test_top_hil_pwm_replay_l3", "enabled": true,
      "description": "A6 L3: mesma janela do A6 L2, PWM replay.",
      "duration_s": 5.0, "record_interval": 4808, "ref_mode": "vf", "vf_base_hz": 60.0, "vf_acc_hz_s": 12.0,
      "modulation": 1.0, "tload_nm": 116.7136249340566,
      "output_dir": "A6_tacc5s_load100/l3_top_pwm_replay_vf_5s"
    },
    {
      "id": "A7_l2", "case_id": "A7", "result_key": "vf_2s_realts",
      "level": "l2", "runner": "cocotb", "test_mode": "vf", "enabled": true,
      "description": "A7: rampa 2.0 s, 1.1 Tn — sobrecarga curta e margem numerica.",
      "duration_s": 2.0, "record_interval": 1923, "vf_base_hz": 60.0, "vf_acc_hz_s": 30.0, "tload_nm": 128.38498742746228,
      "output_dir": "A7_tacc2s_load110/l2_vf_2s_realts"
    },
    {
      "id": "A7_l3", "case_id": "A7", "result_key": "pwm_replay_vf_2s",
      "level": "l3", "runner": "cocotb", "top": "top_hil", "testcase": "test_top_hil_pwm_replay_l3", "enabled": true,
      "description": "A7 L3: mesma janela do A7 L2, PWM replay.",
      "duration_s": 2.0, "record_interval": 1923, "ref_mode": "vf", "vf_base_hz": 60.0, "vf_acc_hz_s": 30.0,
      "modulation": 1.0, "tload_nm": 128.38498742746228,
      "output_dir": "A7_tacc2s_load110/l3_top_pwm_replay_vf_2s"
    }
  ]
}
```

- [ ] **Step 2: Escrever o teste de validação da matriz**

Create `verification/cocotb/scripts/tests/test_campaign_03_matrix.py`:

```python
"""Valida a matriz de 22 experimentos da campaign_03 (arquivo de dados puro,
sem depender de simulador)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MATRIX_PATH = (
    Path(__file__).resolve().parents[1]
    / "campaigns" / "campaign_03_full_matrix.json"
)


def _load():
    return json.loads(MATRIX_PATH.read_text())


def test_matrix_has_22_experiments():
    config = _load()
    assert len(config["experiments"]) == 22


def test_all_experiment_ids_are_unique():
    config = _load()
    ids = [e["id"] for e in config["experiments"]]
    assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"


def test_all_output_dirs_are_unique():
    config = _load()
    dirs = [e["output_dir"] for e in config["experiments"]]
    assert len(dirs) == len(set(dirs)), f"duplicate output_dir: {dirs}"


def test_cocotb_experiments_have_required_fields():
    config = _load()
    for exp in config["experiments"]:
        if exp["runner"] != "cocotb":
            continue
        assert "level" in exp
        assert "duration_s" in exp
        assert "record_interval" in exp
        if exp["level"] == "l2":
            assert exp["test_mode"] in ("vf", "sine")
        if exp["level"] == "l3":
            assert exp["ref_mode"] in ("vf", "fixed")


def test_fullstack_mock_experiments_depend_on_existing_cocotb_case():
    config = _load()
    ids = {e["id"] for e in config["experiments"]}
    for exp in config["experiments"]:
        if exp["runner"] != "fullstack_mock":
            continue
        assert exp["depends_on"] in ids


def test_case_ids_match_manifest():
    config = _load()
    manifest = json.loads(
        (Path(__file__).resolve().parents[4]
         / "results" / "2026-07-04_campaign_03" / "manifest.json").read_text()
    )
    manifest_ids = {c["id"] for c in manifest["cases"]}
    matrix_case_ids = {e["case_id"] for e in config["experiments"]}
    assert matrix_case_ids == manifest_ids
```

- [ ] **Step 3: Rodar os testes**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/test_campaign_03_matrix.py -v
```

Expected: 6 passed.

- [ ] **Step 4: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add verification/cocotb/campaigns/campaign_03_full_matrix.json \
        verification/cocotb/scripts/tests/test_campaign_03_matrix.py
git commit -m "feat(validation): matriz de 22 experimentos da campaign_03 (S0+Grupo A1-A7)"
```

---

## Task 3: Priming do modelo C (`prime_c_model.py`)

**Files:**
- Create: `verification/cocotb/scripts/prime_c_model.py`
- Create: `verification/cocotb/scripts/tests/test_prime_c_model.py`

**Interfaces:**
- Produces: `ensure_c_model_built() -> Path` — retorna o caminho do `.so` já compilado, levanta `RuntimeError` se o backend C não estiver disponível. Task 5 chama essa função uma vez, de forma síncrona, antes de abrir o pool paralelo.

- [ ] **Step 1: Escrever o teste**

```python
"""Unit test for prime_c_model.py — verifica que o .so compila e que a
segunda chamada e idempotente (nao recompila se o .c nao mudou)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import prime_c_model


def test_ensure_c_model_built_creates_so():
    so_path = prime_c_model.ensure_c_model_built()
    assert so_path.exists()
    assert so_path.name == "libim_model.so"


def test_ensure_c_model_built_is_idempotent():
    so_path_1 = prime_c_model.ensure_c_model_built()
    mtime_1 = so_path_1.stat().st_mtime
    so_path_2 = prime_c_model.ensure_c_model_built()
    mtime_2 = so_path_2.stat().st_mtime
    assert mtime_1 == mtime_2, "segunda chamada nao deve recompilar um .so inalterado"
```

- [ ] **Step 2: Rodar o teste — verificar que falha**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/test_prime_c_model.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'prime_c_model'`

- [ ] **Step 3: Escrever `prime_c_model.py`**

```python
#!/usr/bin/env python3
"""prime_c_model.py — compila o modelo C de referencia uma unica vez, antes
de qualquer worker paralelo comecar.

models/im_reference_model.py compila verification/cocotb/sim_build/reference_model/libim_model.so
sob demanda, na primeira vez que InductionMotorReferenceModel(backend="c")
roda, e so recompila se o .so estiver ausente ou mais antigo que IM_Model.c.
Se duas execucoes cocotb paralelas caem nesse caminho de compilacao ao mesmo
tempo, os dois gcc escrevem no mesmo arquivo de saida e um processo pode
tentar dlopen um .so parcialmente escrito pelo outro. Chamar esta funcao uma
vez, serialmente, antes de abrir o pool paralelo garante que o .so ja existe
e esta atualizado antes de qualquer worker toca-lo.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.im_reference_model import InductionMotorReferenceModel


def ensure_c_model_built() -> Path:
    model = InductionMotorReferenceModel(backend="c")
    if model.backend_name != "c":
        raise RuntimeError(
            f"esperava backend C, veio {model.backend_name!r} — "
            "verifique se o gcc esta instalado e se IM_Model.c compila"
        )
    so_path = (
        Path(__file__).resolve().parent.parent
        / "sim_build" / "reference_model" / "libim_model.so"
    )
    if not so_path.exists():
        raise RuntimeError(f"esperava {so_path} existir apos o priming")
    return so_path


if __name__ == "__main__":
    path = ensure_c_model_built()
    print(f"libim_model.so pronto: {path}")
```

- [ ] **Step 4: Rodar o teste — verificar que passa**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/test_prime_c_model.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add verification/cocotb/scripts/prime_c_model.py \
        verification/cocotb/scripts/tests/test_prime_c_model.py
git commit -m "feat(validation): prime_c_model.py evita corrida na compilacao do modelo C"
```

---

## Task 4: Isolar `--build-dir`, suportar `--test` para L2 e corrigir `HIL_L3_TLOAD_NM` em `run_campaign.py`

**Files:**
- Modify: `verification/cocotb/scripts/run_campaign.py`
- Create: `verification/cocotb/scripts/tests/test_run_campaign_env.py`

**Interfaces:**
- Consumes: nenhuma mudança de interface externa para quem já usa `run_campaign.py --config campaigns/l3_pwm_replay.json` (comportamento default preservado).
- Produces: `run_cocotb(exp: dict, env: dict, build_dir: str = "sim_build") -> int` — agora aceita `build_dir` e adiciona `--test <exp["test_mode"]>` quando `exp` tiver a chave `test_mode`. `run_experiment` passa `build_dir=f"sim_build/{exp['id']}"` por padrão. `build_l3_env` agora inclui `HIL_L3_TLOAD_NM`. Task 5 (`run_campaign_matrix.py`) importa `run_cocotb`, `build_l3_env`, `generate_l3_overlay`, `write_readme`, `env_number`, `cocotb_root`, `project_root`, `load_json` diretamente deste módulo.

- [ ] **Step 1: Escrever os testes que falham**

Create `verification/cocotb/scripts/tests/test_run_campaign_env.py`:

```python
"""Testes para as mudancas em run_campaign.py: isolamento de --build-dir,
--test para L2, e a variavel HIL_L3_TLOAD_NM que faltava em build_l3_env."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import run_campaign as rc


def _base_config():
    return {
        "case_root": "verification/results/fake_campaign/CASE",
        "defaults": {
            "im_clock_frequency": 200_000_000,
            "im_solver_step_cycles": 26,
            "hil_pwm_frequency": 1000,
            "motor": {"rs": 0.4396, "rr": 0.2826, "ls": 0.0031364,
                      "lr": 0.0063264, "lm": 0.1099442, "j": 0.4, "npp": 2.0},
            "vdc": 1240.0,
        },
    }


def test_build_l3_env_includes_tload_nm(tmp_path):
    exp = {"id": "x", "duration_s": 0.5, "tload_nm": 116.7136249340566}
    env = rc.build_l3_env(_base_config(), exp, tmp_path)
    assert env["HIL_L3_TLOAD_NM"] == "116.7136249340566"


def test_build_l3_env_tload_nm_defaults_to_zero(tmp_path):
    exp = {"id": "x", "duration_s": 0.5}
    env = rc.build_l3_env(_base_config(), exp, tmp_path)
    assert env["HIL_L3_TLOAD_NM"] == "0.0"


def test_run_cocotb_passes_build_dir_and_test_mode():
    exp = {"top": "tim_solver", "test_mode": "vf", "testcase": "test_tim_solver_vf_stimulus"}
    with patch.object(rc.subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        rc.run_cocotb(exp, {}, build_dir="sim_build/A1_l2")
    args = mock_run.call_args[0][0]
    assert "--build-dir" in args
    assert args[args.index("--build-dir") + 1] == "sim_build/A1_l2"
    assert "--test" in args
    assert args[args.index("--test") + 1] == "vf"


def test_run_cocotb_omits_test_flag_when_no_test_mode():
    exp = {"top": "top_hil", "testcase": "test_top_hil_pwm_replay_l3"}
    with patch.object(rc.subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        rc.run_cocotb(exp, {}, build_dir="sim_build/A1_l3")
    args = mock_run.call_args[0][0]
    assert "--test" not in args


def test_run_cocotb_defaults_build_dir_to_sim_build():
    exp = {"top": "top_hil", "testcase": "test_top_hil_pwm_replay_l3"}
    with patch.object(rc.subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        rc.run_cocotb(exp, {})
    args = mock_run.call_args[0][0]
    assert args[args.index("--build-dir") + 1] == "sim_build"
```

- [ ] **Step 2: Rodar os testes — verificar que falham**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/test_run_campaign_env.py -v 2>&1 | head -30
```

Expected: falhas em `test_build_l3_env_includes_tload_nm` (KeyError) e nos testes de `run_cocotb` (`--build-dir`/`--test` ausentes do comando).

- [ ] **Step 3: Modificar `build_l3_env` — adicionar `HIL_L3_TLOAD_NM`**

Em `verification/cocotb/scripts/run_campaign.py`, dentro de `build_l3_env`, logo após a linha `"HIL_L3_INITIAL_THETA_RAD": env_number(...)`:

```python
# Antes:
        "HIL_L3_INITIAL_THETA_RAD": env_number(exp.get("initial_theta_rad", defaults.get("initial_theta_rad", math.pi / 4))),
        "HIL_L3_OUT_DIR": str(out_dir.resolve()),
    })
    return env

# Depois:
        "HIL_L3_INITIAL_THETA_RAD": env_number(exp.get("initial_theta_rad", defaults.get("initial_theta_rad", math.pi / 4))),
        "HIL_L3_TLOAD_NM": env_number(exp.get("tload_nm", defaults.get("tload_nm", 0.0))),
        "HIL_L3_OUT_DIR": str(out_dir.resolve()),
    })
    return env
```

- [ ] **Step 4: Modificar `run_cocotb` — `build_dir` e `--test`**

```python
# Antes:
def run_cocotb(exp: dict[str, Any], env: dict[str, str]) -> int:
    cmd = [
        "uv", "run", "python", "run.py",
        "--sim", str(exp.get("sim", "nvc")),
        "--top", str(exp.get("top", "top_hil")),
    ]
    testcase = exp.get("testcase")
    if testcase:
        cmd.extend(["-k", str(testcase)])
    print("[campaign] running:", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=cocotb_root(), env=env)
    return proc.returncode

# Depois:
def run_cocotb(exp: dict[str, Any], env: dict[str, str], build_dir: str = "sim_build") -> int:
    cmd = [
        "uv", "run", "python", "run.py",
        "--sim", str(exp.get("sim", "nvc")),
        "--top", str(exp.get("top", "top_hil")),
        "--build-dir", build_dir,
    ]
    test_mode = exp.get("test_mode")
    if test_mode:
        cmd.extend(["--test", str(test_mode)])
    testcase = exp.get("testcase")
    if testcase:
        cmd.extend(["-k", str(testcase)])
    print("[campaign] running:", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=cocotb_root(), env=env)
    return proc.returncode
```

- [ ] **Step 5: Modificar `run_experiment` — isolar `build_dir` por experimento**

```python
# Antes:
    t0 = time.monotonic()
    rc = run_cocotb(exp, env)
    wall_s = time.monotonic() - t0

# Depois:
    build_dir = exp.get("build_dir", f"sim_build/{exp['id']}")
    t0 = time.monotonic()
    rc = run_cocotb(exp, env, build_dir=build_dir)
    wall_s = time.monotonic() - t0
```

- [ ] **Step 6: Rodar os testes — verificar que passam**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/test_run_campaign_env.py -v
```

Expected: 5 passed.

- [ ] **Step 7: Rodar a suíte inteira de `scripts/tests/` para garantir que nada quebrou**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/ -v
```

Expected: todos os testes existentes (`test_hilbin_check.py`, `test_pwm_gap_replay.py`, os novos desta feature) passam.

- [ ] **Step 8: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add verification/cocotb/scripts/run_campaign.py \
        verification/cocotb/scripts/tests/test_run_campaign_env.py
git commit -m "fix(validation): isola --build-dir por experimento, suporta --test em L2, corrige HIL_L3_TLOAD_NM ausente"
```

---

## Task 5: Orquestrador — env L2, manifest e summary.csv

**Files:**
- Create: `verification/cocotb/scripts/run_campaign_matrix.py`
- Create: `verification/cocotb/scripts/tests/test_run_campaign_matrix.py`

**Interfaces:**
- Consumes: `run_cocotb`, `build_l3_env`, `generate_l3_overlay`, `write_readme`, `env_number`, `cocotb_root`, `project_root`, `load_json` de `run_campaign.py` (Task 4); `ensure_c_model_built` de `prime_c_model.py` (Task 3).
- Produces: `build_l2_env(config, exp, out_dir) -> dict[str, str]`; `append_summary_row(summary_csv_path, row: dict) -> None`; `update_manifest_case(manifest, case_id, level, result_key, output_dir, status) -> None`; `save_manifest(path, manifest) -> None`. Task 6 usa essas funções dentro do laço de execução paralela.

- [ ] **Step 1: Escrever os testes que falham**

Create `verification/cocotb/scripts/tests/test_run_campaign_matrix.py`:

```python
"""Testes das funcoes puras do orquestrador: env L2, manifest, summary.csv.
Nao invoca nenhum simulador nem gcc — subprocess.run e sempre mockado."""
import csv
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import run_campaign_matrix as rcm


def _defaults():
    return {
        "im_clock_frequency": 200_000_000,
        "im_solver_step_cycles": 26,
        "motor": {"rs": 0.4396, "rr": 0.2826, "ls": 0.0031364,
                  "lr": 0.0063264, "lm": 0.1099442, "j": 0.4, "npp": 2.0},
        "vdc": 1240.0,
        "v_peak": 620.0,
        "initial_theta_rad": math.pi / 4,
        "warmup_steps": 400,
    }


def test_build_l2_env_vf_mode(tmp_path):
    config = {"defaults": _defaults()}
    exp = {
        "test_mode": "vf", "duration_s": 0.5, "record_interval": 481,
        "vf_base_hz": 60.0, "vf_acc_hz_s": 120.0, "tload_nm": 116.7136249340566,
    }
    env = rcm.build_l2_env(config, exp, tmp_path)
    assert env["IM_RS"] == "0.4396"
    assert env["IM_J"] == "0.4"
    assert env["HIL_VF_DURATION_S"] == "0.5"
    assert env["HIL_VF_ACC_RAMP_HZ_S"] == "120.0"
    assert env["HIL_VF_TLOAD_NM"] == "116.7136249340566"
    assert env["HIL_VF_CSV"] == str((tmp_path / "vf_vhdl_vs_c.csv").resolve())
    assert env["HIL_VF_METRICS"] == str((tmp_path / "metrics.json").resolve())


def test_build_l2_env_sine_mode_computes_steps_from_duration(tmp_path):
    config = {"defaults": _defaults()}
    exp = {"test_mode": "sine", "duration_s": 0.20, "sine_freq_hz": 60.0, "tload_nm": 0.0}
    env = rcm.build_l2_env(config, exp, tmp_path)
    # Ts = 26/200e6 = 1.3e-7 s; steps = round(0.20 / 1.3e-7) = 1538462
    assert env["HIL_SINE_STEPS"] == "1538462"
    assert env["HIL_SINE_FREQ_HZ"] == "60.0"
    assert env["HIL_SINE_CSV"] == str((tmp_path / "sine_vhdl_vs_c.csv").resolve())


def test_build_l2_env_rejects_unknown_test_mode(tmp_path):
    config = {"defaults": _defaults()}
    exp = {"test_mode": "bogus", "duration_s": 0.1}
    try:
        rcm.build_l2_env(config, exp, tmp_path)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_append_summary_row_creates_header(tmp_path):
    csv_path = tmp_path / "summary.csv"
    rcm.append_summary_row(csv_path, {
        "case": "A1", "level": "L2", "status": "generated",
        "path": "A1_tacc0p5s_load000/l2_vf_500ms_realts",
        "duration_s": 0.5, "t_acc_s": 0.5, "tload_nm": 0.0, "csv_rows": 9615,
        "nrmse_i_alpha": 0.0462, "nrmse_i_beta": 0.0471,
        "mae_flux_alpha_wb": 0.0090, "mae_flux_beta_wb": 0.0101,
        "mae_speed_rad_s": 0.369,
        "overlay": "A1_tacc0p5s_load000/l2_vf_500ms_realts/overlay.html",
        "note": "formal Grupo A; sem carga",
    })
    with csv_path.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["case"] == "A1"
    assert rows[0]["level"] == "L2"


def test_append_summary_row_appends_without_duplicating_header(tmp_path):
    csv_path = tmp_path / "summary.csv"
    row = {
        "case": "A1", "level": "L2", "status": "generated", "path": "p",
        "duration_s": 0.5, "t_acc_s": 0.5, "tload_nm": 0.0, "csv_rows": 1,
        "nrmse_i_alpha": 0.01, "nrmse_i_beta": 0.01,
        "mae_flux_alpha_wb": 0.01, "mae_flux_beta_wb": 0.01,
        "mae_speed_rad_s": 0.01, "overlay": "o", "note": "n",
    }
    rcm.append_summary_row(csv_path, row)
    rcm.append_summary_row(csv_path, {**row, "case": "A2"})
    with csv_path.open() as f:
        lines = f.readlines()
    assert lines[0].startswith("case,level,status")
    assert len(lines) == 3


def test_update_manifest_case_marks_partial_then_full():
    manifest = {"cases": [{"id": "A1", "status": "pending", "l2_results": {}, "l3_results": {}}]}
    rcm.update_manifest_case(manifest, "A1", "l2", "vf_500ms_realts",
                              "A1_tacc0p5s_load000/l2_vf_500ms_realts", ok=True)
    case = manifest["cases"][0]
    assert case["l2_results"]["vf_500ms_realts"] == "A1_tacc0p5s_load000/l2_vf_500ms_realts"
    assert "generated" in case["status"]

    rcm.update_manifest_case(manifest, "A1", "l3", "pwm_replay_vf_500ms",
                              "A1_tacc0p5s_load000/l3_top_pwm_replay_vf_500ms", ok=True)
    assert case["l3_results"]["pwm_replay_vf_500ms"] == "A1_tacc0p5s_load000/l3_top_pwm_replay_vf_500ms"
    assert case["status"] == "l2_l3_generated"


def test_update_manifest_case_marks_blocked_on_failure():
    manifest = {"cases": [{"id": "A2", "status": "pending", "l2_results": {}, "l3_results": {}}]}
    rcm.update_manifest_case(manifest, "A2", "l2", "vf_500ms_realts",
                              "A2_tacc0p5s_load100/l2_vf_500ms_realts", ok=False)
    assert manifest["cases"][0]["status"] == "blocked"
```

- [ ] **Step 2: Rodar os testes — verificar que falham**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/test_run_campaign_matrix.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'run_campaign_matrix'`

- [ ] **Step 3: Criar `run_campaign_matrix.py` (parte 1 — env L2, manifest, summary.csv)**

Create `verification/cocotb/scripts/run_campaign_matrix.py`:

```python
#!/usr/bin/env python3
"""Orquestrador da campaign_03 — roda a matriz S0+Grupo A (22 experimentos)
em paralelo, isolando a work library do simulador por experimento e o .so do
modelo C via priming serial (ver prime_c_model.py).

Uso:
    cd verification/cocotb
    uv run python scripts/run_campaign_matrix.py \\
        --config campaigns/campaign_03_full_matrix.json --max-parallel 4

    # Rodar so um caso:
    uv run python scripts/run_campaign_matrix.py --config ... --only A1_l2

    # So imprimir o plano, sem rodar nada:
    uv run python scripts/run_campaign_matrix.py --config ... --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_campaign import (  # noqa: E402
    build_l3_env, cocotb_root, env_number, generate_l3_overlay,
    load_json, project_root, run_cocotb, write_readme,
)
from prime_c_model import ensure_c_model_built  # noqa: E402

SUMMARY_FIELDS = [
    "case", "level", "status", "path", "duration_s", "t_acc_s", "tload_nm",
    "csv_rows", "nrmse_i_alpha", "nrmse_i_beta", "mae_flux_alpha_wb",
    "mae_flux_beta_wb", "mae_speed_rad_s", "overlay", "note",
]


# ── Env builders ──────────────────────────────────────────────────────────────

def build_l2_env(config: dict[str, Any], exp: dict[str, Any], out_dir: Path) -> dict[str, str]:
    """Build the environment for a tim_solver L2 run (test_mode 'vf' or 'sine')."""
    import os

    defaults = config.get("defaults", {})
    motor = defaults.get("motor", {})
    clock = int(defaults.get("im_clock_frequency", 200_000_000))
    step_cycles = int(defaults.get("im_solver_step_cycles", 26))
    ts = step_cycles / clock

    env = os.environ.copy()
    env.update({
        "IM_CLOCK_FREQUENCY": env_number(clock),
        "IM_SOLVER_STEP_CYCLES": env_number(step_cycles),
        "IM_RS": env_number(motor.get("rs", 0.4396)),
        "IM_RR": env_number(motor.get("rr", 0.2826)),
        "IM_LS": env_number(motor.get("ls", 0.0031364)),
        "IM_LR": env_number(motor.get("lr", 0.0063264)),
        "IM_LM": env_number(motor.get("lm", 0.1099442)),
        "IM_J": env_number(motor.get("j", 0.4)),
        "IM_NPP": env_number(motor.get("npp", 2.0)),
    })

    test_mode = exp["test_mode"]
    theta = exp.get("initial_theta_rad", defaults.get("initial_theta_rad", 0.7853981633974483))
    v_peak = exp.get("v_peak", defaults.get("v_peak", 620.0))
    warmup = exp.get("warmup_steps", defaults.get("warmup_steps", 400))

    if test_mode == "vf":
        env.update({
            "HIL_VF_DURATION_S": env_number(exp["duration_s"]),
            "HIL_VF_RECORD_INTERVAL": env_number(exp["record_interval"]),
            "HIL_VF_WARMUP_STEPS": env_number(warmup),
            "HIL_VF_F_NOMINAL_HZ": env_number(exp.get("vf_base_hz", 60.0)),
            "HIL_VF_V_PEAK_NOMINAL": env_number(v_peak),
            "HIL_VF_ACC_RAMP_HZ_S": env_number(exp["vf_acc_hz_s"]),
            "HIL_VF_TLOAD_NM": env_number(exp.get("tload_nm", 0.0)),
            "HIL_VF_INITIAL_THETA_RAD": env_number(theta),
            "HIL_VF_CSV": str((out_dir / "vf_vhdl_vs_c.csv").resolve()),
            "HIL_VF_METRICS": str((out_dir / "metrics.json").resolve()),
        })
    elif test_mode == "sine":
        steps = int(exp["steps"]) if "steps" in exp else round(float(exp["duration_s"]) / ts)
        env.update({
            "HIL_SINE_STEPS": env_number(steps),
            "HIL_SINE_WARMUP_STEPS": env_number(exp.get("warmup_steps", 50)),
            "HIL_SINE_FREQ_HZ": env_number(exp.get("sine_freq_hz", 60.0)),
            "HIL_SINE_V_PEAK": env_number(v_peak),
            "HIL_SINE_INITIAL_THETA_RAD": env_number(theta),
            "HIL_SINE_TLOAD_NM": env_number(exp.get("tload_nm", 0.0)),
            "HIL_SINE_CSV": str((out_dir / "sine_vhdl_vs_c.csv").resolve()),
            "HIL_SINE_METRICS": str((out_dir / "metrics.json").resolve()),
        })
    else:
        raise ValueError(f"unknown L2 test_mode: {test_mode!r}")
    return env


# ── manifest / summary bookkeeping (single-threaded — only main() calls these) ──

def load_manifest(path: Path) -> dict[str, Any]:
    return load_json(path)


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2))


def update_manifest_case(
    manifest: dict[str, Any], case_id: str, level: str, result_key: str,
    output_dir: str, ok: bool,
) -> None:
    case = next(c for c in manifest["cases"] if c["id"] == case_id)
    if not ok:
        case["status"] = "blocked"
        return
    results_key = "l2_results" if level == "l2" else "l3_results"
    case[results_key][result_key] = output_dir
    has_l2 = bool(case.get("l2_results"))
    has_l3 = bool(case.get("l3_results"))
    if has_l2 and has_l3:
        case["status"] = "l2_l3_generated"
    elif has_l2 or has_l3:
        case["status"] = "partial_generated"


def append_summary_row(csv_path: Path, row: dict[str, Any]) -> None:
    is_new = not csv_path.exists()
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in SUMMARY_FIELDS})
```

- [ ] **Step 4: Rodar os testes de env/manifest/summary — verificar que passam**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/test_run_campaign_matrix.py -v
```

Expected: 7 passed (os testes de execução paralela ainda não existem — vêm na Task 6).

- [ ] **Step 5: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add verification/cocotb/scripts/run_campaign_matrix.py \
        verification/cocotb/scripts/tests/test_run_campaign_matrix.py
git commit -m "feat(validation): env builder L2, manifest e summary.csv do orquestrador da campaign_03"
```

---

## Task 6: Execução paralela, retomada e execução sem aborto em cascata

**Files:**
- Modify: `verification/cocotb/scripts/run_campaign_matrix.py`
- Modify: `verification/cocotb/scripts/tests/test_run_campaign_matrix.py`

**Interfaces:**
- Consumes: tudo da Task 5.
- Produces: `run_one_cocotb(config, exp, case_root, build_dir) -> dict` (roda 1 experimento cocotb, retorna `{"id", "ok", "wall_s", "metrics"}`); `run_one_fullstack_mock(config, exp, case_root) -> dict`; `main(argv) -> int`. Task 7 depende de `run_one_cocotb`/`run_one_fullstack_mock` já terem gravado `metrics.json`/CSV no `out_dir` antes de gerar overlay.

- [ ] **Step 1: Escrever os testes que falham (execução mockada)**

Append to `verification/cocotb/scripts/tests/test_run_campaign_matrix.py`:

```python
from unittest.mock import patch


def _fake_manifest(ids):
    return {"cases": [{"id": i, "status": "pending", "l2_results": {}, "l3_results": {}} for i in ids]}


def test_run_one_cocotb_writes_run_log_and_returns_ok(tmp_path):
    case_root = tmp_path / "campaign"
    exp = {
        "id": "A1_l2", "case_id": "A1", "result_key": "vf_500ms_realts",
        "level": "l2", "runner": "cocotb", "test_mode": "vf",
        "duration_s": 0.5, "record_interval": 481, "vf_acc_hz_s": 120.0, "tload_nm": 0.0,
        "output_dir": "A1_tacc0p5s_load000/l2_vf_500ms_realts",
    }
    config = {"defaults": _defaults(), "case_root": str(case_root)}

    def fake_run_cocotb(exp_, env_, build_dir="sim_build"):
        out_dir = case_root / exp_["output_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "metrics.json").write_text(json.dumps({
            "metrics": {"nrmse_i_alpha": 0.01, "nrmse_i_beta": 0.01,
                        "mae_flux_alpha_wb": 0.01, "mae_flux_beta_wb": 0.01,
                        "mae_speed_rad_s": 0.01},
            "duration_s": 0.5, "csv_rows": 100,
        }))
        return 0

    with patch.object(rcm, "run_cocotb", side_effect=fake_run_cocotb):
        result = rcm.run_one_cocotb(config, exp, case_root)
    assert result["ok"] is True
    assert result["id"] == "A1_l2"
    log_path = case_root / exp["output_dir"] / "run.log"
    assert log_path.exists()


def test_run_one_cocotb_reports_failure_without_raising(tmp_path):
    case_root = tmp_path / "campaign"
    exp = {
        "id": "A7_l2", "case_id": "A7", "result_key": "vf_2s_realts",
        "level": "l2", "runner": "cocotb", "test_mode": "vf",
        "duration_s": 2.0, "record_interval": 1923, "vf_acc_hz_s": 30.0, "tload_nm": 128.38,
        "output_dir": "A7_tacc2s_load110/l2_vf_2s_realts",
    }
    config = {"defaults": _defaults(), "case_root": str(case_root)}

    with patch.object(rcm, "run_cocotb", return_value=1):
        result = rcm.run_one_cocotb(config, exp, case_root)
    assert result["ok"] is False
    assert result["id"] == "A7_l2"


def test_main_continues_after_one_case_fails(tmp_path, monkeypatch):
    case_root = tmp_path / "campaign"
    manifest_path = tmp_path / "manifest.json"
    summary_path = tmp_path / "summary.csv"
    config_path = tmp_path / "matrix.json"

    manifest_path.write_text(json.dumps(_fake_manifest(["A1", "A2"])))
    config_path.write_text(json.dumps({
        "case_root": str(case_root),
        "defaults": _defaults(),
        "experiments": [
            {"id": "A1_l2", "case_id": "A1", "result_key": "vf_500ms_realts",
             "level": "l2", "runner": "cocotb", "test_mode": "vf", "enabled": True,
             "duration_s": 0.5, "record_interval": 481, "vf_acc_hz_s": 120.0, "tload_nm": 0.0,
             "output_dir": "A1_tacc0p5s_load000/l2_vf_500ms_realts"},
            {"id": "A2_l2", "case_id": "A2", "result_key": "vf_500ms_realts",
             "level": "l2", "runner": "cocotb", "test_mode": "vf", "enabled": True,
             "duration_s": 0.5, "record_interval": 481, "vf_acc_hz_s": 120.0, "tload_nm": 116.71,
             "output_dir": "A2_tacc0p5s_load100/l2_vf_500ms_realts"},
        ],
    }))

    def fake_run_cocotb(exp_, env_, build_dir="sim_build"):
        out_dir = case_root / exp_["output_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        if exp_["id"] == "A2_l2":
            return 1  # simula falha
        (out_dir / "metrics.json").write_text(json.dumps({
            "metrics": {"nrmse_i_alpha": 0.01, "nrmse_i_beta": 0.01,
                        "mae_flux_alpha_wb": 0.01, "mae_flux_beta_wb": 0.01,
                        "mae_speed_rad_s": 0.01},
            "duration_s": 0.5, "csv_rows": 100,
        }))
        return 0

    monkeypatch.setattr(rcm, "run_cocotb", fake_run_cocotb)
    monkeypatch.setattr(rcm, "generate_l3_overlay", lambda *a, **k: None)
    monkeypatch.setattr(rcm, "write_readme", lambda *a, **k: None)
    monkeypatch.setattr(rcm, "_regenerate_dashboard", lambda *a, **k: None)

    rc = rcm.main([
        "--config", str(config_path), "--manifest", str(manifest_path),
        "--summary", str(summary_path), "--max-parallel", "2",
    ])

    assert rc == 1  # sinaliza que houve falha, mas nao interrompeu o outro caso
    manifest = json.loads(manifest_path.read_text())
    by_id = {c["id"]: c for c in manifest["cases"]}
    assert "generated" in by_id["A1"]["status"]
    assert by_id["A2"]["status"] == "blocked"


def test_main_skips_cases_already_ok_on_resume(tmp_path, monkeypatch):
    case_root = tmp_path / "campaign"
    manifest_path = tmp_path / "manifest.json"
    summary_path = tmp_path / "summary.csv"
    config_path = tmp_path / "matrix.json"

    manifest = _fake_manifest(["A1"])
    manifest["cases"][0]["l2_results"] = {"vf_500ms_realts": "A1_tacc0p5s_load000/l2_vf_500ms_realts"}
    manifest["cases"][0]["status"] = "l2_l3_generated"
    manifest_path.write_text(json.dumps(manifest))
    config_path.write_text(json.dumps({
        "case_root": str(case_root),
        "defaults": _defaults(),
        "experiments": [
            {"id": "A1_l2", "case_id": "A1", "result_key": "vf_500ms_realts",
             "level": "l2", "runner": "cocotb", "test_mode": "vf", "enabled": True,
             "duration_s": 0.5, "record_interval": 481, "vf_acc_hz_s": 120.0, "tload_nm": 0.0,
             "output_dir": "A1_tacc0p5s_load000/l2_vf_500ms_realts"},
        ],
    }))

    calls = []

    def fake_run_cocotb(exp_, env_, build_dir="sim_build"):
        calls.append(exp_["id"])
        return 0

    monkeypatch.setattr(rcm, "run_cocotb", fake_run_cocotb)
    monkeypatch.setattr(rcm, "_regenerate_dashboard", lambda *a, **k: None)

    rcm.main(["--config", str(config_path), "--manifest", str(manifest_path),
              "--summary", str(summary_path), "--max-parallel", "1"])

    assert calls == [], "caso ja marcado como generated no manifest nao deveria rodar de novo"
```

- [ ] **Step 2: Rodar os testes — verificar que falham**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/test_run_campaign_matrix.py -v 2>&1 | tail -20
```

Expected: `AttributeError: module 'run_campaign_matrix' has no attribute 'run_one_cocotb'` (e as demais funções ainda não existem).

- [ ] **Step 3: Adicionar a execução por caso e o `main()` paralelo**

Append to `verification/cocotb/scripts/run_campaign_matrix.py`:

```python
# ── Per-case execution ────────────────────────────────────────────────────────

def _is_case_already_ok(manifest: dict[str, Any], case_id: str, level: str, result_key: str) -> bool:
    case = next((c for c in manifest["cases"] if c["id"] == case_id), None)
    if case is None:
        return False
    results = case.get("l2_results" if level == "l2" else "l3_results", {})
    return result_key in results


def run_one_cocotb(config: dict[str, Any], exp: dict[str, Any], case_root: Path) -> dict[str, Any]:
    out_dir = case_root / exp["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run.log"

    if exp["level"] == "l2":
        env = build_l2_env(config, exp, out_dir)
    else:
        env = build_l3_env(config, exp, out_dir)

    build_dir = f"sim_build/{exp['id']}"
    t0 = time.monotonic()
    with log_path.open("w") as logf:
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = logf
        try:
            rc = run_cocotb(exp, env, build_dir=build_dir)
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
    wall_s = time.monotonic() - t0

    metrics_path = out_dir / "metrics.json"
    metrics = load_json(metrics_path) if metrics_path.exists() else None
    return {"id": exp["id"], "ok": rc == 0, "wall_s": wall_s, "metrics": metrics, "out_dir": out_dir}


def run_one_fullstack_mock(config: dict[str, Any], exp: dict[str, Any], case_root: Path) -> dict[str, Any]:
    dep_id = exp["depends_on"]
    dep_exp = next(e for e in config["_experiments_by_id"].values() if e["id"] == dep_id)
    top_csv = case_root / dep_exp["output_dir"] / "top_pwm_replay_vs_c.csv"
    out_dir = case_root / exp["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run.log"

    cmd = [
        "uv", "run", "python", "scripts/top_fullstack_mock.py", str(top_csv),
        "--out-dir", str(out_dir),
        "--warmup-s", str(exp.get("warmup_s", 0.001)),
        "--record-interval", str(exp.get("record_interval", 1)),
        "--skip-s", str(exp.get("skip_s", 0.0)),
    ]
    t0 = time.monotonic()
    with log_path.open("w") as logf:
        proc = subprocess.run(cmd, cwd=cocotb_root(), stdout=logf, stderr=subprocess.STDOUT)
    wall_s = time.monotonic() - t0

    metrics_path = out_dir / "metrics.json"
    metrics = load_json(metrics_path) if metrics_path.exists() else None
    return {"id": exp["id"], "ok": proc.returncode == 0, "wall_s": wall_s, "metrics": metrics, "out_dir": out_dir}


def _summary_row_from_result(exp: dict[str, Any], result: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    case = next(c for c in manifest["cases"] if c["id"] == exp["case_id"])
    m = (result.get("metrics") or {}).get("metrics", {})
    overlay_rel = f"{exp['output_dir']}/overlay.html"
    return {
        "case": exp["case_id"], "level": exp["level"].upper(),
        "status": "generated" if result["ok"] else "blocked",
        "path": exp["output_dir"],
        "duration_s": exp.get("duration_s", ""), "t_acc_s": case.get("t_acc_s", ""),
        "tload_nm": exp.get("tload_nm", ""),
        "csv_rows": (result.get("metrics") or {}).get("csv_rows", ""),
        "nrmse_i_alpha": m.get("nrmse_i_alpha", ""), "nrmse_i_beta": m.get("nrmse_i_beta", ""),
        "mae_flux_alpha_wb": m.get("mae_flux_alpha_wb", ""), "mae_flux_beta_wb": m.get("mae_flux_beta_wb", ""),
        "mae_speed_rad_s": m.get("mae_speed_rad_s", ""),
        "overlay": overlay_rel, "note": exp.get("description", ""),
    }


def _regenerate_dashboard(campaign_dir: Path) -> None:
    cmd = ["uv", "run", "python", "scripts/build_campaign_dashboard.py", "--campaign", str(campaign_dir)]
    subprocess.run(cmd, cwd=cocotb_root())


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--max-parallel", type=int, default=4)
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    config = load_json(args.config)
    manifest = load_manifest(args.manifest)
    case_root = Path(config["case_root"])
    if not case_root.is_absolute():
        case_root = project_root() / case_root

    experiments = [e for e in config["experiments"] if e.get("enabled", False)]
    config["_experiments_by_id"] = {e["id"]: e for e in experiments}
    if args.only:
        experiments = [e for e in experiments if e["id"] in set(args.only)]

    if not args.force:
        experiments = [
            e for e in experiments
            if not _is_case_already_ok(manifest, e["case_id"], e["level"], e["result_key"])
        ]

    cocotb_exps = [e for e in experiments if e["runner"] == "cocotb"]
    mock_exps = [e for e in experiments if e["runner"] == "fullstack_mock"]

    if args.dry_run:
        for e in cocotb_exps + mock_exps:
            print(f"[dry-run] {e['id']} ({e['runner']}) -> {e['output_dir']}")
        return 0

    ensure_c_model_built()

    any_failed = False
    with ThreadPoolExecutor(max_workers=args.max_parallel) as pool:
        futures = {pool.submit(run_one_cocotb, config, e, case_root): e for e in cocotb_exps}
        for future in as_completed(futures):
            exp = futures[future]
            result = future.result()
            update_manifest_case(manifest, exp["case_id"], exp["level"], exp["result_key"],
                                  exp["output_dir"], ok=result["ok"])
            save_manifest(args.manifest, manifest)
            append_summary_row(args.summary, _summary_row_from_result(exp, result, manifest))
            status = "OK" if result["ok"] else "FAIL"
            print(f"[{status}] {exp['id']} ({result['wall_s']:.1f}s)", flush=True)
            if result["ok"] and exp["level"] == "l3":
                generate_l3_overlay(result["out_dir"], f"{exp['id']} - Top_HIL PWM replay vs C")
                write_readme(result["out_dir"], exp, result["metrics"], result["wall_s"], None)
            if not result["ok"]:
                any_failed = True

    for exp in mock_exps:
        dep = config["_experiments_by_id"][exp["depends_on"]]
        if not _is_case_already_ok(manifest, dep["case_id"], dep["level"], dep["result_key"]):
            print(f"[SKIP] {exp['id']} — dependencia {dep['id']} nao concluida", flush=True)
            any_failed = True
            continue
        result = run_one_fullstack_mock(config, exp, case_root)
        update_manifest_case(manifest, exp["case_id"], exp["level"], exp["result_key"],
                              exp["output_dir"], ok=result["ok"])
        save_manifest(args.manifest, manifest)
        append_summary_row(args.summary, _summary_row_from_result(exp, result, manifest))
        status = "OK" if result["ok"] else "FAIL"
        print(f"[{status}] {exp['id']} ({result['wall_s']:.1f}s)", flush=True)
        if not result["ok"]:
            any_failed = True

    _regenerate_dashboard(case_root)
    return 1 if any_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Rodar os testes — verificar que passam**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/test_run_campaign_matrix.py -v
```

Expected: 11 passed no total (7 da Task 5 + 4 novos).

- [ ] **Step 5: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add verification/cocotb/scripts/run_campaign_matrix.py \
        verification/cocotb/scripts/tests/test_run_campaign_matrix.py
git commit -m "feat(validation): pool paralelo, retomada e nao-aborto-em-cascata no orquestrador da campaign_03"
```

---

## Task 7: Validação com `--dry-run` na matriz real

**Files:**
- No new files — usa os artefatos das Tasks 1, 2 e 6.

**Interfaces:**
- Consumes: `campaign_03_full_matrix.json` (Task 2), `manifest.json` (Task 1), `run_campaign_matrix.main` (Task 6).

- [ ] **Step 1: Rodar o dry-run sobre a matriz completa**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run python scripts/run_campaign_matrix.py \
  --config campaigns/campaign_03_full_matrix.json \
  --manifest ../results/2026-07-04_campaign_03/manifest.json \
  --summary ../results/2026-07-04_campaign_03/campaign_dashboard/summary.csv \
  --dry-run
```

Expected: 22 linhas `[dry-run] <id> (<runner>) -> <output_dir>`, sem nenhuma chamada a `nvc`/`gcc`.

- [ ] **Step 2: Conferir que os 22 IDs batem com a Task 2**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run python scripts/run_campaign_matrix.py \
  --config campaigns/campaign_03_full_matrix.json \
  --manifest ../results/2026-07-04_campaign_03/manifest.json \
  --summary ../results/2026-07-04_campaign_03/campaign_dashboard/summary.csv \
  --dry-run | wc -l
```

Expected: `22`

- [ ] **Step 3: Commit se algum ajuste foi necessário na matriz (não no manifest — este fica untracked)**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git status --short verification/cocotb/campaigns/campaign_03_full_matrix.json
# Se houve mudanca (o manifest.json em verification/results/ NAO entra — fica untracked):
git add verification/cocotb/campaigns/campaign_03_full_matrix.json
git commit -m "fix(validation): ajustes na matriz da campaign_03 apos dry-run"
```

---

## Task 8: Smoke test end-to-end com 2 casos reais rápidos

**Files:**
- No new files — execução real, validação final do pipeline antes da bateria completa de ~24h.

**Interfaces:**
- Consumes: pipeline inteiro (Tasks 1-6).

- [ ] **Step 1: Rodar só os 2 casos mais baratos da matriz (`S0_l3_pwm_replay_sine_6ms`, ~71s de parede, e `S0_l2_vf_50ms_realts`, ~4 min)**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run python scripts/run_campaign_matrix.py \
  --config campaigns/campaign_03_full_matrix.json \
  --manifest ../results/2026-07-04_campaign_03/manifest.json \
  --summary ../results/2026-07-04_campaign_03/campaign_dashboard/summary.csv \
  --only S0_l3_pwm_replay_sine_6ms --only S0_l2_vf_50ms_realts \
  --max-parallel 2
```

Expected: duas linhas `[OK] S0_l3_pwm_replay_sine_6ms (~71s)` e `[OK] S0_l2_vf_50ms_realts (~240s)`; comando termina com código de saída `0`.

- [ ] **Step 2: Conferir os artefatos gerados**

```bash
ls /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/results/2026-07-04_campaign_03/S0_tacc1s_load000/l3_top_pwm_replay_sine_6ms/
ls /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/results/2026-07-04_campaign_03/S0_tacc1s_load000/l2_vf_50ms_realts/
cat /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/results/2026-07-04_campaign_03/manifest.json | python3 -c "import json,sys; m=json.load(sys.stdin); print(next(c for c in m['cases'] if c['id']=='S0'))"
```

Expected: `metrics.json`, `run.log`, `top_pwm_replay_vs_c.csv`/`overlay.html` no diretório L3; `metrics.json`, `run.log`, `vf_vhdl_vs_c.csv` no L2 (overlay do L2 é gerado manualmente com `vf_report.py --compare-only`, ver nota abaixo); o caso `S0` no manifest com `status` contendo `"generated"` e `l2_results`/`l3_results` populados com as duas chaves rodadas.

- [ ] **Step 3: Gerar o overlay do caso L2 (`vf_report.py --compare-only`) e o dashboard final**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run python scripts/vf_report.py --compare-only \
  --vhdl-csv ../results/2026-07-04_campaign_03/S0_tacc1s_load000/l2_vf_50ms_realts/vf_vhdl_vs_c.csv \
  --out ../results/2026-07-04_campaign_03/S0_tacc1s_load000/l2_vf_50ms_realts/overlay.html

uv run python scripts/build_campaign_dashboard.py \
  --campaign ../results/2026-07-04_campaign_03
```

Expected: `Dashboard gerado em .../2026-07-04_campaign_03/index.html`; abrir o arquivo mostra o caso S0 com 2 dos 8 sub-resultados já presentes.

- [ ] **Step 4: No commit — smoke test artifacts stay on disk only**

`verification/results/` is gitignored on purpose (campaign output is never
versioned). Do not `git add`/`git commit` anything under
`verification/results/2026-07-04_campaign_03/`. The artifacts (metrics.json,
CSVs, overlay.html, index.html) remain as local evidence that the pipeline
works; there is nothing to commit for this step.

- [ ] **Step 5: Só depois de tudo acima passar — rodar a matriz completa em background**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
nohup uv run python scripts/run_campaign_matrix.py \
  --config campaigns/campaign_03_full_matrix.json \
  --manifest ../results/2026-07-04_campaign_03/manifest.json \
  --summary ../results/2026-07-04_campaign_03/campaign_dashboard/summary.csv \
  --max-parallel 4 \
  > /tmp/campaign_03_full_run.log 2>&1 &
disown
echo "PID: $!"
```

Esta última etapa não faz parte da validação do plano (roda ~24h) — é o disparo real da campanha, para ser feito manualmente pelo usuário quando o restante estiver revisado e aprovado.

---

## Self-Review

**Spec coverage:**

| Requisito da spec | Task |
|---|---|
| Matriz S0 (oficiais) + Grupo A1-A7, L2+L3 | Task 1 (manifest/story), Task 2 (matriz) |
| Isolamento de `--build-dir` por caso | Task 4 |
| Priming serial do `.so` do modelo C | Task 3, chamado em Task 6 `main()` antes do pool |
| Pool paralelo limitado, configurável | Task 6 (`--max-parallel`) |
| Log isolado por caso | Task 6 (`run.log` em cada `out_dir`) |
| Sem aborto em cascata | Task 6 (`as_completed`, `any_failed` sem `break`) |
| Retomável (`--force`, skip already-ok) | Task 6 (`_is_case_already_ok`) |
| Pós-processamento L2 (overlay) | Task 8 Step 3 (documentado; ver nota de escopo abaixo) |
| Pós-processamento L3 (overlay/readme) | Task 6 `main()`, reaproveita `generate_l3_overlay`/`write_readme` |
| Dashboard final regenerado | Task 6 `_regenerate_dashboard`, chamado ao fim de `main()` |
| Estimativa de custo documentada | Global Constraints + spec (não repetido em código) |

**Nota de escopo — overlay L2 automático:** a Task 6 gera overlay automaticamente apenas para L3 (via `generate_l3_overlay`, já testado e reaproveitado de `run_campaign.py`). Para L2, o `vf_report.py --compare-only` é chamado manualmente no Task 8 Step 3 como parte da validação do smoke test, mas o `main()` do orquestrador **não chama isso automaticamente** dentro do loop paralelo. Isso é uma simplificação deliberada: gerar overlay L2 dentro de cada worker exigiria testar `vf_report.py --compare-only` com fixtures de CSV sintéticas (mais 2-3 testes) só para uma chamada de subprocess que já é exercida manualmente no Task 8. Se o usuário quiser overlay L2 automático por caso, é uma Task 9 pequena e isolada (adicionar uma chamada a `subprocess.run(["uv","run","python","scripts/vf_report.py","--compare-only", ...])` dentro do ramo `if exp["level"] == "l2"` do loop em `main()`, espelhando o ramo `l3` já existente) — não incluída aqui para não inflar o escopo antes de validar o pipeline principal.

**Placeholder scan:** nenhum `TBD`/`TODO` encontrado; todo código é completo e executável.

**Consistência de tipos:** `run_one_cocotb`/`run_one_fullstack_mock` sempre retornam `{"id", "ok", "wall_s", "metrics", "out_dir"}` — usado de forma consistente em `main()` e nos testes da Task 6. `update_manifest_case` e `append_summary_row` usam as mesmas chaves (`case_id`, `level`, `result_key`, `output_dir`) definidas na Task 2 (`campaign_03_full_matrix.json`) e na Task 1 (`manifest.json`).
