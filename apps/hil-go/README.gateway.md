# HIL Gateway Docker

Gateway web para publicar o HIL Monitor via Cloudflare Tunnel sem perder o acesso UDP local à EBAZ.

## Porta escolhida

O sistema já usa `80`, `3000`, `6001`, `6002`, `8000`, `8080`, `8081` e `9444`.

Este gateway usa:

```text
127.0.0.1:5177
```

O container roda com `network_mode: host` porque o discovery UDP por broadcast e a telemetria UDP `5006` precisam operar na rede local do host.

## Rodar

```bash
cd apps/hil-go
docker compose -f docker-compose.gateway.yml up -d --build
```

Teste local:

```bash
curl http://127.0.0.1:5177/api/local-ip
```

## Cloudflare Tunnel

A config ativa está em:

```text
/etc/cloudflared/config.yml
```

Adicionar antes do fallback `http_status:404`:

```yaml
  - hostname: hil.contardi.dev
    service: http://localhost:5177
```

Depois:

```bash
sudo systemctl restart cloudflared
```
