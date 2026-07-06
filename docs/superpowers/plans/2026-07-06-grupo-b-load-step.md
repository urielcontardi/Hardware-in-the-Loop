# Grupo B — Degrau de Carga em Regime (B1-B3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar suporte a degrau de carga em regime permanente (Grupo B, casos B1-B3) aos testes L2/L3 já existentes, e rodar os 6 novos experimentos (`B1_l2`, `B1_l3`, `B2_l2`, `B2_l3`, `B3_l2`, `B3_l3`) na `campaign_03` já existente, sem re-rodar nenhum caso já concluído (S0, A1-A7).

**Architecture:** Um módulo novo e puro (`transient_metrics.py`) calcula estatísticas de resposta a degrau (pico de desvio de velocidade, pico de corrente, tempo de recuperação) a partir das séries já coletadas pelos testes existentes. `tests/test_tim_solver_vf.py` (L2) e `tests/test_top_hil.py` (L3) ganham duas variáveis de ambiente opcionais cada, que — só quando presentes — trocam o torque de carga uma única vez no meio da simulação e chamam o módulo novo para gravar métricas de transitório extras em `metrics.json`. `run_campaign_matrix.py`/`run_campaign.py` só precisam repassar 2 campos novos do JSON da matriz para essas env vars. A campanha 03 (manifest, story, matriz) ganha 3 casos e 6 experimentos novos; o orquestrador já pula tudo que já rodou (retomada existente), então basta rodar de novo — só B1-B3 vão executar.

**Tech Stack:** Python 3.12, cocotb, NVC, `pytest`, `uv run`.

## Global Constraints

- `Tn = 116.7136249340566` N·m (mesma constante do Grupo A).
- Valores de carga: B1 `0.25Tn=29.17840623351415 -> 0.75Tn=87.53521870054244`; B2 `0.50Tn=58.3568124670283 -> 1.00Tn=116.7136249340566`; B3 `0.75Tn=87.53521870054244 -> 0.25Tn=29.17840623351415`.
- Timing de cada caso B: `vf_base_hz=60.0`, `vf_acc_hz_s=120.0` (t_acc=0,5s), `duration_s=1.0`, degrau em `t_step=0.6` (0,1s de acomodação após o fim da rampa), janela de observação 0,6-1,0s.
- `Ts = 26/200_000_000 = 1.3e-7 s` — nunca alterado. `record_interval=962` (mesmo alvo de ~8000 linhas do Grupo A para 1,0s de duração).
- `initial_theta_rad = 0.7853981633974483` em todos os casos.
- Nenhuma mudança em `run_campaign_matrix.py`/`run_campaign.py` além de repassar os 2 campos novos (`tload_step_nm`, `tload_step_time_s`) para as env vars correspondentes — sem alterar a lógica de execução paralela/retomada já revisada.
- Casos L2 com carga (histórico da `campaign_03`: A2, A3, A4, A6, A7) já falham um assert de fluxo hardcoded (`mae_flux_alpha < 1e-2`/`1e-3`) do próprio módulo de teste — B1-B3 L2 (todos com carga) provavelmente também vão falhar esse mesmo assert. Isso é esperado, não uma regressão desta feature: `metrics.json` continua sendo salvo antes do assert rodar, e o orquestrador já reporta isso corretamente como `[FAIL]` (dado real preservado). Não "consertar" o assert como parte deste plano.
- L3 (`test_top_hil_pwm_replay_l3`) não tem esse assert de fluxo — espera-se que B1-B3 L3 passem, como todos os `A*_l3` da campanha anterior passaram mesmo com carga.

---

## File Map

| Ação | Caminho | Responsabilidade |
|---|---|---|
| CREATE | `verification/cocotb/models/transient_metrics.py` | Função pura de métricas de degrau (pico, tempo de recuperação) |
| CREATE | `verification/cocotb/scripts/tests/test_transient_metrics.py` (na verdade em `models/tests/`, ver Task 1) | Testes do módulo acima |
| MODIFY | `verification/cocotb/tests/test_tim_solver_vf.py` | Suporte a degrau de carga (L2) + métricas de transitório |
| MODIFY | `verification/cocotb/tests/test_top_hil.py` | Suporte a degrau de carga (L3) + métricas de transitório |
| MODIFY | `verification/cocotb/scripts/run_campaign_matrix.py` | `build_l2_env` repassa `tload_step_nm`/`tload_step_time_s` |
| MODIFY | `verification/cocotb/scripts/run_campaign.py` | `build_l3_env` repassa os mesmos 2 campos (prefixo `HIL_L3_`) |
| MODIFY | `verification/results/2026-07-04_campaign_03/manifest.json` | +3 casos (B1, B2, B3) |
| MODIFY | `verification/results/2026-07-04_campaign_03/campaign_story.json` | +grupo "B" na matriz |
| MODIFY | `verification/cocotb/campaigns/campaign_03_full_matrix.json` | +6 experimentos |
| MODIFY | `verification/cocotb/scripts/tests/test_campaign_03_matrix.py` | Ajusta contagem para 28 experimentos, novos casos |

---

## Task 1: `transient_metrics.py` — métricas puras de resposta a degrau

**Files:**
- Create: `verification/cocotb/models/transient_metrics.py`
- Create: `verification/cocotb/models/tests/__init__.py` (se `models/tests/` ainda não existir como pacote)
- Create: `verification/cocotb/models/tests/test_transient_metrics.py`

**Interfaces:**
- Produces: `compute_transient_metrics(t: list[float], speed: list[float], i_alpha: list[float], i_beta: list[float], t_step: float, settle_tol_frac: float = 0.05) -> dict` com chaves `speed_before_step_rad_s`, `speed_peak_deviation_rad_s`, `current_peak_a`, `recovery_time_s` (`float | None`). Tasks 2 e 3 importam essa função diretamente.

- [ ] **Step 1: Verificar/criar `models/tests/__init__.py`**

```bash
ls /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb/models/tests/ 2>&1 || \
  mkdir -p /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb/models/tests/
touch /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb/models/tests/__init__.py
```

- [ ] **Step 2: Escrever os testes que falham**

Create `verification/cocotb/models/tests/test_transient_metrics.py`:

```python
"""Testes de compute_transient_metrics — funcao pura, sem simulador."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest
from models.transient_metrics import compute_transient_metrics


def test_returns_zero_when_no_step_in_window():
    t = [0.0, 0.1, 0.2]
    speed = [50.0, 50.0, 50.0]
    i_alpha = [0.0, 0.0, 0.0]
    i_beta = [0.0, 0.0, 0.0]
    result = compute_transient_metrics(t, speed, i_alpha, i_beta, t_step=1.0)
    assert result["speed_before_step_rad_s"] == 50.0
    assert result["speed_peak_deviation_rad_s"] == 0.0
    assert result["current_peak_a"] == 0.0
    assert result["recovery_time_s"] is None


def test_detects_peak_deviation_current_peak_and_recovery_time():
    t = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    speed = [100.0] * 6 + [70.0, 85.0, 95.0, 99.0, 100.0]
    i_alpha = [0.0] * 6 + [50.0, 30.0, 10.0, 2.0, 0.0]
    i_beta = [0.0] * 11
    result = compute_transient_metrics(t, speed, i_alpha, i_beta, t_step=0.6)
    assert result["speed_before_step_rad_s"] == 100.0
    assert result["speed_peak_deviation_rad_s"] == pytest.approx(30.0)
    assert result["current_peak_a"] == pytest.approx(50.0)
    assert result["recovery_time_s"] == pytest.approx(0.2, abs=1e-9)


def test_recovery_time_none_when_it_never_settles():
    t = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    speed = [100.0] * 6 + [70.0, 72.0, 10.0]
    i_alpha = [0.0] * 9
    i_beta = [0.0] * 9
    result = compute_transient_metrics(t, speed, i_alpha, i_beta, t_step=0.6)
    assert result["speed_peak_deviation_rad_s"] == pytest.approx(90.0)
    assert result["recovery_time_s"] is None
```

- [ ] **Step 3: Rodar os testes — verificar que falham**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest models/tests/test_transient_metrics.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'models.transient_metrics'` (ou `ImportError`).

- [ ] **Step 4: Escrever `models/transient_metrics.py`**

```python
"""Metricas de resposta a degrau de carga (Grupo B).

Calculadas a partir da mesma serie temporal ja coletada para o CSV/NRMSE de
cada teste L2/L3 -- nao precisa de captura de alta resolucao separada, o
record_interval ja existente (~125us de passo para os casos B1-B3) e
suficiente para capturar a dinamica eletromecanica do motor.
"""
from __future__ import annotations

import math


def compute_transient_metrics(
    t: list[float],
    speed: list[float],
    i_alpha: list[float],
    i_beta: list[float],
    t_step: float,
    settle_tol_frac: float = 0.05,
) -> dict:
    """Estatisticas de resposta a degrau para a janela t >= t_step.

    Retorna:
        speed_before_step_rad_s: velocidade na ultima amostra antes de t_step.
        speed_peak_deviation_rad_s: maior |speed(t) - speed_before_step| para t >= t_step.
        current_peak_a: maior sqrt(i_alpha^2 + i_beta^2) para t >= t_step.
        recovery_time_s: segundos desde t_step ate a velocidade permanecer
            dentro de settle_tol_frac do seu valor final (ultima amostra) ate
            o fim da janela; None se nunca assentar (exige pelo menos 2
            amostras restantes para aceitar o assentamento, evitando o caso
            trivial de "a ultima amostra sempre bate com ela mesma").
    """
    idx_before = None
    for i, ti in enumerate(t):
        if ti < t_step:
            idx_before = i
        else:
            break
    speed_before = speed[idx_before] if idx_before is not None else speed[0]

    post_idx = [i for i, ti in enumerate(t) if ti >= t_step]
    if not post_idx:
        return {
            "speed_before_step_rad_s": speed_before,
            "speed_peak_deviation_rad_s": 0.0,
            "current_peak_a": 0.0,
            "recovery_time_s": None,
        }

    speed_peak_deviation = max(abs(speed[i] - speed_before) for i in post_idx)
    current_peak = max(math.hypot(i_alpha[i], i_beta[i]) for i in post_idx)

    speed_final = speed[post_idx[-1]]
    tol = abs(speed_final) * settle_tol_frac
    recovery_time = None
    for j in range(len(post_idx)):
        remaining = post_idx[j:]
        if len(remaining) < 2:
            break
        if all(abs(speed[k] - speed_final) <= tol for k in remaining):
            recovery_time = t[post_idx[j]] - t_step
            break

    return {
        "speed_before_step_rad_s": speed_before,
        "speed_peak_deviation_rad_s": speed_peak_deviation,
        "current_peak_a": current_peak,
        "recovery_time_s": recovery_time,
    }
```

- [ ] **Step 5: Rodar os testes — verificar que passam**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest models/tests/test_transient_metrics.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add verification/cocotb/models/transient_metrics.py \
        verification/cocotb/models/tests/__init__.py \
        verification/cocotb/models/tests/test_transient_metrics.py
git commit -m "feat(validation): compute_transient_metrics para degrau de carga (Grupo B)"
```

---

## Task 2: Degrau de carga em `test_tim_solver_vf.py` (L2)

**Files:**
- Modify: `verification/cocotb/tests/test_tim_solver_vf.py`

**Interfaces:**
- Consumes: `compute_transient_metrics` de `models/transient_metrics.py` (Task 1).
- Produces: quando `HIL_VF_TLOAD_STEP_NM`/`HIL_VF_TLOAD_STEP_TIME_S` estão setadas, `metrics.json` ganha uma chave `"transient": {"vhdl": {...}, "c": {...}}` com o formato de `compute_transient_metrics`. Quando ausentes, comportamento idêntico ao atual (chave `transient` nem aparece).

- [ ] **Step 1: Adicionar as duas env vars opcionais**

Em `verification/cocotb/tests/test_tim_solver_vf.py`, logo após a função `_env_path` (por volta da linha 44), adicionar:

```python
def _env_float_opt(name: str) -> float | None:
    raw = os.environ.get(name)
    return None if raw in (None, "") else float(raw)
```

E, na seção "V/F control parameters" (por volta da linha 70, logo após `TLOAD_NM = _env_float("HIL_VF_TLOAD_NM", 0.0)`):

```python
# Antes:
TLOAD_NM        = _env_float("HIL_VF_TLOAD_NM", 0.0)
INITIAL_THETA   = _env_float("HIL_VF_INITIAL_THETA_RAD", INITIAL_THETA)

# Depois:
TLOAD_NM        = _env_float("HIL_VF_TLOAD_NM", 0.0)
TLOAD_STEP_NM       = _env_float_opt("HIL_VF_TLOAD_STEP_NM")
TLOAD_STEP_TIME_S   = _env_float_opt("HIL_VF_TLOAD_STEP_TIME_S")
INITIAL_THETA   = _env_float("HIL_VF_INITIAL_THETA_RAD", INITIAL_THETA)
```

- [ ] **Step 2: Importar `compute_transient_metrics`**

No bloco de imports (por volta da linha 26, junto aos outros `from models...`):

```python
# Antes:
from models.im_reference_model import IMPhysicalParams, InductionMotorReferenceModel
from models.sim_benchmark import save_benchmark
from models.vf_control import VFControl

# Depois:
from models.im_reference_model import IMPhysicalParams, InductionMotorReferenceModel
from models.sim_benchmark import save_benchmark
from models.transient_metrics import compute_transient_metrics
from models.vf_control import VFControl
```

- [ ] **Step 3: Aplicar o degrau no laço principal**

Localizar (por conteúdo, a linha exata pode variar) o trecho:

```python
# Antes:
        va, vb, vc = vf.step()          # midpoint sample
        tload = vf.tload
        for _ in range(RECORD_INTERVAL - half - 1):

# Depois:
        va, vb, vc = vf.step()          # midpoint sample
        tload = vf.tload
        if (
            TLOAD_STEP_NM is not None
            and TLOAD_STEP_TIME_S is not None
            and step * TS_S >= TLOAD_STEP_TIME_S
        ):
            tload = TLOAD_STEP_NM
        for _ in range(RECORD_INTERVAL - half - 1):
```

- [ ] **Step 4: Calcular e gravar as métricas de transitório**

Localizar o trecho que monta o dict `metrics` (por volta da linha 363, logo antes de `METRICS_PATH.parent.mkdir(...)`):

```python
# Antes:
        "metrics": {
            "nrmse_i_alpha": nrmse_i_alpha,
            "nrmse_i_beta": nrmse_i_beta,
            "mae_flux_alpha_wb": mae_flux_alpha,
            "mae_flux_beta_wb": mae_flux_beta,
            "mae_speed_rad_s": mae_speed,
            "mae_speed_rpm": _rpm(mae_speed),
        },
    }
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))

# Depois:
        "metrics": {
            "nrmse_i_alpha": nrmse_i_alpha,
            "nrmse_i_beta": nrmse_i_beta,
            "mae_flux_alpha_wb": mae_flux_alpha,
            "mae_flux_beta_wb": mae_flux_beta,
            "mae_speed_rad_s": mae_speed,
            "mae_speed_rpm": _rpm(mae_speed),
        },
    }
    if TLOAD_STEP_TIME_S is not None:
        t_arr = [r["t_us"] / 1e6 for r in rows]
        metrics["transient"] = {
            "vhdl": compute_transient_metrics(
                t_arr, [r["vhdl_speed"] for r in rows],
                [r["vhdl_i_alpha"] for r in rows], [r["vhdl_i_beta"] for r in rows],
                TLOAD_STEP_TIME_S,
            ),
            "c": compute_transient_metrics(
                t_arr, [r["ref_speed"] for r in rows],
                [r["ref_i_alpha"] for r in rows], [r["ref_i_beta"] for r in rows],
                TLOAD_STEP_TIME_S,
            ),
        }
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
```

- [ ] **Step 5: Smoke test rápido — confirmar que o comportamento sem degrau não muda**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
IM_CLOCK_FREQUENCY=200000000 IM_SOLVER_STEP_CYCLES=26 IM_RS=0.4396 IM_RR=0.2826 IM_LS=0.0031364 IM_LR=0.0063264 IM_LM=0.1099442 IM_J=0.4 IM_NPP=2.0 \
HIL_VF_DURATION_S=0.05 HIL_VF_RECORD_INTERVAL=48 HIL_VF_F_NOMINAL_HZ=60 HIL_VF_V_PEAK_NOMINAL=620 HIL_VF_ACC_RAMP_HZ_S=60 HIL_VF_TLOAD_NM=0 \
HIL_VF_CSV=/tmp/task2_smoke.csv HIL_VF_METRICS=/tmp/task2_smoke_metrics.json \
uv run python run.py --sim nvc --top tim_solver --test vf -k test_tim_solver_vf_stimulus --build-dir sim_build/task2_smoke_nostep
python3 -c "import json; m=json.load(open('/tmp/task2_smoke_metrics.json')); assert 'transient' not in m; print('OK: sem transient quando step nao configurado')"
```

Expected: teste cocotb passa (sem carga, mesmo caso já validado em S0), e o script Python confirma que `transient` não aparece no `metrics.json` quando as env vars de degrau não são passadas.

- [ ] **Step 6: Smoke test com degrau ativo — confirmar que a chave `transient` aparece e tem valores plausíveis**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
IM_CLOCK_FREQUENCY=200000000 IM_SOLVER_STEP_CYCLES=26 IM_RS=0.4396 IM_RR=0.2826 IM_LS=0.0031364 IM_LR=0.0063264 IM_LM=0.1099442 IM_J=0.4 IM_NPP=2.0 \
HIL_VF_DURATION_S=1.0 HIL_VF_RECORD_INTERVAL=962 HIL_VF_F_NOMINAL_HZ=60 HIL_VF_V_PEAK_NOMINAL=620 HIL_VF_ACC_RAMP_HZ_S=120 \
HIL_VF_TLOAD_NM=29.17840623351415 HIL_VF_TLOAD_STEP_NM=87.53521870054244 HIL_VF_TLOAD_STEP_TIME_S=0.6 \
HIL_VF_CSV=/tmp/task2_smoke_step.csv HIL_VF_METRICS=/tmp/task2_smoke_step_metrics.json \
uv run python run.py --sim nvc --top tim_solver --test vf -k test_tim_solver_vf_stimulus --build-dir sim_build/task2_smoke_step
python3 -c "
import json
m = json.load(open('/tmp/task2_smoke_step_metrics.json'))
t = m['transient']
print(json.dumps(t, indent=2))
assert 'vhdl' in t and 'c' in t
assert t['vhdl']['speed_peak_deviation_rad_s'] >= 0
"
```

Expected: teste cocotb roda (pode falhar o assert de fluxo hardcoded, é esperado para caso com carga — ver Global Constraints); o `metrics.json` tem a chave `transient` com `vhdl`/`c` populados e valores numéricos plausíveis (não `null`/`NaN`).

- [ ] **Step 7: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add verification/cocotb/tests/test_tim_solver_vf.py
git commit -m "feat(validation): suporte a degrau de carga + metricas de transitorio em test_tim_solver_vf.py"
```

---

## Task 3: Degrau de carga em `test_top_hil.py` (L3)

**Files:**
- Modify: `verification/cocotb/tests/test_top_hil.py`

**Interfaces:**
- Consumes: `compute_transient_metrics` de `models/transient_metrics.py` (Task 1).
- Produces: mesmo formato de `metrics["transient"]` da Task 2, mas dentro de `test_top_hil_pwm_replay_l3`, ativado por `HIL_L3_TLOAD_STEP_NM`/`HIL_L3_TLOAD_STEP_TIME_S`.

- [ ] **Step 1: Importar `compute_transient_metrics`**

No topo de `verification/cocotb/tests/test_top_hil.py`, junto aos demais imports do módulo (mesmo padrão de `test_tim_solver_vf.py`):

```python
from models.transient_metrics import compute_transient_metrics
```

- [ ] **Step 2: Ler as duas env vars opcionais dentro de `test_top_hil_pwm_replay_l3`**

Localizar, dentro da função `test_top_hil_pwm_replay_l3` (por volta da linha 450), o trecho:

```python
# Antes:
    tload_nm = env_float("HIL_L3_TLOAD_NM", 0.0)
    out_dir = env_path(

# Depois:
    tload_nm = env_float("HIL_L3_TLOAD_NM", 0.0)

    def env_float_opt(name: str) -> float | None:
        raw = os.environ.get(name)
        return None if raw in (None, "") else float(raw)

    tload_step_nm = env_float_opt("HIL_L3_TLOAD_STEP_NM")
    tload_step_time_s = env_float_opt("HIL_L3_TLOAD_STEP_TIME_S")
    tload_step_applied = False
    out_dir = env_path(
```

- [ ] **Step 3: Aplicar o degrau uma única vez no laço principal**

Localizar o trecho do laço principal (por volta da linha 548):

```python
# Antes:
    for step in range(sample_steps):
        cmd_state = latest_cmd_state
        va = sig_fp(dut.va_motor)

# Depois:
    for step in range(sample_steps):
        cmd_state = latest_cmd_state
        t_s_now = step * params.ts
        if (
            tload_step_nm is not None
            and tload_step_time_s is not None
            and not tload_step_applied
            and t_s_now >= tload_step_time_s
        ):
            tload_nm = tload_step_nm
            await sm.set_torque_load(real_to_fp(tload_nm))
            tload_step_applied = True
        va = sig_fp(dut.va_motor)
```

- [ ] **Step 4: Calcular e gravar as métricas de transitório**

Localizar o trecho que monta o dict `metrics` (por volta da linha 645), logo antes de `metrics_path.write_text(...)`:

```python
# Antes:
        "metrics": {
            "nrmse_i_alpha": math.sqrt(se_ia / max(n_metrics, 1)) / max(math.sqrt(ref2_ia / max(n_metrics, 1)), 1e-9),
            "nrmse_i_beta": math.sqrt(se_ib / max(n_metrics, 1)) / max(math.sqrt(ref2_ib / max(n_metrics, 1)), 1e-9),
            "mae_flux_alpha_wb": sae_fa / max(n_metrics, 1),
            "mae_flux_beta_wb": sae_fb / max(n_metrics, 1),
            "mae_speed_rad_s": sae_wm / max(n_metrics, 1),
        },
        "artifacts": {
            "csv": str(csv_path),
            "metrics": str(metrics_path),
        },
    }
    metrics_path.write_text(json.dumps(metrics, indent=2))

# Depois:
        "metrics": {
            "nrmse_i_alpha": math.sqrt(se_ia / max(n_metrics, 1)) / max(math.sqrt(ref2_ia / max(n_metrics, 1)), 1e-9),
            "nrmse_i_beta": math.sqrt(se_ib / max(n_metrics, 1)) / max(math.sqrt(ref2_ib / max(n_metrics, 1)), 1e-9),
            "mae_flux_alpha_wb": sae_fa / max(n_metrics, 1),
            "mae_flux_beta_wb": sae_fb / max(n_metrics, 1),
            "mae_speed_rad_s": sae_wm / max(n_metrics, 1),
        },
        "artifacts": {
            "csv": str(csv_path),
            "metrics": str(metrics_path),
        },
    }
    if tload_step_time_s is not None:
        t_arr = [r["t_s"] for r in rows]
        metrics["transient"] = {
            "vhdl": compute_transient_metrics(
                t_arr, [r["vhdl_speed"] for r in rows],
                [r["vhdl_i_alpha"] for r in rows], [r["vhdl_i_beta"] for r in rows],
                tload_step_time_s,
            ),
            "c": compute_transient_metrics(
                t_arr, [r["ref_speed"] for r in rows],
                [r["ref_i_alpha"] for r in rows], [r["ref_i_beta"] for r in rows],
                tload_step_time_s,
            ),
        }
    metrics_path.write_text(json.dumps(metrics, indent=2))
```

- [ ] **Step 5: Smoke test sem degrau — confirmar que nada muda**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
IM_CLOCK_FREQUENCY=200000000 IM_SOLVER_STEP_CYCLES=26 IM_RS=0.4396 IM_RR=0.2826 IM_LS=0.0031364 IM_LR=0.0063264 IM_LM=0.1099442 IM_J=0.4 IM_NPP=2.0 \
HIL_PWM_FREQUENCY=1000 HIL_L3_STEPS=384615 HIL_L3_WARMUP_STEPS=400 HIL_L3_RECORD_INTERVAL=48 HIL_L3_VDC=1240 HIL_L3_MODULATION=0.70 \
HIL_L3_REF_MODE=fixed HIL_L3_REF_FREQ_HZ=60 \
HIL_L3_OUT_DIR=/tmp/task3_smoke_nostep \
uv run python run.py --sim nvc --top top_hil -k test_top_hil_pwm_replay_l3 --build-dir sim_build/task3_smoke_nostep
python3 -c "import json; m=json.load(open('/tmp/task3_smoke_nostep/metrics.json')); assert 'transient' not in m; print('OK: sem transient quando step nao configurado')"
```

Expected: teste passa (mesmo caso sine curto já validado antes), `transient` ausente do `metrics.json`.

- [ ] **Step 6: Smoke test com degrau ativo**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
IM_CLOCK_FREQUENCY=200000000 IM_SOLVER_STEP_CYCLES=26 IM_RS=0.4396 IM_RR=0.2826 IM_LS=0.0031364 IM_LR=0.0063264 IM_LM=0.1099442 IM_J=0.4 IM_NPP=2.0 \
HIL_PWM_FREQUENCY=1000 HIL_L3_STEPS=7692308 HIL_L3_WARMUP_STEPS=400 HIL_L3_RECORD_INTERVAL=962 HIL_L3_VDC=1240 HIL_L3_MODULATION=1.0 \
HIL_L3_REF_MODE=vf HIL_L3_VF_BASE_HZ=60 HIL_L3_VF_ACC_HZ_S=120 \
HIL_L3_TLOAD_NM=29.17840623351415 HIL_L3_TLOAD_STEP_NM=87.53521870054244 HIL_L3_TLOAD_STEP_TIME_S=0.6 \
HIL_L3_OUT_DIR=/tmp/task3_smoke_step \
uv run python run.py --sim nvc --top top_hil -k test_top_hil_pwm_replay_l3 --build-dir sim_build/task3_smoke_step
python3 -c "
import json
m = json.load(open('/tmp/task3_smoke_step/metrics.json'))
t = m['transient']
print(json.dumps(t, indent=2))
assert 'vhdl' in t and 'c' in t
"
```

Expected: teste passa (L3 não tem o assert de fluxo hardcoded, deve passar mesmo com carga — ver Global Constraints), `transient` presente e com valores plausíveis.

- [ ] **Step 7: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add verification/cocotb/tests/test_top_hil.py
git commit -m "feat(validation): suporte a degrau de carga + metricas de transitorio em test_top_hil.py"
```

---

## Task 4: Repassar `tload_step_nm`/`tload_step_time_s` no orquestrador

**Files:**
- Modify: `verification/cocotb/scripts/run_campaign_matrix.py`
- Modify: `verification/cocotb/scripts/run_campaign.py`
- Modify: `verification/cocotb/scripts/tests/test_run_campaign_matrix.py`
- Modify: `verification/cocotb/scripts/tests/test_run_campaign_env.py`

**Interfaces:**
- Consumes: nenhuma interface nova — só estende os campos opcionais que `build_l2_env`/`build_l3_env` já aceitam via `exp.get(...)`.
- Produces: quando `exp` (o dict do experimento no JSON da matriz) tem `tload_step_nm` E `tload_step_time_s`, o env dict retornado ganha `HIL_VF_TLOAD_STEP_NM`/`HIL_VF_TLOAD_STEP_TIME_S` (L2) ou `HIL_L3_TLOAD_STEP_NM`/`HIL_L3_TLOAD_STEP_TIME_S` (L3). Ausência de qualquer um dos dois campos no experimento mantém o comportamento atual (nenhuma env var de degrau é setada).

- [ ] **Step 1: Escrever os testes que falham**

Em `verification/cocotb/scripts/tests/test_run_campaign_matrix.py`, adicionar:

```python
def test_build_l2_env_vf_mode_includes_load_step_when_present(tmp_path):
    config = {"defaults": _defaults()}
    exp = {
        "test_mode": "vf", "duration_s": 1.0, "record_interval": 962,
        "vf_base_hz": 60.0, "vf_acc_hz_s": 120.0, "tload_nm": 29.17840623351415,
        "tload_step_nm": 87.53521870054244, "tload_step_time_s": 0.6,
    }
    env = rcm.build_l2_env(config, exp, tmp_path)
    assert env["HIL_VF_TLOAD_STEP_NM"] == "87.53521870054244"
    assert env["HIL_VF_TLOAD_STEP_TIME_S"] == "0.6"


def test_build_l2_env_vf_mode_omits_load_step_when_absent(tmp_path):
    config = {"defaults": _defaults()}
    exp = {
        "test_mode": "vf", "duration_s": 0.5, "record_interval": 481,
        "vf_base_hz": 60.0, "vf_acc_hz_s": 120.0, "tload_nm": 0.0,
    }
    env = rcm.build_l2_env(config, exp, tmp_path)
    assert "HIL_VF_TLOAD_STEP_NM" not in env
    assert "HIL_VF_TLOAD_STEP_TIME_S" not in env
```

Em `verification/cocotb/scripts/tests/test_run_campaign_env.py`, adicionar:

```python
def test_build_l3_env_includes_load_step_when_present(tmp_path):
    exp = {
        "id": "x", "duration_s": 1.0, "tload_nm": 29.17840623351415,
        "tload_step_nm": 87.53521870054244, "tload_step_time_s": 0.6,
    }
    env = rc.build_l3_env(_base_config(), exp, tmp_path)
    assert env["HIL_L3_TLOAD_STEP_NM"] == "87.53521870054244"
    assert env["HIL_L3_TLOAD_STEP_TIME_S"] == "0.6"


def test_build_l3_env_omits_load_step_when_absent(tmp_path):
    exp = {"id": "x", "duration_s": 0.5, "tload_nm": 0.0}
    env = rc.build_l3_env(_base_config(), exp, tmp_path)
    assert "HIL_L3_TLOAD_STEP_NM" not in env
    assert "HIL_L3_TLOAD_STEP_TIME_S" not in env
```

- [ ] **Step 2: Rodar os testes — verificar que falham**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/test_run_campaign_matrix.py scripts/tests/test_run_campaign_env.py -v 2>&1 | tail -20
```

Expected: os 4 testes novos falham (`KeyError`/`AssertionError`, as env vars ainda não existem).

- [ ] **Step 3: Adicionar o passthrough em `build_l2_env`**

Em `verification/cocotb/scripts/run_campaign_matrix.py`, dentro de `build_l2_env`, no ramo `if test_mode == "vf":`, logo após `"HIL_VF_TLOAD_NM": env_number(exp.get("tload_nm", 0.0)),`:

```python
# Antes:
            "HIL_VF_TLOAD_NM": env_number(exp.get("tload_nm", 0.0)),
            "HIL_VF_INITIAL_THETA_RAD": env_number(theta),

# Depois:
            "HIL_VF_TLOAD_NM": env_number(exp.get("tload_nm", 0.0)),
            "HIL_VF_INITIAL_THETA_RAD": env_number(theta),
```

(mantém a linha `HIL_VF_INITIAL_THETA_RAD` como está — o passthrough do degrau entra por fora do `env.update({...})`, logo depois dele, já que é condicional):

```python
# Adicionar logo apos o env.update({...}) do ramo "vf" (apos o fechamento do dict, ainda dentro do `if test_mode == "vf":`):
        if "tload_step_nm" in exp and "tload_step_time_s" in exp:
            env["HIL_VF_TLOAD_STEP_NM"] = env_number(exp["tload_step_nm"])
            env["HIL_VF_TLOAD_STEP_TIME_S"] = env_number(exp["tload_step_time_s"])
```

- [ ] **Step 4: Adicionar o passthrough em `build_l3_env`**

Em `verification/cocotb/scripts/run_campaign.py`, dentro de `build_l3_env`, logo após a linha `"HIL_L3_TLOAD_NM": env_number(...)` (adicionada na Task 4 da campanha anterior):

```python
# Antes:
        "HIL_L3_TLOAD_NM": env_number(exp.get("tload_nm", defaults.get("tload_nm", 0.0))),
        "HIL_L3_OUT_DIR": str(out_dir.resolve()),
    })
    return env

# Depois:
        "HIL_L3_TLOAD_NM": env_number(exp.get("tload_nm", defaults.get("tload_nm", 0.0))),
        "HIL_L3_OUT_DIR": str(out_dir.resolve()),
    })
    if "tload_step_nm" in exp and "tload_step_time_s" in exp:
        env["HIL_L3_TLOAD_STEP_NM"] = env_number(exp["tload_step_nm"])
        env["HIL_L3_TLOAD_STEP_TIME_S"] = env_number(exp["tload_step_time_s"])
    return env
```

- [ ] **Step 5: Rodar os testes — verificar que passam**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/test_run_campaign_matrix.py scripts/tests/test_run_campaign_env.py -v
```

Expected: todos passam (9 em `test_run_campaign_matrix.py`, 7 em `test_run_campaign_env.py`).

- [ ] **Step 6: Rodar a suíte inteira**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/ models/tests/ -v
```

Expected: todos passam, sem regressão.

- [ ] **Step 7: Commit**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add verification/cocotb/scripts/run_campaign_matrix.py \
        verification/cocotb/scripts/run_campaign.py \
        verification/cocotb/scripts/tests/test_run_campaign_matrix.py \
        verification/cocotb/scripts/tests/test_run_campaign_env.py
git commit -m "feat(validation): repassa tload_step_nm/tload_step_time_s nos env builders L2/L3"
```

---

## Task 5: Adicionar B1-B3 à campanha 03

**Files:**
- Modify: `verification/results/2026-07-04_campaign_03/manifest.json`
- Modify: `verification/results/2026-07-04_campaign_03/campaign_story.json`
- Modify: `verification/cocotb/campaigns/campaign_03_full_matrix.json`
- Modify: `verification/cocotb/scripts/tests/test_campaign_03_matrix.py`

**Interfaces:**
- Produces: 3 novos casos (`B1`, `B2`, `B3`) no manifest; grupo `"B"` na `campaign_story.json`; 6 novos experimentos (`B1_l2`, `B1_l3`, `B2_l2`, `B2_l3`, `B3_l2`, `B3_l3`) na matriz, cada um com `case_id` batendo com o manifest.

- [ ] **Step 1: Adicionar os 3 casos ao `manifest.json`**

Em `verification/results/2026-07-04_campaign_03/manifest.json`, dentro da lista `"cases"`, adicionar (não remover nenhum caso existente):

```json
    {"id": "B1", "dir": "B1_step025_to075", "group": "perturbacao_carga", "freq_hz": 60.0, "tload_pre_nm": 29.17840623351415, "tload_post_nm": 87.53521870054244, "t_step_s": 0.6, "status": "pending", "l2_results": {}, "l3_results": {}},
    {"id": "B2", "dir": "B2_step050_to100", "group": "perturbacao_carga", "freq_hz": 60.0, "tload_pre_nm": 58.3568124670283, "tload_post_nm": 116.7136249340566, "t_step_s": 0.6, "status": "pending", "l2_results": {}, "l3_results": {}},
    {"id": "B3", "dir": "B3_step075_to025", "group": "perturbacao_carga", "freq_hz": 60.0, "tload_pre_nm": 87.53521870054244, "tload_post_nm": 29.17840623351415, "t_step_s": 0.6, "status": "pending", "l2_results": {}, "l3_results": {}}
```

- [ ] **Step 2: Adicionar o grupo "B" à `campaign_story.json`**

Em `verification/results/2026-07-04_campaign_03/campaign_story.json`, dentro de `"matrix"`, logo após o fechamento do grupo `"A"`, adicionar:

```json
    "B": {
      "label": "Perturbacao de Carga em Regime",
      "description": "Motor ja em regime permanente a 60 Hz; aplica um degrau de torque de carga em t=0.6s e observa a resposta transitoria (queda de velocidade, pico de corrente, tempo de recuperacao). E o criterio que o proprio plano de validacao chama de mais direto para qualidade de um simulador HIL.",
      "cases": [
        {"id": "B1", "condicao": "60 Hz, 0.25 Tn", "perturbacao": "0.25 -> 0.75 Tn em t=0.6s", "objetivo": "Queda de velocidade, pico de corrente, recuperacao."},
        {"id": "B2", "condicao": "60 Hz, 0.50 Tn", "perturbacao": "0.50 -> 1.00 Tn em t=0.6s", "objetivo": "Resposta a carga nominal."},
        {"id": "B3", "condicao": "60 Hz, 0.75 Tn", "perturbacao": "0.75 -> 0.25 Tn em t=0.6s", "objetivo": "Sobressinal apos alivio de carga."}
      ]
    }
```

(atenção: o grupo `"A"` já existente termina com `}` sem vírgula antes de `}` de fechamento de `"matrix"` — adicionar `,` depois do `}` do grupo `"A"` antes de inserir `"B": {...}`.)

- [ ] **Step 3: Adicionar os 6 experimentos à matriz**

Em `verification/cocotb/campaigns/campaign_03_full_matrix.json`, dentro de `"experiments"`, adicionar ao final da lista (antes do `]` de fechamento):

```json
    {
      "id": "B1_l2", "case_id": "B1", "result_key": "step_1s",
      "level": "l2", "top": "tim_solver", "runner": "cocotb", "test_mode": "vf", "enabled": true,
      "description": "B1: degrau de carga 0.25Tn->0.75Tn em regime (60Hz), t_step=0.6s.",
      "duration_s": 1.0, "record_interval": 962, "vf_base_hz": 60.0, "vf_acc_hz_s": 120.0,
      "tload_nm": 29.17840623351415, "tload_step_nm": 87.53521870054244, "tload_step_time_s": 0.6,
      "output_dir": "B1_step025_to075/l2_step_1s"
    },
    {
      "id": "B1_l3", "case_id": "B1", "result_key": "pwm_replay_step_1s",
      "level": "l3", "runner": "cocotb", "top": "top_hil", "testcase": "test_top_hil_pwm_replay_l3", "enabled": true,
      "description": "B1 L3: mesmo degrau do B1 L2, PWM replay.",
      "duration_s": 1.0, "record_interval": 962, "ref_mode": "vf", "vf_base_hz": 60.0, "vf_acc_hz_s": 120.0,
      "modulation": 1.0, "tload_nm": 29.17840623351415, "tload_step_nm": 87.53521870054244, "tload_step_time_s": 0.6,
      "output_dir": "B1_step025_to075/l3_top_pwm_replay_step_1s"
    },
    {
      "id": "B2_l2", "case_id": "B2", "result_key": "step_1s",
      "level": "l2", "top": "tim_solver", "runner": "cocotb", "test_mode": "vf", "enabled": true,
      "description": "B2: degrau de carga 0.50Tn->1.00Tn em regime (60Hz), t_step=0.6s.",
      "duration_s": 1.0, "record_interval": 962, "vf_base_hz": 60.0, "vf_acc_hz_s": 120.0,
      "tload_nm": 58.3568124670283, "tload_step_nm": 116.7136249340566, "tload_step_time_s": 0.6,
      "output_dir": "B2_step050_to100/l2_step_1s"
    },
    {
      "id": "B2_l3", "case_id": "B2", "result_key": "pwm_replay_step_1s",
      "level": "l3", "runner": "cocotb", "top": "top_hil", "testcase": "test_top_hil_pwm_replay_l3", "enabled": true,
      "description": "B2 L3: mesmo degrau do B2 L2, PWM replay.",
      "duration_s": 1.0, "record_interval": 962, "ref_mode": "vf", "vf_base_hz": 60.0, "vf_acc_hz_s": 120.0,
      "modulation": 1.0, "tload_nm": 58.3568124670283, "tload_step_nm": 116.7136249340566, "tload_step_time_s": 0.6,
      "output_dir": "B2_step050_to100/l3_top_pwm_replay_step_1s"
    },
    {
      "id": "B3_l2", "case_id": "B3", "result_key": "step_1s",
      "level": "l2", "top": "tim_solver", "runner": "cocotb", "test_mode": "vf", "enabled": true,
      "description": "B3: degrau de carga 0.75Tn->0.25Tn em regime (60Hz), t_step=0.6s.",
      "duration_s": 1.0, "record_interval": 962, "vf_base_hz": 60.0, "vf_acc_hz_s": 120.0,
      "tload_nm": 87.53521870054244, "tload_step_nm": 29.17840623351415, "tload_step_time_s": 0.6,
      "output_dir": "B3_step075_to025/l2_step_1s"
    },
    {
      "id": "B3_l3", "case_id": "B3", "result_key": "pwm_replay_step_1s",
      "level": "l3", "runner": "cocotb", "top": "top_hil", "testcase": "test_top_hil_pwm_replay_l3", "enabled": true,
      "description": "B3 L3: mesmo degrau do B3 L2, PWM replay.",
      "duration_s": 1.0, "record_interval": 962, "ref_mode": "vf", "vf_base_hz": 60.0, "vf_acc_hz_s": 120.0,
      "modulation": 1.0, "tload_nm": 87.53521870054244, "tload_step_nm": 29.17840623351415, "tload_step_time_s": 0.6,
      "output_dir": "B3_step075_to025/l3_top_pwm_replay_step_1s"
    }
```

(lembrar de adicionar `,` após o `}` do último experimento existente, `A7_l3`, antes de colar este bloco.)

- [ ] **Step 4: Atualizar `test_campaign_03_matrix.py` para 28 experimentos**

Em `verification/cocotb/scripts/tests/test_campaign_03_matrix.py`:

```python
# Antes:
def test_matrix_has_22_experiments():
    config = _load()
    assert len(config["experiments"]) == 22

# Depois:
def test_matrix_has_28_experiments():
    config = _load()
    assert len(config["experiments"]) == 28
```

E, na função `test_cocotb_experiments_have_required_fields`, adicionar a checagem de consistência do par step/step_time (depois do bloco `if exp["level"] == "l3":`):

```python
        if "tload_step_nm" in exp or "tload_step_time_s" in exp:
            assert "tload_step_nm" in exp and "tload_step_time_s" in exp, (
                f"{exp['id']}: tload_step_nm e tload_step_time_s devem vir juntos"
            )
```

- [ ] **Step 5: Rodar os testes**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/test_campaign_03_matrix.py -v
```

Expected: todos passam, incluindo `test_matrix_has_28_experiments` e `test_case_ids_match_manifest` (agora com B1/B2/B3 batendo entre matriz e manifest).

- [ ] **Step 6: Rodar a suíte inteira de novo**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run pytest scripts/tests/ models/tests/ -v
```

Expected: todos passam.

- [ ] **Step 7: Commit (só a matriz tracked entra — manifest.json fica untracked, igual ao resto de `verification/results/`)**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop
git add verification/cocotb/campaigns/campaign_03_full_matrix.json \
        verification/cocotb/scripts/tests/test_campaign_03_matrix.py
git commit -m "feat(validation): adiciona Grupo B (B1-B3) a matriz da campaign_03"
```

`manifest.json` e `campaign_story.json` em `verification/results/2026-07-04_campaign_03/` **não são commitados** — mesma regra já estabelecida (resultados de campanha ficam untracked). As edições nesses dois arquivos ficam só em disco.

---

## Task 6: Smoke test real — B1 (L2+L3) e depois a matriz completa

**Files:**
- Nenhum arquivo novo — execução real, validação final antes de rodar B1-B3 inteiro.

**Interfaces:**
- Consumes: tudo das Tasks 1-5.

- [ ] **Step 1: Rodar só B1 (L2+L3) de verdade pelo orquestrador**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run python scripts/run_campaign_matrix.py \
  --config campaigns/campaign_03_full_matrix.json \
  --manifest ../results/2026-07-04_campaign_03/manifest.json \
  --summary ../results/2026-07-04_campaign_03/campaign_dashboard/summary.csv \
  --only B1_l2 --only B1_l3 --max-parallel 2
```

Expected: `B1_l3` termina `[OK]` (L3 não tem assert de fluxo); `B1_l2` pode terminar `[FAIL]` (assert de fluxo hardcoded, esperado para caso com carga — ver Global Constraints). Em ambos os casos, `metrics.json` deve existir com a chave `transient`.

- [ ] **Step 2: Confirmar os artefatos e a métrica de transitório**

```bash
cat /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/results/2026-07-04_campaign_03/B1_step025_to075/l2_step_1s/metrics.json | python3 -c "import json,sys; m=json.load(sys.stdin); print(json.dumps(m['transient'], indent=2))"
cat /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/results/2026-07-04_campaign_03/B1_step025_to075/l3_top_pwm_replay_step_1s/metrics.json | python3 -c "import json,sys; m=json.load(sys.stdin); print(json.dumps(m['transient'], indent=2))"
```

Expected: ambos imprimem `vhdl`/`c` com `speed_peak_deviation_rad_s > 0` (o degrau de carga deve causar uma queda de velocidade real) e `current_peak_a` maior que a corrente de regime pré-degrau.

- [ ] **Step 3: Confirmar que S0/A1-A7 não foram re-executados**

```bash
python3 -c "
import json
m = json.load(open('/home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/results/2026-07-04_campaign_03/manifest.json'))
for c in m['cases']:
    if c['id'] not in ('B1','B2','B3'):
        print(c['id'], c['status'])
"
```

Expected: status de S0/A1-A7 idênticos ao estado final da campanha anterior (nenhum virou `pending` de novo, nenhum re-rodou) — confirma que a retomada pulou tudo que já estava `ok`.

- [ ] **Step 4: Rodar B2 e B3 (os que faltam) de verdade**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run python scripts/run_campaign_matrix.py \
  --config campaigns/campaign_03_full_matrix.json \
  --manifest ../results/2026-07-04_campaign_03/manifest.json \
  --summary ../results/2026-07-04_campaign_03/campaign_dashboard/summary.csv \
  --only B2_l2 --only B2_l3 --only B3_l2 --only B3_l3 --max-parallel 4
```

Expected: os 4 experimentos rodam (L3 `[OK]`, L2 provavelmente `[FAIL]` no assert de fluxo, ambos com `metrics.json`/`transient` reais). Nenhum outro caso da matriz é tocado.

- [ ] **Step 5: Regenerar o dashboard**

```bash
cd /home/urielcontardi/Desktop/Projects/Hardware-in-the-Loop/verification/cocotb
uv run python scripts/build_campaign_dashboard.py --campaign ../results/2026-07-04_campaign_03
```

Expected: `Dashboard gerado em .../2026-07-04_campaign_03/index.html`, agora mostrando o Grupo B ao lado de S0/Grupo A.

- [ ] **Step 6: Nenhum commit de resultados — igual às tasks anteriores**

`verification/results/` continua gitignored. Nada a commitar após este smoke test.

---

## Self-Review

**Spec coverage:**

| Requisito da spec | Task |
|---|---|
| `compute_transient_metrics` (pico, recuperação) | Task 1 |
| Degrau de carga em L2 sem quebrar comportamento atual | Task 2 |
| Degrau de carga em L3 (segunda escrita AXI mid-loop) | Task 3 |
| Env builders repassam os 2 campos novos | Task 4 |
| B1-B3 na matriz/manifest/story | Task 5 |
| Smoke test real + confirmação de retomada | Task 6 |
| B4/B5, Grupo C fora de escopo | Nenhuma task os implementa (correto) |

**Placeholder scan:** nenhum `TBD`/`TODO`; todo código é completo e executável.

**Consistência de tipos:** `compute_transient_metrics(t, speed, i_alpha, i_beta, t_step, settle_tol_frac=0.05) -> dict` usado de forma idêntica em Task 2 (L2, com `t_us/1e6`) e Task 3 (L3, com `t_s` direto) — mesma assinatura, mesmas chaves de retorno (`speed_before_step_rad_s`, `speed_peak_deviation_rad_s`, `current_peak_a`, `recovery_time_s`). Nomes de env vars (`HIL_VF_TLOAD_STEP_NM`/`_TIME_S`, `HIL_L3_TLOAD_STEP_NM`/`_TIME_S`) consistentes entre Task 2/3 (onde são lidas) e Task 4 (onde são escritas pelos env builders).
