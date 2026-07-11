# Capítulo de Resultados — Texto do Grupo B, Custo Computacional e Clareza Metodológica

## Contexto

Os specs anteriores (2026-07-07 e 2026-07-11) cobriram dados/tabelas/figuras.
Este cobre a **redação** em `Mestrado_latex/Mestrado/chapters/`, usando esse
material já pronto. Não é um projeto de software — é conteúdo de dissertação;
por isso não segue o formato de plano TDD, e a "implementação" é a redação
direta dos arquivos `.tex`.

## Auditoria de procedência (feita antes deste spec)

Confirmado por investigação direta (não por suposição):
- `extras/induction-motor-model/psim/1_modelValidation/paramSim.txt` (fonte do
  L1) tem `Rs=0,4396`/`J=0,4` desde o primeiro commit (2025-05-27, submódulo
  `Induction-Motor-Model`), nunca mudou — as figuras L1 já existentes na
  dissertação (Figura 4.2/4.3/4.5) não usam parâmetros errados.
- Nenhuma referência a `campaign_01`/`campaign_02` ou aos parâmetros errados
  (`Rs=0,435`/`J=0,192`, introduzidos só no `HIL_AXI_Top.vhd` e corrigidos no
  commit `e0e6907`) existe em nenhum capítulo atual.
- Todo o conteúdo novo deste spec vem exclusivamente de
  `verification/results/2026-07-04_campaign_03/`.

## Achado: B3 não atende à precondição de regime do próprio Capítulo 3

`3-MateriaisMetodos.tex` (§ Perturbações de Carga) já exige que "a perturbação
[só] deve ser aplicada... após a velocidade atingir uma faixa estacionária
(±2% por 500ms)". Medido em `campaign_03/B3_step075_to025/.../metrics.json`,
campo `transient`: velocidade antes do degrau é `51,19 rad/s` (VHDL) e
`78,25 rad/s` (C/C++) — ambas longe da síncrona (188,5 rad/s) e divergentes
entre si — contra `~186-187 rad/s` em B1 e B2. Ou seja: com `0,75 T_n` de carga
sustentada e a mesma rampa V/f usada nos demais casos, o motor não atinge
regime antes do instante fixo do degrau (`t=0,6s`); a precondição do próprio
Capítulo 3 não foi respeitada nesta execução. B3 continua sendo um ensaio
válido e definido na matriz (`quad:grupo-b`); esta rodada específica é que não
serve como medição B1/B2-comparável.

## 1. Clareza metodológica (Níveis × Grupos)

**Texto**, `3-MateriaisMetodos.tex`, imediatamente antes de
`\subsubsection{Partida e Aceleração}` (dentro de `sec:matriz-cenarios-hil`):
parágrafo curto (~80-120 palavras) explicitando que L1-L4
(`quad:cadeia-validacao`) e os Grupos A/B/C (`quad:grupo-a`/`quad:grupo-b`/
`quad:grupo-c`) são eixos ortogonais — nível = contra qual referência
(fidelidade de implementação); grupo = qual situação do motor (cenário de
operação) — e que cada grupo é validado, na medida do possível, em cada nível
aplicável (L1 é validação global do modelo numérico, anterior e independente
da definição dos grupos).

**Diagrama**, `docs/diagrams/06-validation-groups.d2` (repo HIL, atualiza o
existente, não cria novo): adiciona a caixa do Grupo C (`pending`, "planejado,
não iniciado"), corrige o status do Grupo B (era "código pronto, não
executado"; passa a "L2/L3 completos em B1/B2; B3 pendente de reexecução —
precondição de regime não atendida"), anota status L2/L3 por caixa (ex.:
Grupo A: "L2: 7/7 ✓  L3: 7/7 ✓"). Sem cor, mesma convenção monocromática
(`box`/`pending`). Regenerar com `./build.sh` e atualizar
`docs/diagrams/README.md` (linha já existente da tabela, só o texto da
coluna "Mostra").

## 2. Seção Grupo B (nova, em `4-Resultados.tex`)

Inserida depois da seção do Grupo A, no lugar onde hoje está a subseção
"Situação Atual e Continuidade Experimental" (que se move para o fim do
capítulo, ver item 4). Estrutura, espelhando o Grupo A:

1. **Introdução** — objetivo (validar resposta a degrau de carga em regime,
   critério mais direto de qualidade de um simulador HIL, remete a
   `subsec:grupo-b-perturbacao`), casos B1/B2/B3, fonte `campaign_03`.
2. **Matriz de Ensaios** — tabela `parametros_grupo_b.tex` (carga inicial/
   final/sentido, os 3 casos), texto explicando que a magnitude do degrau é
   igual nos três (0,5 T_n), variando o patamar de partida e o sentido.
3. **Comparação Temporal** — **B1 e B2** detalhados (forma de onda completa +
   zoom no degrau + três fases), com as figuras já geradas
   (`HIL_GrupoB_B1/B2_CorrenteFluxoVelocidade.pdf`,
   `HIL_GrupoB_B1/B2_ZoomDegrau.pdf`, `HIL_GrupoB_B1/B2_TresFases.pdf`).
4. **Métricas Globais** — tabela `metricas_grupo_b.tex` (NRMSE/MAE, os 3
   casos) e `transiente_grupo_b.tex` (desvio de pico/tempo de recuperação).
   B3 aparece nas duas tabelas (dado real, não escondido), mas o texto
   explica a ressalva antes de qualquer conclusão numérica sobre ele.
5. **Achado Metodológico: Precondição de Regime Não Atendida (B3)** — usa a
   tabela de velocidade-antes-do-degrau (B1/B2 ~186-187 rad/s vs B3 51/78
   rad/s) como evidência, remete à exigência já escrita em
   `subsec:grupo-b-perturbacao`, conclui que a combinação carga
   `0,75 T_n` + rampa V/f não dá tempo de acomodação suficiente, e registra
   como reexecução pendente (rampa mais longa ou verificação explícita da
   condição de regime antes de disparar o degrau).
6. **Síntese** — B1/B2 confirmam a mesma consistência L2≈L3 já vista no
   Grupo A (nenhum erro dominante introduzido pela cadeia integrada); B3 não
   entra nessa conclusão.

Todas as figuras/tabelas já existem em disco
(`docs/results-chapter/tables/`, `Mestrado/figuras/`) — este item é só
redação, sem gerar nada novo.

## 3. Seção Custo Computacional (nova, em `4-Resultados.tex`)

Logo após a seção do Grupo B. Tabela `tempo_simulacao.tex` (todos os casos
A1-A7/B1-B3, L2 e L3) + figura `HIL_CustoComputacional.pdf`. Argumento
central (números já confirmados ao gerar a figura): a cossimulação RTL usada
para verificação roda entre `~5.800×` e `~6.100×` (L2) e `~11.800×` e
`~12.500×` (L3) mais devagar que o tempo real do motor simulado — ou seja,
simular alguns segundos de operação do motor custa horas de tempo de parede.
Esse é o argumento direto para a necessidade do L4 (execução em FPGA real):
verificação por cossimulação é adequada para validar corretude, mas inviável
para qualquer uso em tempo real.

## 4. Fechamento do capítulo (move + atualiza)

A subseção "Situação Atual e Continuidade Experimental" (hoje ao final da
seção do Grupo A) se torna a última subseção do capítulo inteiro (depois de
Custo Computacional), com o texto atualizado: Grupo A completo (L2/L3, 7/7);
Grupo B completo em L2/L3 para B1/B2, B3 pendente de reexecução (precondição
de regime); Grupo C planejado, não iniciado; L4 pendente para todos os
grupos. Mantém a ressalva já existente sobre a normalização de NRMSE
divergente entre L2/L3 (RMS) e diagnósticos L4 anteriores (pico-a-pico).

## Fora de escopo

- Rodar Grupo C ou L4 — permanecem como trabalho futuro, já cobertos pelo
  texto atualizado do item 4.
- Reexecutar B3 — fica registrado como pendente, não resolvido aqui.
- Atualizar Resumo/Abstract ou Conclusão (Cap. 5) com os números do Grupo B —
  já são conhecidos como pendentes no `docs/PLANO_ESCRITA.md`, mas esse
  documento em si está desatualizado (não reflete o trabalho desta sessão) e
  não é atualizado por este spec.
