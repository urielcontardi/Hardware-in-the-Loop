# Navegação fluida por pirâmide LOD com tiles

Data: 2026-06-20
Branch: feat/dma-telemetria
Status: aprovado para planejamento

## Objetivo

Entregar uma experiência de navegação (zoom e pan no eixo temporal) sem lag, sem
costura visual e sem flicker, tanto na sessão ao vivo quanto em runs salvos
(`.hilbin`). A meta é zoom/pan contínuo sobre uma sessão de até 30 min sem atraso
perceptível, sem mudança de caráter do traço ao cruzar fronteiras de dados, e sem
saltos ou regiões em branco durante a interação.

## Motivação (estado atual)

Hoje os dados vivem em três cópias no backend e três no front, e o render alterna
entre dois caminhos com algoritmos de redução diferentes. Isso causa três defeitos:

1. **Lag.** `handleSeries` relê do disco todas as amostras full-rate da janela
   (`store.ReadWindow`) e só então faz min/max, a cada movimento de pan. Zoom-out
   de minutos lê milhões de amostras por interação.
2. **Costura.** O render escolhe entre `decimateAndProject` (decimação client-side
   sobre o tail vivo) e `seriesToProjected` (envelope min/max do servidor). São
   densidades e estatísticas diferentes, então o traço muda de aparência ao cruzar
   `hiResStart`.
3. **Flicker.** `/api/series` é assíncrono e disparado de dois lugares; o
   `ViewportController` só descarta por `seq`, não confere se a janela que voltou
   bate com a renderizada, então a vista "pula" durante o pan.

Existe um pacote `internal/overview` que agrega min/max em buckets de 50 ms para a
sessão inteira, projetado exatamente para responder zoom-out em O(pixels), mas
nenhum handler o consulta. Ele é alimentado e ignorado.

## Abordagem escolhida

Servidor de tiles multi-resolução no backend (pirâmide de níveis de detalhe),
endereçado por tiles imutáveis e cacheáveis, alimentando um único caminho de
render no front. O `overview` morto evolui para o coração do sistema.

Alternativas descartadas:
- **Pirâmide no frontend** (baixar tudo e agregar em JS): inviável em full-rate
  (ordem de GBs em memória) e perde fidelidade no zoom fundo.
- **Híbrido tiles grossos + fetch raw**: mantém um handoff entre duas fontes, ou
  seja, a costura que queremos eliminar.

## Arquitetura

```
Ingestão (receiver)                Consulta (pan/zoom)
   |                                  |
   v                                  v
[rawbuf RAM ~30s]              front: viewport [from,to,width]
[store disco full-rate]   ->    escolhe TIER (bucket ~ (to-from)/width)
   | Compute() por amostra            |
   v                                  v
[Piramide LOD]            <----  pede so os TILES que faltam
  T0 raw . T1 1ms . T2 20ms          (cache reusa vizinhos no pan)
  T3 500ms . T4 10s                   |
  bucket = min/max/mean (8 ch)        v
                               1 caminho de render: envelope + mean
```

### Tiers

Cada bucket guarda `min/max/mean` dos 8 canais **derivados** (Ia, Ib, Ic, FluxA,
FluxB, FluxC, Speed, Te), porque o envelope tem que ser do que é exibido, não dos
5 canais base gravados em disco. A derivação usa `derive.Motor.Compute`, igual ao
`overview` atual.

- **T0** raw, sem bucketização. Recentes do `rawbuf` (RAM), antigas do store ou do
  arquivo aberto. Servido pelo `/api/raw` existente (transporte por cursor).
- **T1** 1 ms, **T2** 20 ms, **T3** 500 ms, **T4** 10 s.

Cada tier acima de T1 é construído por agregação em cascata do tier de baixo: ao
fechar um bucket de Ti, promove-se para Ti+1 (min dos mins, max dos maxes, mean
ponderada por contagem). Custo O(número de tiers) por amostra, não O(n).

As granularidades são um ponto de partida e ficam parametrizadas pela taxa de
amostragem real (telemetria padrão ~10 kHz via `gpioFallbackHz`).

### Seleção de tier

O front calcula `secPerPx = (to - from) / width` e escolhe o maior tier cujo
bucket ainda entrega pelo menos 1 bucket por pixel. Quando `secPerPx` cai abaixo
do espaçamento entre amostras raw, usa T0. Resultado: resposta sempre O(pixels).

### Tiles imutáveis

Um tile é um bloco de N buckets de fronteira fixa (proposta: 1024 buckets/tile),
índice `floor(bucketIndex / 1024)`. Tiles completos são imutáveis e ganham
`Cache-Control: public, max-age=31536000, immutable` mais `ETag`. Apenas o tile da
ponta (ainda crescendo) é `no-store`. No pan, o front já tem os tiles vizinhos em
cache: reuso instantâneo, sem re-fetch, sem flicker.

### Vivo e salvos pelo mesmo caminho

A sessão ao vivo mantém a pirâmide incrementalmente na ingestão. Ao abrir um
`.hilbin`, o backend varre o arquivo uma vez (reusando o índice esparso do store)
e constrói os mesmos tiers em memória, com um indicador de carregando no front. O
front não distingue as duas origens.

Decisão: **rebuild em memória ao abrir, sem sidecar em disco** nesta fase. A dor
principal é a navegação ao vivo, não reabrir arquivos repetidamente. Um sidecar
`.hiltiles` para tornar o segundo open instantâneo fica registrado como otimização
futura (adiciona invalidação de cache, fora de escopo agora).

### Comportamento ao vivo

Navegar (zoom/pan) congela a vista no ponto observado (modelo osciloscópio). Um
botão "Voltar ao vivo" regruda a borda direita ao tempo real. Mais previsível que
reconciliar pan com stream contínuo.

## Componentes

### Backend

1. **`internal/pyramid`** (evolução de `internal/overview`)
   - `New(sampleRateHz float64) *Pyramid`
   - `Push(t float64, v [NumChannels]float64)`: cai no T1, promove em cascata.
   - `SelectTier(secPerPx float64) int`
   - `Tier(i int) *tier`, `Reset()`
   - `Bucket = {TStart float64, Min/Max/Mean [NumChannels]float64, Count int}`
   - `BuildFromStore(store, motor)`: varre um run salvo e popula T1..T4.

2. **Recorte por tiles**
   - `Tile(tier, index int) (buckets []Bucket, sealed bool)`: `sealed=false` para o
     tile da ponta ainda crescendo.

3. **Handlers HTTP**
   - `GET /api/tiers`: metadados (sampleRate, span da sessão, e por tier:
     `bucketSec`, `bucketsPerTile`, `bucketCount`). O front usa isso para escolher
     tier e saber quais tiles existem, substituindo a aritmética frágil de
     `windowSec`/`viewEndSec`.
   - `GET /api/tiles?tier=T&index=I`: um tile no formato wire abaixo. Cabeçalhos de
     cache conforme `sealed`.
   - `/api/raw` permanece para o tail vivo e o zoom fundo (T0).
   - `handleSeries` é aposentado.

### Formato wire do tile

Little-endian, parseável com `DataView`:
```
header: tier u8 . bucketsCount u16 . nch u8 . bucketSec f32 . tStart0 f32
por bucket: tStart f32 . nch x (min f32, max f32, mean f32)
```
8 canais x 12 B = 96 B/bucket + 4 B de tempo = 100 B/bucket. Tile de 1024 buckets
~ 100 KB, com gzip do servidor. `tStart` por bucket cobre gaps: bucket ausente
significa sem dado, sem traço fantasma.

### Frontend (`frontend/src/`)

Elimina os dois caminhos de render e os três buffers paralelos.

1. **`TileCache`**: `Map<"tier:index", Bucket[]>`. Tiles `sealed` persistem; o da
   ponta é sempre re-fetchado. LRU com teto (proposta: 200 tiles).
2. **`ViewportController` (reescrito)**: recebe `[from, to, width]`, escolhe o tier
   pelos metadados de `/api/tiers`, lista os índices de tile que cobrem a janela,
   busca só os ausentes, monta o array contíguo de buckets e entrega. Guarda
   `[from,to]` da resposta e descarta se a vista mudou (resolve a corrida).
3. **Caminho de render único**: sempre banda min/max mais linha mean a partir de
   buckets. Em T0 os buckets são amostras raw (min==max==mean), então o traço fino
   aparece sem código especial. Removidos `useSeries`, `decimateAndProject`,
   `seriesToProjected` e os buffers `ovTBuf`/`ovSBuf`/`latestSeries`.
4. **Estado de navegação**: `paused` mais botão "Voltar ao vivo". Vivo gruda na
   borda direita; navegar congela. `streamGeneration` segue descartando respostas
   pós-reset.

uPlot é mantido (escolha correta para séries temporais em canvas). Continua o
`setScale` manual (necessário para o modo vivo), agora alimentado por dados sempre
alinhados à janela, eliminando "tempo vazio".

## Erros e bordas

- Tile da ponta cresce: sempre `no-store`, recalculado a cada request.
- Gap de dados: bucket ausente, sem traço fantasma.
- Troca de motor no meio da sessão: `Reset()` mais rebuild da pirâmide (os canais
  derivados mudam).
- Reset/Run: `streamGeneration++` no front e `Reset()` no back.
- Abrir run salvo: indicador de carregando durante o `BuildFromStore`.

## Testes

- `pyramid`: a promoção em cascata preserva min/max/mean comparada com a agregação
  direta das amostras (property test).
- Recorte de tiles: fronteiras corretas e `sealed` correto (imutabilidade).
- Handlers `/api/tiers` e `/api/tiles`: golden bytes do formato wire.
- `TileCache` (vitest): pan reaproveita tiles em cache sem re-fetch.
- `ViewportController` (vitest): descarta resposta de janela obsoleta.
- Aceite: pan/zoom contínuo sobre sessão de 30 min sem lag perceptível, sem
  mudança de caráter do traço, sem flicker.

## Fora de escopo

- Sidecar `.hiltiles` em disco para open instantâneo na segunda vez.
- Mudanças na cadeia de aquisição, no formato `.hilbin` gravado, ou na taxa de
  telemetria.
- Reconciliação de pan com stream contínuo na borda direita (modelo escolhido é
  congelar ao navegar).
