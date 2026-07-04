# Campanhas cocotb

Edite os arquivos JSON deste diretorio para escolher quais experimentos rodar.

## L3 PWM replay

Arquivo principal:

```text
campaigns/l3_pwm_replay.json
```

Comando a partir de `verification/cocotb`:

```bash
uv run python scripts/run_campaign.py --config campaigns/l3_pwm_replay.json
```

Ou, a partir da raiz do repositorio:

```bash
cd verification/cocotb
bash run_l3_campaign.sh
```

Para rodar apenas um experimento especifico:

```bash
uv run python scripts/run_campaign.py --config campaigns/l3_pwm_replay.json --only l3_top_pwm_replay_vf_2s
```

Cada experimento habilitado (`enabled: true`) cria uma pasta de resultado com:

- `run_config_resolved.json`: configuracao efetiva e variaveis de ambiente.
- `metrics.json`: metricas calculadas em todos os passos validos.
- `top_pwm_replay_vs_c.csv`: CSV decimado conforme `record_interval`.
- `overlay.html`: grafico interativo.
- `README.md`: resumo do caso e tempo de execucao.

Para casos longos, ajuste `record_interval`. As metricas continuam sendo
calculadas em todos os passos; a decimacao afeta apenas o CSV/HTML.
