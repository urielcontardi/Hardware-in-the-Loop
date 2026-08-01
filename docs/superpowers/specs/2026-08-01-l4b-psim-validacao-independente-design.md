# L4-B — Validação Independente em PSIM (FPGA real vs. PSIM completo)

## Contexto

Nesta e em sessões anteriores, foi construída uma comparação nova entre a
telemetria real da FPGA (campanha `2026-07-25_campaign_l4_final` — link
simbólico pra `2026-07-25_l4_repeat/r1`, mesmo nome que o resto do pipeline
de figuras já usa como campanha "oficial", 6 casos) e uma reprodução
**completa e independente** da cadeia V/f + portadora + NPC + motor, feita
inteiramente dentro do PSIM (bloco de motor de indução nativo,
`Iu/Iv/Iw/motorSpeed` — nunca o modelo C/DLL embutido no mesmo schematic, que
foi descartado por mostrar comportamento numérico irrelevante pra esse
objetivo). Os dados já foram mesclados em
`verification/results/2026-07-25_campaign_l4_final/<Caso>_l4/l4_pwm_replay/capture/{partida,regime}.npz`
(campos `psim_*` adicionados aos `fpga_*`/`cmod_*` já existentes, ver
`verification/cocotb/scripts/psim_csv_to_npz.py`).

O usuário quer usar essa comparação na dissertação. Esta spec define como.

## Decisão 1 — Enquadramento: nova categoria "L4-B"

Essa comparação **não isola fonte de erro** (mistura modelo do motor, lei
V/f, modulador, método numérico, tudo de uma vez) — é estruturalmente
diferente de L1-L4, que isolam uma fonte por nível. Ela serve como
**corroboração independente**: duas implementações completamente separadas
(C/VHDL do projeto vs. PSIM comercial, motor nativo) convergindo pra
resultados parecidos contra a FPGA real é evidência mais persuasiva de que o
comportamento observado não é artefato de uma implementação específica.

Investigação prévia mostrou que **"L4-B" não existe ainda em lugar nenhum do
texto da dissertação** (só existe como conceito de planejamento em
`docs/experimental-validation-plan.md`, dentro do repo HIL, nunca escrito no
Cap. 3/4). Decisão: criar a categoria do zero, com o PSIM como único exemplo
escrito — **não** tentar reconstruir retroativamente o mock em C
(`hil_fullstack_mock.py`) contra capturas reais, que nunca foi formalizado.

Nome adotado: **L4-B**, mantendo a convenção L1-L4 já usada.

## Decisão 2 — Escopo de dados

6 casos, mesma matriz reduzida de sempre: **S0, A1, A3, A5, B1, B2**. Só o
ramo do motor PSIM nativo (`Iu/Iv/Iw/motorSpeed`) em todos.

**Não incluir**: o episódio em que o B1 pareceu travar em ~94 rad/s — foi
erro de ferramenta (mostrei a branch errada do modelo C/DLL por engano), não
um achado real sobre o sistema. O motor nativo nunca travou. Não deve
aparecer na dissertação de forma alguma, nem como nota de rodapé.

## Decisão 3 — Mudanças no Cap. 3 (`3-MateriaisMetodos.tex`)

Nova subseção, próxima de `quad:cadeia-validacao`, definindo L4-B:

1. O que é: reprodução completa e independente da cadeia V/f + portadora +
   NPC + motor no PSIM, comparada direto contra telemetria real da FPGA.
2. Por que existe: robustez adicional via segunda implementação
   independente — não confirma que o C/VHDL do projeto está certo por si só,
   confirma que o comportamento não é artefato de uma implementação
   específica.
3. Ressalva metodológica explícita (parafraseando o espírito já usado na
   dissertação para o L4-B/full-stack no `experimental-validation-plan.md`):
   ao contrário de L1-L4, essa comparação não isola fonte de erro; qualquer
   divergência pode vir de qualquer camada, misturada.
4. Nota técnica: a lei V/f do PSIM (`v_pu = K·f`, proporcional pura, sem
   boost) é **idêntica** à do firmware real
   (`src/ps_app/vf_ctrl.c:109`, comentário explícito "no boost") — a lei de
   controle não é uma variável neste experimento, reforça a comparação.
5. Adiciona linha `L4-B` na tabela `quad:cadeia-validacao`.
6. Não cria tabela de parâmetros nova — referencia a tabela de parâmetros do
   motor já existente no Cap. 3 (mesmos valores, incluindo `Vdc=1240V`).

## Decisão 4 — Mudanças no Cap. 4 (`4-Resultados.tex`)

Nova seção **"Validação L4-B: Reprodução Independente em PSIM"**, depois da
seção L4 (Grupo A/B) já existente.

**Por caso** (S0, A1, A3, A5, B1, B2), mesmo padrão visual do L4 já
estabelecido:

- 1 figura **Overview**: janela completa, correntes de fase `a/b/c` (Clarke
  inversa aplicada aos dados `fpga_ia/fpga_ib`; o PSIM já é nativamente
  trifásico, não precisa converter), velocidade, regiões de partida/regime
  sombreadas (mesmo padrão de `axvspan` do `l4_figures.py`).
- 2 figuras **Overlay** (partida + regime): zoom em cada janela, correntes
  de fase sobrepostas PSIM×FPGA (estilo DUT-vs-referência já usado:
  linha sólida grossa semi-transparente vs. tracejada fina).
- **Sem painel de fluxo** — texto explica que o motor nativo do PSIM não
  expõe fluxo do rotor como grandeza acessível (limitação da ferramenta, não
  do experimento).
- Tabela de métricas (NRMSE/erro por caso), mesmo estilo de `tab:l4-metricas`.

**Explicação de divergência** (única relevante encontrada): caso A3, janela
de partida — mergulho de velocidade breve (~-7 rad/s) nos primeiros ~0,15s,
presente na FPGA, ausente no PSIM (que fica em ~0 até começar a subir).
Explicado como manifestação leve do mesmo limite do V/f sem boost/compensação
de escorregamento já documentado no Cap. 3 (carga aplicada desde o início da
rampa) — mesma família de causa que motivou reduzir a matriz A/B
originalmente, aqui aparecendo de forma suave (o motor se recupera rápido,
não trava) em vez de divergente.

**Aside sobre método de integração**: um parágrafo curto, escopo explícito
**só no caso S0** (não testado sistematicamente nos outros 5), relatando que
alternar entre "Backward Euler" e "Trapezoidal" no PSIM não mudou nenhum
resultado — e explicando o porquê: o campo alterado ficava na aba SPICE do
Simulation Control, sem efeito na engine nativa de fato usada para rodar
essas simulações (confirmado pelo usuário). Enquadrar como teste pontual de
sanidade, não como estudo sistemático de robustez numérica.

## Decisão 5 — Pipeline técnico (script de figuras)

Novo script `verification/cocotb/scripts/l4b_figures.py`, espelhando
`l4_figures.py`:

- **Entrada**: os `.npz` já mesclados em
  `verification/results/2026-07-25_campaign_l4_final/<Caso>_l4/l4_pwm_replay/capture/{partida,regime}.npz`
  (campos `fpga_*`/`psim_*`; ignora `cmod_*`).
- **Estilo visual**: reaproveita `l2_figures.py` (`eng`) — paleta Okabe-Ito,
  `figure.dpi=120`, DUT (PSIM) em linha sólida grossa semi-transparente,
  referência (FPGA) tracejada fina, salva `.pdf`+`.png` via `save_fig()`.
- **Conversão de eixo**: aplica Clarke inversa (`inverse_clarke`, já usada em
  `results_explorer_app.py::_load_full_capture`) nos dados `fpga_ia/fpga_ib`
  pra obter `ia/ib/ic` de fase; os dados `psim_*` já são fase nativa
  (`Iu/Iv/Iw`), sem transformação.
- **Métricas**: calculadas direto dos dados mesclados nesta pipeline (NRMSE
  por fase/velocidade) — não reaproveita os números de correlação
  calculados ad-hoc durante a sessão de brainstorming/exploração.
- **Saída**:
  `docs/results-chapter/figures/l4b/HIL_L4B_<Caso>_Overview.{pdf,png}`,
  `HIL_L4B_<Caso>_Partida_Overlay.{pdf,png}`,
  `HIL_L4B_<Caso>_Regime_Overlay.{pdf,png}`, mais
  `docs/results-chapter/tables/l4b_metricas.tex`.
- **Pós-processamento manual** (fora do script): copiar os PDFs gerados pra
  `Mestrado_latex/Mestrado/figuras/`, mesmo fluxo manual já usado pros outros
  níveis (L2/L3/L4).

## Fora de escopo (explicitamente, não fazer)

- Reconstruir/formalizar o mock em C (`hil_fullstack_mock.py`) contra
  capturas reais da FPGA como parte deste trabalho.
- Corrigir os gaps já conhecidos e documentados da seção L1 existente
  (`fig:PSIM_Results2` duplicada por falta de `simPWM02/03.txt`,
  eixos sem unidade em 4 figuras de zoom) — problema pré-existente, não
  relacionado a L4-B.
- Mencionar o episódio do B1 "travando" (erro de ferramenta, não achado
  real) em qualquer lugar do texto.
- Testar sistematicamente o método de integração (Backward Euler vs.
  Trapezoidal) nos outros 5 casos além do S0.
- Adicionar painel de fluxo às figuras L4-B (motor nativo do PSIM não expõe
  essa grandeza).

## Próximos passos após esta spec

1. Escrever `l4b_figures.py`, gerar as figuras/tabela dos 6 casos.
2. Escrever a subseção nova do Cap. 3 (definição de L4-B).
3. Escrever a seção nova do Cap. 4 (resultados L4-B, por caso, incluindo o
   aside do método de integração).
4. Copiar as figuras geradas pra `Mestrado_latex/Mestrado/figuras/`.
