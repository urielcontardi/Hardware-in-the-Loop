# Simplificação da Matriz Experimental — Limitação do V/f em Malha Aberta

## Achado

Investigação disparada por uma inspeção visual da figura `HIL_GrupoA03_A7_CorrenteFluxoVelocidade.pdf`: a velocidade mecânica do caso `A7` cai monotonicamente até valores muito além da síncrona (~-451 rad/s contra uma síncrona de 188,5 rad/s), o que não é fisicamente plausível para uma partida V/f sob carga.

Checado o `ref_speed` (saída do próprio modelo C de referência, não o VHDL) em todos os casos do Grupo A a partir dos CSVs de `verification/results/2026-07-04_campaign_03/`:

| Caso | rampa / carga | velocidade final (rad/s) |
|---|---|---|
| A1 | 0,5s / 0 T_n | +185,8 |
| A2 | 0,5s / 1,0 T_n | -17,3 |
| A3 | 1,0s / 0,5 T_n | +186,0 |
| A4 | 2,0s / 1,0 T_n | -363,0 |
| A5 | 5,0s / 0 T_n | +188,2 |
| A6 | 5,0s / 1,0 T_n | -1.239,0 |
| A7 | 2,0s / 1,1 T_n | -451,5 |

Casos sem carga ou com carga leve (A1, A3, A5) convergem corretamente perto da síncrona. Casos com carga ≥1,0 T_n (A2, A4, A6, A7) divergem para velocidade negativa, tanto pior quanto mais longa a rampa.

Investigação de causa raiz (`IM_Model.c`, `verification/cocotb/tests/test_top_hil.py`, `verification/cocotb/models/vf_control.py`) confirmou: **não é bug do modelo nem do VHDL**. A equação de movimento (`dwm = (Te - Tload)/J`, `IM_Model.c:308`) está correta e idêntica em todas as variantes do modelo. A causa é metodológica: a carga é aplicada em valor cheio desde `t=0` (motor parado), enquanto a lei de comando V/f é estritamente proporcional ao tempo decorrido (`vf_control.py`, `test_top_hil.py:489-501`), sem reforço de tensão em baixa frequência nem compensação de escorregamento. Em `t≈0`, tensão/frequência ~0 → torque disponível ~0, mas a carga já se opõe em valor pleno; a velocidade cai abaixo de zero quase imediatamente, e como a frequência do estator não depende da velocidade real do rotor, o escorregamento efetivo explode e a máquina fica presa na região de torque colapsado pelo resto da rampa — sem nunca se recuperar. Rampas mais longas (2s, 5s) acumulam mais tempo nesse regime deficiente, daí a divergência crescer com `t_acc`.

O mesmo mecanismo explica a divergência já registrada para `B3` (carga inicial de `0,75 T_n` sustentada desde o início da rampa, antes mesmo do degrau) — não são dois problemas, é o mesmo limite físico do V/f em malha aberta sem boost/compensação de escorregamento, conhecido na literatura de acionamentos escalares.

## Decisão

Reduzir a matriz experimental de L2/L3 aos casos que são válidos sob essa lei de comando (carga nula ou leve, `≤0,5 T_n` no início da rampa):

- **Grupo A**: mantém A1, A3, A5. Remove A2, A4, A6, A7.
- **Grupo B**: mantém B1, B2. Remove B3.
- **Grupo C**: nunca executado; reenquadrado como candidato de exploração em L4, não mais um item pendente de L2/L3.

A diversidade de cenários mais ampla (cargas elevadas, degraus adicionais, condições do Grupo C) fica reservada à validação em L4, quando a plataforma roda em tempo real no hardware — sem o custo de cossimulação RTL (~5.900×-6.100× no L2, ~11.800×-12.000× no L3, `sec:resultados-custo-computacional`) e, presumivelmente, com uma malha de controle capaz de sustentar carga desde o repouso (o que está fora do escopo deste ajuste — não se está corrigindo o V/f, apenas reconhecendo seu limite conhecido e restringindo o que é reportado a cenários onde ele é válido).

## Escopo do ajuste

- **Capítulo 3** (`3-MateriaisMetodos.tex`): tabelas `quad:grupo-a` e `quad:grupo-b` reduzidas; parágrafo novo explicando a restrição a carga leve/nula e o adiamento da diversidade de cenários para L4; Grupo C reenquadrado como candidato L4 em vez de pendência L2/L3.
- **Capítulo 4** (`4-Resultados.tex`): seção Grupo A reescrita (A5 substitui A7 como segundo caso ilustrado; tabela de métricas cai para 3 linhas; parágrafos de síntese que comparavam níveis de carga reescritos); seção Grupo B reduzida (tira B3 e a subseção de achado metodológico dedicada, fundida numa frase); tabela de custo computacional cai de 20 para 10 linhas; fechamento do capítulo atualizado.
- **Diagrama** `docs/diagrams/06-validation-groups.d2`: Grupo A "3/3", Grupo B "2/2", Grupo C removido como caixa própria (absorvido pela caixa L4).
- **Scripts** (`verification/cocotb/scripts/chapter_common.py`, `Mestrado_latex/Mestrado/scripts/gerar_figuras_resultados_hil.py`): `GRUPO_A_IDS`/`GRUPO_B_IDS`/`CASES`/`CASES_B` filtrados para os casos sobreviventes, para que uma regeneração futura não reintroduza A2/A4/A6/A7/B3 sem querer.

## Fora de escopo

- Corrigir o V/f (adicionar boost de tensão em baixa frequência ou compensação de escorregamento) — isso resolveria a divergência e permitiria reincluir os casos de carga elevada, mas é trabalho de modelagem/controle, não de redação ou geração de figuras. Fica registrado como possível trabalho futuro, não implementado aqui.
- Reexecutar A2/A4/A6/A7/B3 sob uma lei de comando corrigida.
- Qualquer mudança em `IM_Model.c` ou no equacionamento do motor — confirmado correto, não é o alvo do ajuste.
