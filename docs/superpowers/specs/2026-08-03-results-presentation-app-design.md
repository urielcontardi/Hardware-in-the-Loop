# App de apresentação de resultados HIL (público, `/results`)

## Contexto e motivação

O `results_explorer_app.py` (spec `2026-07-07-results-explorer-design.md`) já
existe e roda bem localmente, mas foi desenhado para uso pessoal de
exploração: seleciona entre 6 campanhas em `verification/results/`, várias
delas obsoletas ou intermediárias (ex.: `2026-07-25_campaign_l4_v2`,
`2026-07-14_campaign_l4`, notas tipo "prefira a `_final`"). Isso é ruído
aceitável pra mim, mas inadequado pra mostrar ao orientador — a lista de
campanhas exige que ele já saiba qual escolher.

Este spec cobre um segundo app, curado, publicado em
`https://hil.contardi.dev/results`, que conta a história de validação (L2 →
L3 → L4) sem exigir esse conhecimento prévio. O explorer completo continua
existindo, sem mudança de comportamento, só de uso local.

## Escopo

- Novo app Streamlit `results_presentation_app.py`, com navegação fixa
  **Nível de validação → Caso**, sem seletor de campanha.
- Refatoração de `results_explorer_app.py`: extrai as funções de
  construção de figura/cache para um módulo compartilhado, sem mudar
  comportamento do explorer completo.
- Publicação via Docker + regra de path no Cloudflare Tunnel já ativo
  (`/etc/cloudflared/config.yml`), path `/results` no host `hil.contardi.dev`
  existente (raiz continua servindo o monitor Go/`hil-gateway`).
- Fora de escopo: autenticação/controle de acesso (mesmo padrão sem auth
  dos demais hosts do túnel), edição de dados, campanhas além das duas
  canônicas atuais, testes automatizados de UI.

## Conteúdo e navegação

Dois níveis de seletor, ambos `st.selectbox`/similar, sem cascata de
campanha:

1. **Nível** — `L2`, `L3` ou `L4`, cada um mapeado a uma campanha canônica
   fixa no código (não escolhida pelo usuário):
   - `L2` — "C/C++ vs VHDL do Solver". Campanha
     `2026-07-04_campaign_03`, runs com prefixo `l2_*` dentro de cada caso.
   - `L3` — "Top_HIL Simulado vs C/C++". Mesma campanha, runs `l3_*`.
   - `L4` — "FPGA Real vs Offline". Campanha `2026-07-25_campaign_l4_final`.
   - Pergunta e nota de cada nível vêm de
     `verification/results/2026-07-04_campaign_03/campaign_story.json`
     (`levels[].question`/`levels[].note`), exibidas como texto de contexto
     acima do seletor de caso — não hardcoded de novo no app.
2. **Caso** — reaproveita `_CASE_INFO`/`_GROUP_ORDER` já existentes em
   `results_explorer_app.py` (nomes amigáveis, agrupamento
   Sanidade/Partida/Perturbação), migrados para o módulo compartilhado.
   Para `L2`/`L3`, a lista de casos vem de `list_cases()` na campanha
   `campaign_03`; runs dentro do caso são filtrados por prefixo (`l2_`/
   `l3_`) antes de aplicar a mesma lógica de "esconde seletor se sobrar
   1 run" que o explorer já tem. Para `L4`, casos vêm de
   `campaign_l4_final` (`S0`, `A1`, `A3`, `A5`, `B1`, `B2`).

Multiselect de canais e o seletor "Vista" do L4 (Ensaio completo / Zoom
partida / Zoom regime) continuam como no explorer — são conteúdo real, não
poluição de escolha.

## Arquitetura

Quatro arquivos em `verification/cocotb/scripts/`:

- **`results_explorer_data.py`** (existente, sem mudança) — leitura pura de
  disco, compartilhada pelos dois apps.
- **`results_explorer_render.py`** (novo) — extraído de
  `results_explorer_app.py`: `_load_csv`, `_load_npz`, `_load_full_capture`,
  `_find_raw_hilbin`, `_build_figure`, `_build_npz_figure`,
  `_build_full_capture_figure`, `_flatten_metrics`, `_SUFFIX_LABELS`,
  `_SERIES_STYLE`, `_CASE_INFO`, `_GROUP_ORDER`, `_case_id`, `_case_label`.
  Sem `st.set_page_config`/fluxo de página — só funções puras (algumas
  usam `st.cache_data`, isso fica).
- **`results_explorer_app.py`** (existente, refatorado só nos imports —
  passa a importar de `results_explorer_render` em vez de definir
  localmente). Comportamento e UI inalterados.
- **`results_presentation_app.py`** (novo) — importa
  `results_explorer_data` + `results_explorer_render`, implementa o fluxo
  Nível → Caso descrito acima.

## Deploy e roteamento

**Container**, seguindo o padrão já usado por `apps/hil-go` (Docker com
`restart: unless-stopped`, sem systemd dedicado):

- `verification/cocotb/Dockerfile.results` — Python 3.12 + `uv sync`
  (dependências `streamlit`/`pandas`/`plotly` já em `pyproject.toml`),
  copia `scripts/`.
- `verification/cocotb/docker-compose.results.yml` — monta
  `../results:/app/verification/results:ro` (leitura apenas — o app nunca
  escreve). Comando:
  ```
  uv run streamlit run scripts/results_presentation_app.py \
    --server.port=8503 --server.address=0.0.0.0 \
    --server.baseUrlPath=/results
  ```
  Porta `8503`: não colide com nenhuma porta já em uso no host (`5177,
  8000, 8081, 3000, 9444, 8501, 80`) — evita inclusive a `8501`, hoje
  reivindicada (mas sem processo ativo) por `proposal.contardi.dev`.
- `--server.baseUrlPath=/results` é obrigatório: o Cloudflare Tunnel
  encaminha o path completo (`/results/...`) sem remover o prefixo; sem
  essa flag os assets/websocket do Streamlit quebram atrás do subpath.

**Roteamento** — adicionar em `/etc/cloudflared/config.yml` uma regra de
`path` **antes** da entrada genérica de `hil.contardi.dev` (cloudflared
casa de cima pra baixo, primeira regra vence):

```yaml
  - hostname: hil.contardi.dev
    path: ^/results(/.*)?$
    service: http://localhost:8503
  - hostname: hil.contardi.dev
    service: http://localhost:5177
  - service: http_status:404
```

Depois `sudo systemctl restart cloudflared`. A raiz de `hil.contardi.dev`
continua servindo o monitor Go (`hil-gateway`) sem alteração.

Sem autenticação — mesmo padrão dos demais hosts do túnel (nenhum tem
Cloudflare Access configurado hoje); o link não é divulgado publicamente,
só compartilhado com o orientador.

## Tratamento de erros

Mesma filosofia de degradação de `results_explorer_data.py`/
`results_explorer_app.py`, sem exceção visível ao usuário:

- Campanha canônica (`campaign_03` ou `campaign_l4_final`) ausente/vazia
  no disco → `st.error` com nome da campanha esperada, sem traceback.
- Caso sem run reconhecido (após filtro de prefixo `l2_`/`l3_`) →
  `st.info`.
- `metrics.json` ausente/malformado → pula a tabela, sem exceção.
- Nenhum canal `vhdl_*`/`ref_*` (ou `fpga_*`/`cmod_*`) detectado → aviso,
  sem tentar plotar.

## Testes

- `pytest` para as funções puras extraídas em `results_explorer_render.py`
  (equivalente ao que já existe/existiria para `results_explorer_app.py`).
- Sem teste automatizado de UI (Streamlit) — verificação manual:
  1. Local: `uv run streamlit run scripts/results_presentation_app.py`,
     navegar os 3 níveis (L2/L3/L4) pelo menos uma vez cada, confirmar
     gráfico e zoom funcionando.
  2. `docker compose -f docker-compose.results.yml up -d --build`, curl
     local (`curl http://127.0.0.1:8503/results`) confirmando 200.
  3. Após atualizar e reiniciar o `cloudflared`,
     `https://hil.contardi.dev/results` carrega igual ao teste local
     (assets/websocket ok com `baseUrlPath`).
  4. `https://hil.contardi.dev/` (raiz) continua servindo o monitor Go
     normalmente — confirma que a nova regra de path não quebrou a rota
     existente.

## Fora de escopo

- Autenticação/controle de acesso.
- Novas campanhas além das duas canônicas (`campaign_03`,
  `campaign_l4_final`) — se uma nova campanha se tornar canônica, o
  mapeamento fixo no código precisa ser atualizado manualmente.
- Editar/gerar `metrics.json`/CSVs — o app só lê o que já existe em disco.
- Mudar o comportamento do explorer completo (`results_explorer_app.py`)
  além da extração de código compartilhado.
