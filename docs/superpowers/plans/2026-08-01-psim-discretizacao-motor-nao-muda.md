# PSIM — por que o método de integração não muda o motor (S0: backeuler vs trapezoidal idênticos)

## Achado empírico (confirmado nesta sessão, com dados reais)

Durante a reprodução do caso S0 no PSIM (`extras/induction-motor-model/psim/2_pwmModelValidation/`),
foram geradas duas exportações do mesmo caso, uma com "Backward Euler" e outra
com "Trapezoidal" selecionados em algum lugar do PSIM
(`data/S0/S0_1us_backeuler.csv` vs `data/S0/S0_1us_trapezoidal.csv`).

Comparação ponto a ponto em 4 instantes ao longo de toda a simulação (t=0,02s /
0,15s / 1,0s / 3,0s), em todas as 11 colunas (`Iu,Iv,Iw,motorSpeed,IuSim1,
IvSim1,IwSim1,Wr1,Wmec1,motorSpeedSim`): **valores idênticos, dígito por
dígito**, em 100% dos pontos checados. Isso vale tanto para o motor PSIM
nativo (`Iu/Iv/Iw/motorSpeed`) quanto para o modelo C dentro do PSIM
(`IuSim1/IvSim1/IwSim1/Wmec1`).

Igualdade *exata* de todos os dígitos impressos ao longo de toda a simulação é
mais forte que "convergência numérica" — dois métodos de ordem diferente
(Backward Euler é 1ª ordem, Trapezoidal é 2ª ordem) convergem quando o passo é
pequeno, mas normalmente não ficam bit-a-bit iguais. O mais provável é que a
opção alterada nunca chegou a influenciar os sinais medidos.

## Duas explicações para o mecanismo — nenhuma verificada de forma independente ainda

### Explicação 1 (Claude,राciocínio desta sessão, não confirmado na UI do PSIM)

O bloco DLL (`IM_Model.c`, chamado via `simuser()`/`plecsOutput()`) faz sua
**própria integração interna fixa em C** a cada passo — por exemplo,
`MODEL_B2` usa Euler explícito simples (`x_novo = x_velho + dx*Ts`). Isso é
uma função externa chamada pelo PSIM como "caixa preta"; o solver geral de
circuito do PSIM (que resolve R/L/C e chaves via companion-model) nunca toca
essa matemática interna. O bloco de motor nativo do PSIM provavelmente segue
o mesmo padrão (blocos de máquina costumam ser resolvidos por equação própria
a cada passo, não pelo sistema geral de RLC).

### Explicação 2 (Gemini, colada pelo usuário, **não verificada por mim contra o PSIM real**)

> Segundo o Gemini, o campo "Integration Method" (Backward Euler / Trapezoidal)
> que foi alterado estava na **aba SPICE** do Simulation Control, não na aba
> nativa do PSIM. Essa configuração só teria efeito ao rodar via
> "Run > Run SPICE Simulation" — o botão padrão "Run Simulation" (engine
> nativa do PSIM) ignoraria completamente esse campo. No solver nativo, o
> circuito de potência (onde o motor está) usaria um método de integração
> fixo e embutido no PSIM (historicamente baseado em Trapezoidal), independente
> de qualquer coisa configurada na aba SPICE.
>
> Ponto arquitetural mais amplo levantado pelo Gemini: no PSIM, a separação é
> entre **circuito de potência** (motor, inversor — sempre resolvido como
> sistema contínuo pelo solver nativo) e **circuito de controle** (onde
> conversores s→z e filtros discretos de fato respeitam o método de
> discretização escolhido). Pra forçar o motor a rodar sob uma discretização
> específica e controlada, a sugestão foi **não usar o bloco gráfico de
> motor**, e sim implementar o modelo em espaço de estados já discretizado
> dentro de um C-Block/Simplified C-Block, com as equações de diferença
> escritas à mão (matrizes `A_d`, `B_d` calculadas offline com o método
> desejado).

## Por que isso importa pro texto da dissertação

Se a explicação 2 estiver correta, o "achado" não é sobre robustez numérica
do motor (que é como a explicação 1, sozinha, poderia ser lida) — é que o
teste comparou algo que nunca poderia ter dado diferente, porque a
configuração alterada não pertencia ao motor de simulação que rodou. As duas
explicações não são mutuamente exclusivas: mesmo rodando pela engine nativa
(sem tocar em nada de SPICE), a explicação 1 ainda prediz o mesmo resultado
(DLL e motor nativo são caixas-pretas imunes ao solver geral). Então o
resultado idêntico é consistente com qualquer uma das duas, ou as duas juntas
— não dá pra distinguir só com os dados que temos.

**Conexão direta com o projeto**: o próprio `IM_Model.c` já tem 5 variantes
(`MODEL_A, MODEL_B, MODEL_B2, MODEL_C, MODEL_D`, `IM_Model.h:55-61`) —
plausivelmente formulações/discretizações diferentes implementadas como
equações de diferença explícitas, exatamente o padrão que o Gemini descreveu
como "a forma certa" de testar discretização dentro do PSIM. Isso já existe;
só falta confirmar se essas variantes correspondem de fato a métodos de
integração diferentes (Euler forward/backward, bilinear/Tustin) e comparar
`Model=0..4` entre si — não o "Solver Type"/"Integration Method" do PSIM.

## Pendências antes de usar qualquer uma dessas afirmações no texto final

1. **Verificar na UI do PSIM**: onde exatamente ficam os dois campos
   "Backward Euler"/"Trapezoidal" que geraram os dois CSVs — aba SPICE (como
   o Gemini afirma) ou algum outro lugar? Confirmar qual botão de "Run" foi
   usado pra gerar cada exportação.
2. **Se a explicação 2 se confirmar**: refazer o teste de fato pela aba
   nativa do PSIM (se ela expuser algum controle de integração pro motor —
   provavelmente não expõe, dado o argumento arquitetural do Gemini) ou migrar
   pro caminho do C-Block/estado discretizado, se o objetivo for realmente
   comparar métodos de integração do motor dentro do PSIM.
3. **Comparar `Model=0..4` da DLL entre si** (não o solver do PSIM) — esse é
   o teste que efetivamente muda a discretização usada, já validado como
   correto nesta sessão.
4. Nenhuma afirmação deste arquivo deve entrar no texto da dissertação sem
   essa confirmação — o conteúdo do Gemini é reproduzido aqui como pista de
   investigação, não como fato estabelecido.
