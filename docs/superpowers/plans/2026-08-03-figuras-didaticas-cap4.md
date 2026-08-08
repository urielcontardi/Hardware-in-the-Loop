# Plano — Figuras didáticas e orientadas à evidência para o Capítulo 4

## Objetivo

Substituir gráficos genéricos e visualmente densos por figuras que respondam,
cada uma, a uma pergunta científica explícita. A prioridade é permitir que o
leitor identifique rapidamente o estímulo, a resposta, a concordância entre
implementações e a métrica que sustenta a conclusão do texto.

## Princípios editoriais

1. Uma figura deve defender uma afirmação principal.
2. A janela temporal deve ser derivada do evento físico (`t_acc`, `t_step`) e
   da frequência fundamental, nunca da duração bruta da captura.
3. Regime permanente deve ocupar no máximo seis ciclos, salvo análise espectral.
4. Transitórios longos usam envelopes (RMS móvel) para corrente e sinais suaves
   em escala integral; formas de onda instantâneas ficam em janelas curtas.
5. Comparações entre casos da mesma família usam dimensões, cores, notação e
   limites compatíveis.
6. O estímulo deve estar visível: fim da rampa ou degrau de carga marcado e
   identificado numericamente.
7. Métricas usadas no texto devem aparecer na figura quando ajudarem a leitura.
8. Títulos internos redundantes são removidos; a legenda LaTeX descreve o caso.
9. Subamostragem de sinais com ripple deve preservar extremos por bloco, evitando
   alias visual produzido por amostragem uniforme simples.

## Famílias de figuras

### Partida e aceleração — S0, A1, A3, A5

Pergunta: a implementação reproduz a dinâmica eletromecânica durante a rampa?

- velocidade mecânica FPGA/referência;
- envelope RMS de uma fase de corrente;
- erro de velocidade com MAE anotado;
- linha vertical no fim da rampa;
- janela: `0 .. t_acc + acomodação curta`.

O caso A3 deve evidenciar o mergulho inicial de velocidade. O caso A5 mostra a
rampa completa, mas não milhares de ciclos instantâneos de corrente.

### Degrau de carga — B1, B2

Pergunta: a resposta transitória ao degrau é reproduzida?

- uma corrente de fase, FPGA/referência;
- velocidade mecânica;
- perfil de carga em N.m;
- linha vertical em `t_step`;
- janela: aproximadamente `t_step ± 150 ms`.

### Regime

Pergunta: forma, amplitude e erro permanecem próximos após a acomodação?

- uma fase representativa durante quatro a seis ciclos;
- resíduo em painel alinhado;
- amplitude/NRMSE ou MAE anotado;
- mesma escala para casos comparáveis.

### Síntese

Pergunta: quais casos são mais difíceis e como L2/L3/L4/L4B se comparam?

- pequenos múltiplos ou barras com intervalos comparáveis;
- evitar repetir formas de onda quando uma tabela ou gráfico de métricas comunica
  melhor a conclusão.

## Implementação

1. Criar `verification/cocotb/scripts/publication_figures.py`.
2. Reutilizar apenas carregadores e métricas existentes; a composição gráfica é
   específica para publicação.
3. Implementar inicialmente as seis figuras L4B orientadas à evidência.
4. Adicionar testes para janelas, presença do evento e nomes de saída.
5. Estender o mesmo padrão ao L4 (FPGA versus modelo C), incluindo fluxo.
6. Substituir no LaTeX somente após inspeção visual dos PNGs.
7. Compilar/revisar paginação e então sincronizar com o Overleaf.

## Critérios de aceite

- nenhuma figura de regime com mais de seis ciclos sem justificativa;
- B1/B2 sempre mostram o degrau aplicado;
- A3 torna visível o mergulho inicial;
- A5 não desenha milhares de ciclos instantâneos em toda a rampa;
- fontes permanecem legíveis na largura usada no LaTeX;
- legenda LaTeX fica acima da imagem e não repete título interno;
- métricas não mudam quando a janela de exibição muda;
- testes existentes continuam passando.
