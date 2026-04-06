# Scripts para Host PC (Ubuntu)

Este diretório contém scripts que rodam no seu PC de desenvolvimento.

## Estrutura

```
scripts/
├── setup/              # Scripts de instalação e configuração
│   └── install_petalinux_deps.sh
├── build/              # Scripts de build Vivado/Petalinux
└── test/               # Scripts de teste e validação
    └── udp_receiver.py
```

## Setup

### `install_petalinux_deps.sh`
Instala todas as dependências necessárias para Petalinux no Ubuntu 24.04.

**Uso:**
```bash
cd scripts/setup
./install_petalinux_deps.sh
```

## Test

### `udp_receiver.py`
Recebe dados UDP do EBAZ4205 e salva em CSV.

**Uso:**
```bash
cd scripts/test
python3 udp_receiver.py
```

**Configuração:**
- Porta: 5005 (padrão)
- Protocolo: UDP
- Formato: 5 floats (20 bytes) - speed, ialpha, ibeta, flux_alpha, flux_beta

**Saída:**
- `solver_data_YYYYMMDD_HHMMSS.csv` - dados com timestamp
