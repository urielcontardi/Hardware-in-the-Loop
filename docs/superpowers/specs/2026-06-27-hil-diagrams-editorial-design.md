# Diagramas do HIL — design editorial (conjunto para a dissertação)

**Data:** 2026-06-27
**Contexto:** Diagramas de arquitetura em `docs/diagrams/` para serem usados como
figuras na dissertação de mestrado. Cada diagrama é referenciado e explicado no
texto. Já existe a base de estilo (D2 monocromático + ELK ortogonal); este
documento define **o quê entra em cada figura** — não o estilo.

## Objetivo

Que a banca, lendo as figuras **em ordem**, entenda o sistema do geral ao
específico, com **nenhum bloco detalhado em dois lugares**. Cada figura é uma
unidade autocontida que um parágrafo do texto pode referenciar.

## Audiência

Banca e leitores acadêmicos. Implica: figuras limpas, foco em UMA ideia por
figura, profundidade suficiente para sustentar as contribuições técnicas
(discretização bilinear, ponto fixo, domínios de clock, decimação).

## Princípio organizador

**Por subsistema (paridade)** + um **mapa** âncora. Cada subsistema "possui" o
seu interior; um mapa de contexto, que nenhum subsistema possui, costura o todo.

A PL é dividida em duas figuras: **integração (HIL_AXI_Top)** e **núcleo
numérico (TIM_Solver)**, porque são dois assuntos densos e o solver é o coração
técnico da dissertação.

## Regra de fronteira (anti-redundância)

1. Cada figura mostra **só o seu interior** em detalhe.
2. Subsistemas vizinhos aparecem como **caixa-preta** na borda, rotulados com a
   interface (protocolo + taxa).
3. Cada **conceito transversal pertence a exatamente UMA figura**; nas demais
   aparece apenas como rótulo de borda, nunca re-explicado.

### Donos dos conceitos transversais

| Conceito transversal | Dono (detalhado em) |
|---|---|
| Cadeia de taxas fim-a-fim (7,69 MHz → ÷77 → ~100 kHz → display) | **00 Mapa** |
| Domínios de clock 100 MHz (FCLK0) / 200 MHz (MMCM) + CDC | **01 FPGA/Top** |
| Filtro anti-aliasing + decimador ÷77 + AXI-Stream/DMA | **01 FPGA/Top** |
| Ponto fixo Q14.28 + passo 26 ciclos = 130 ns | **02 Solver** |
| Dois regimes temporais (ISR @1 kHz vs DMA @~100 kHz) | **03 PS** |
| Pirâmide / decimação de display (min/max) | **04 Backend** |

## Conjunto de figuras (6)

Cada item: **Possui** (interior em detalhe) · **Caixa-preta** (vizinhos) ·
**Legenda** (ideia da figura).

### 00 — Mapa (contexto)
- **Possui:** os 3 domínios de execução (PL hard-RT · PS soft-RT · PC software);
  malha de controle (PS→PL @1 kHz) e caminho de telemetria (PL→PC); a cadeia de
  taxas global; qual clock governa cada domínio (anotação).
- **Caixa-preta:** o interior de todos os subsistemas.
- **Legenda:** "Arquitetura geral do HIL: malha de controle e caminho de
  telemetria."

### 01 — FPGA / HIL_AXI_Top (integração na PL)
- **Possui:** banco de registradores, modulador NPC (carrier 1 kHz), conversão
  estados→tensão (±Vdc/2), os **dois domínios de clock + CDC**, filtro
  anti-aliasing (Butterworth 2ª ord., fc≈40 kHz), **decimador ÷77 → ~100 kHz**,
  AXI-Stream 256-bit → AXI DMA, geração de carrier_tick/IRQ.
- **Caixa-preta:** TIM_Solver (detalhado na 02), PS.
- **Legenda:** "Integração na PL: modulação NPC, travessia de domínios de clock e
  cadeia de decimação até o DMA."

### 02 — TIM_Solver (núcleo numérico)
- **Possui:** entrada (Clarke / V_abc → αβ), espaço de estados
  x[k+1]=A·x[k]+B·u[k], multiplicador bilinear (DSP48E1, 42×42), **Q14.28**,
  timer de passo (26 ciclos @200 MHz = 130 ns), programação de coeficientes
  A/B, saídas Iαβ / ψαβ / ω_m.
- **Caixa-preta:** tudo fora (só V_abc entra, estado sai).
- **Legenda:** "Núcleo numérico: discretização bilinear em ponto fixo Q14.28,
  passo de 130 ns."
- **Nota de implementação:** confirmar a estrutura interna real em
  `src/rtl/TIM_Solver.vhd` (presença/forma da transformada de Clarke, organização
  do datapath bilinear) antes de desenhar.

### 03 — PS / daemon (`src/ps_app`)
- **Possui:** máquina de estados (idle/run/pause/stop), controle V/F na ISR por
  carrier_tick, escrita AXI-Lite (refs + coeficientes), driver DMA (S2MM, burst
  128 frames ≈1,28 ms), empacotamento UDP, eventos PWM; os **dois regimes
  temporais**.
- **Caixa-preta:** PL (caixa HIL_AXI_Top), gateway.
- **Legenda:** "Daemon de controle e telemetria no PS: malha V/F por interrupção
  (1 kHz) e exfiltração por DMA (~100 kHz)."

### 04 — Backend / gateway Go (`apps/hil-go`)
- **Possui:** ingestão UDP, ring lock-free, derive (modelo do motor → Tₑ/abc),
  pirâmide de tiles (decimação de display, min/max), sessão + captura `.hilbin`,
  API HTTP/SSE.
- **Caixa-preta:** placa (EBAZ4205), frontend.
- **Legenda:** "Gateway no host: ingestão da telemetria e pirâmide
  multirresolução."

### 05 — Frontend (`apps/hil-go/frontend`)
- **Possui:** main.ts (orquestrador), tiles + cache, viewport (zoom/pan), render
  scheduler, uPlot.
- **Caixa-preta:** gateway.
- **Legenda:** "Visualização: navegação por zoom sobre tiles e renderização
  incremental."

## Plano de arquivos

Renumeração (de 5 para 6 figuras):

| Atual | Novo | Ação |
|---|---|---|
| `00-system.d2` | `00-system.d2` | Reduzir a contexto puro: subsistemas viram caixa-preta; manter só a cadeia de taxas global + domínios. |
| `01-solver.d2` | `01-fpga-top.d2` | Refocar em HIL_AXI_Top; TIM_Solver vira caixa-preta. |
| — | `02-solver.d2` | **Novo:** interior do TIM_Solver (após ler o RTL). |
| `02-ps-daemon.d2` | `03-ps-daemon.d2` | Renumerar; manter foco nos dois regimes. |
| `03-backend.d2` | `04-backend.d2` | Renumerar; remover detalhes de borda redundantes. |
| `04-frontend.d2` | `05-frontend.d2` | Renumerar. |

`build.sh` continua varrendo `*.d2`. Atualizar a tabela de níveis no
`README.md` para refletir as 6 figuras e a regra de fronteira.

## Estilo (já definido, não muda)

Monocromático, ELK ortogonal, paisagem; convenções na tabela do
`docs/diagrams/README.md` (cinza = domínio 200 MHz; tracejado fino = CDC; seta
tracejada = controle/IRQ; rótulo de seta = taxa).

## Critério de pronto

- 6 `.d2` + PNG/SVG renderizados em `docs/diagrams/img/`.
- Nenhum bloco interno aparece detalhado em mais de uma figura.
- Cada conceito transversal detalhado só no seu dono.
- `README.md` lista as 6 figuras com sua "ideia" e a regra de fronteira.
