# Campanha 03 — Matriz Completa S0+Grupo A com Orquestrador Paralelo

## Contexto e motivação

Duas correções invalidaram todos os resultados numéricos anteriores:

1. Parâmetros de motor divergentes (`Rs=0.435/J=0.192` errados vs `Rs=0.4396/J=0.4`
   corretos, corrigido no commit `e0e6907`).
2. Arquitetura sem sincronismo real pico+vale da portadora (referência V/f
   atualizada por relógio de software livre, não pela IRQ real da portadora
   PWM — corrigido nos commits `f84ff87`...`60b0401`, plano
   `docs/superpowers/plans/2026-07-04-vf-pwm-irq-sync.md`).

A `campaign_02` (`verification/results/2026-07-04_campaign_02/`) foi criada só
para a correção 1 e nunca rodou nada (`status: not_started`). Como as duas
correções afetam os mesmos casos de teste, esta spec define uma campanha nova
(`campaign_03`) que já nasce com ambas as correções aplicadas, evitando uma
terceira rodada de re-execução.

## Objetivo

Gerar, numa única bateria orquestrada, todos os resultados L2/L3 que entram
como evidência direta no capítulo de resultados da dissertação: o estudo
metodológico S0 e a matriz de partida/aceleração completa (Grupo A, A1-A7).

## Escopo

### Matriz de casos (22 execuções cocotb)

**S0 — estudo metodológico** (reexecução dos casos "oficiais" já definidos em
`docs/experimental-validation-plan.md`; diagnósticos como locked-rotor e 12Hz
constante ficam fora, pois sustentam uma conclusão qualitativa já registrada,
não uma métrica de capítulo):

| id | nível | descrição |
|---|---|---|
| `l2_sine_60hz_realts` | L2 | seno trifásico ideal 60 Hz, sem carga |
| `l2_vf_50ms_realts` | L2 | rampa V/f, janela 0-50 ms |
| `l2_vf_2s_realts` | L2 | rampa V/f completa 0-2 s |
| `l3_top_pwm_replay_sine_6ms` | L3 | `Top_HIL` com referência senoidal, PWM replay |
| `l3_top_pwm_replay_vf_50ms` | L3 | `Top_HIL` com rampa V/f 0-50ms, PWM replay |
| `l3_top_pwm_replay_vf_2s` | L3 | `Top_HIL` com rampa V/f 0-2s, PWM replay |
| `l3_fullstack_mock_vf_50ms` | L3 | full-stack mock C independente, 0-50ms |
| `l3_fullstack_mock_vf_2s` | L3 | full-stack mock C independente, 0-2s |

**Grupo A — partida e aceleração** (`docs/experimental-validation-plan.md`,
seção "Grupos de Teste"), L2 (solver isolado) + L3 (`Top_HIL` PWM-replay) para
cada um dos 7 casos:

| id | rampa (t_acc) | carga | objetivo |
|---|---|---|---|
| A1 | 0.5 s | 0 Tn | corrente de partida e fluxo a vazio |
| A2 | 0.5 s | 1.0 Tn | pior caso de corrente com rampa rápida |
| A3 | 1.0 s | 0.5 Tn | caso base do HIL |
| A4 | 2.0 s | 1.0 Tn | partida suave sob carga nominal |
| A5 | 5.0 s | 0 Tn | erro acumulado e estabilidade |
| A6 | 5.0 s | 1.0 Tn | torque com baixa aceleração |
| A7 | 2.0 s | 1.1 Tn | sobrecarga curta e margem numérica |

Total: 8 (S0) + 14 (7 casos × L2/L3) = 22 execuções cocotb.

### Fora de escopo

- Grupo B (degrau de carga) e Grupo C (dinâmica adicional) — ficam para
  iteração futura separada.
- L4 (FPGA real) — não depende deste orquestrador (usa `.hilbin` capturado).
- Correção da inconsistência de fórmula de NRMSE entre L2/L3 e L4 (já
  registrada em `docs/metrics-gap-analysis.md`, item 1) — não é escopo desta
  campanha.

## Riscos identificados e mitigação

Rodar múltiplos cocotb/NVC em paralelo tem dois pontos reais de corrida,
confirmados no código:

1. **Work library do simulador** — `run.py --build-dir` tem default fixo
   `sim_build`, usado por todo script atual sem override. Duas execuções
   paralelas elaborariam VHDL na mesma work library simultaneamente.
   *Mitigação:* cada caso roda com `--build-dir sim_build/<case_id>` próprio.

2. **`libim_model.so` do modelo C** — `models/im_reference_model.py:171-189`
   usa um caminho hardcoded (`verification/cocotb/sim_build/reference_model/
   libim_model.so`, não respeita `--build-dir`) e recompila se o `.so` não
   existir ou o `.c` for mais novo. Duas execuções paralelas caindo no "preciso
   compilar" ao mesmo tempo corromperiam o arquivo.
   *Mitigação:* orquestrador faz uma chamada serial única ("priming") antes de
   abrir o pool paralelo, garantindo o `.so` compilado e estável. Depois disso
   só há `dlopen` concorrente de um arquivo parado, que é seguro.

## Arquitetura

### `verification/cocotb/campaigns/campaign_03_full_matrix.json`

Um único arquivo de configuração: bloco `defaults` (motor Rs/Rr/Ls/Lr/Lm/J/npp
corretos, clock 200MHz, step_cycles 26, Vdc 1240V, PWM 1kHz) + lista
`experiments`, cada um com `id`, `level` (`l2`|`l3`), `output_dir`, duração,
carga, rampa, `ref_mode`. Substitui os ~10 scripts bash quase-duplicados
atuais (`run_a1_l2_vf_500ms.sh` etc.) por uma fonte única de verdade.

### `verification/cocotb/scripts/run_campaign_matrix.py`

Generaliza `run_campaign.py` (hoje só sabe rodar L3) para também rodar L2.
Responsabilidades:

- **Resolução de env por caso**: reaproveita `build_l3_env` para L3; adiciona
  `build_l2_env` equivalente para `tim_solver`/teste `vf` (variáveis
  `HIL_VF_*`), incluindo `--build-dir sim_build/<case_id>` único.
- **Priming serial**: antes do pool, uma chamada síncrona instancia
  `InductionMotorReferenceModel(..., backend="c")` uma vez, forçando a
  compilação do `.so` se necessário, fora de qualquer concorrência.
- **Pool limitado**: `--max-parallel N` (default `4`, ajustável via CLI —
  conservador dado que a máquina tem outros processos pesados rodando, ex.
  builds de Vivado, e RAM/swap já ocupados).
- **Log isolado por caso**: stdout/stderr de cada execução vai para
  `<case_root>/<level>/run.log`; o terminal só recebe uma linha de status por
  evento (início, fim, sucesso/falha) para não misturar saída de processos
  paralelos.
- **Sem aborto em cascata**: uma falha não interrompe os outros casos. Status
  final por caso registrado no manifest (`ok`/`failed`). Se `metrics.json` foi
  produzido mesmo com falha de assert, overlay/README ainda são gerados (dado
  de diagnóstico preservado).
- **Retomável**: reexecutar o script pula casos já `ok` no manifest, a menos
  que `--force` seja passado. `--only <id>` permite rodar um caso específico.
- **Pós-processamento por nível**: L3 reaproveita a geração de overlay já
  existente em `run_campaign.py` (`generate_l3_overlay`); L2 invoca
  `vf_report.py --compare-only --vhdl-csv <csv> --out <out_dir>/overlay.html`
  (não recomputa o modelo C do zero).
- **Dashboard final**: ao esvaziar o pool, chama
  `build_campaign_dashboard.py --campaign <dir>` e imprime uma tabela-resumo
  (caso, nível, status, tempo de parede, NRMSE principal) no terminal.

### Manifest da campanha

`verification/results/2026-07-04_campaign_03/manifest.json`, inicializado com
os 22 casos em `status: "pending"`, atualizado ao vivo para `"running"` /
`"ok"` / `"failed"` conforme o orquestrador avança. Inclui a mesma seção
`motor_source_of_truth` / `reason` / `supersedes` já usada em `campaign_02`,
apontando `"supersedes": ["2026-06-29_campaign_01", "2026-07-04_campaign_02"]`
e citando as duas correções (motor + sincronismo IRQ).

## Artefatos gerados

**Por caso** (`verification/results/campaign_03_.../<caso>/<nivel>/`):
`run_config_resolved.json`, `metrics.json`, CSV decimado, `overlay.html`,
`README.md`, `run.log`.

**Consolidado**: `manifest.json` (status ao vivo) e
`campaign_dashboard/dashboard.html` + `summary.csv` (regenerado ao final,
com link para cada artefato de caso).

## Estimativa de custo

Com base no throughput medido em `campaign_01` (L2 ≈1365 passos/s, L3 ≈673
passos/s): tempo total serial ≈95h; com `--max-parallel 4`, ≈24h (~1 dia
corrido), assumindo RAM suficiente. Ajustável para baixo se a máquina estiver
sob outra carga (ex. build de Vivado em andamento).

## Testes

- Teste unitário do parser de matriz (`build_l2_env`/`build_l3_env` geram os
  env vars esperados a partir de um experimento de exemplo).
- Teste do priming: `.so` já compilado não dispara recompilação (mtime check).
- Smoke test end-to-end com `--only <um caso rápido>` antes de rodar a matriz
  inteira.
