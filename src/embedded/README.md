# Embedded Software (Linux no EBAZ4205)

Software (Python/C/Shell) que roda no ARM Linux embarcado do EBAZ4205.

Este diretório contém código-fonte de aplicações embarcadas, não os binários compilados.

## Scripts

### `udp_sender.py`
Lê dados do solver da BRAM e envia via UDP ethernet.

**Características:**
- Acessa memória física: `0x40000000` (64KB BRAM)
- Taxa: 100 Hz (configurável)
- Protocolo: UDP
- Destino: `192.168.1.100:5005` (configurável no código)

**Uso no EBAZ4205:**
```bash
# Manual
sudo python3 /home/root/udp_sender.py

# Via systemd (auto-start)
systemctl start udp-solver.service
systemctl status udp-solver.service
```

**Formato UDP:**
Pacote de 20 bytes (5 floats, little-endian):
```c
struct {
    float speed_rad_s;      // Velocidade mecânica (rad/s)
    float ialpha_A;         // Corrente alpha (A)
    float ibeta_A;          // Corrente beta (A)
    float flux_alpha_Wb;    // Fluxo alpha (Wb)
    float flux_beta_Wb;     // Fluxo beta (Wb)
}
```

**Layout BRAM (memória compartilhada PL→PS):**
```
Offset  | Campo        | Tamanho | Formato
--------|--------------|---------|----------
0x00    | speed_mech   | 8 bytes | Q14.28 (42-bit)
0x08    | ialpha       | 8 bytes | Q14.28 (42-bit)
0x10    | ibeta        | 8 bytes | Q14.28 (42-bit)
0x18    | flux_alpha   | 8 bytes | Q14.28 (42-bit)
0x20    | flux_beta    | 8 bytes | Q14.28 (42-bit)
```

**Dependências:**
- Python 3 (instalado via Petalinux rootfs config)
- Acesso root ou permissões `/dev/mem`

## Instalação no EBAZ4205

### Opção 1: Copiar para SD Card rootfs
```bash
# No PC, com SD card montado em /mnt
sudo cp src/embedded/udp_sender.py /mnt/home/root/
sudo chmod +x /mnt/home/root/udp_sender.py
```

### Opção 2: Via SCP (após boot Linux)
```bash
# Do PC (do diretório raiz do projeto)
scp src/embedded/udp_sender.py root@192.168.1.10:/home/root/
```

### Opção 3: Incluir no rootfs Petalinux (build-time)
Adicionar no `project-spec/meta-user/recipes-apps/`:

```bash
# Criar recipe custom
petalinux-create -t apps --name udp-solver --enable
# Copiar udp_sender.py para files/
# Editar .bb recipe para instalar
```

## Auto-start (systemd service)

Arquivo: `/etc/systemd/system/udp-solver.service`

```ini
[Unit]
Description=UDP Solver Data Sender
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 /home/root/udp_sender.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Enable:**
```bash
systemctl enable udp-solver.service
systemctl start udp-solver.service
```

## Troubleshooting

**"Permission denied" ao abrir /dev/mem:**
- Execute com `sudo`
- Ou configure UIO no device tree (mais seguro)

**"Cannot connect to UDP":**
- Verifique IP destino no código
- Test ping: `ping 192.168.1.100`
- Verifique firewall no PC

**"No data from BRAM" (valores zerados):**
- Verifique se FPGA foi carregado: `cat /sys/class/fpga_manager/fpga0/state`
- Check se solver está escrevendo (debug com ILA no Vivado)
- Verifique endereço BRAM no Address Editor (deve ser 0x40000000)

## Desenvolvimento

**Testar localmente no PC (sem hardware):**
```python
# Simula BRAM com arquivo
with open("/tmp/fake_bram", "wb") as f:
    f.write(b'\x00' * 0x10000)

# Modifica udp_sender.py:
# mem = mmap.mmap(f.fileno(), BRAM_SIZE, offset=BRAM_ADDR)
# Para:
with open("/tmp/fake_bram", "r+b") as f:
    mem = mmap.mmap(f.fileno(), BRAM_SIZE)
```

## Performance

Taxa teórica máxima:
- CPU ARM Cortex-A9 @ 667 MHz
- Leitura BRAM via HP0: ~1200 MB/s (AXI 64-bit @ 150 MHz)
- UDP overhead: ~100 µs por pacote
- **Taxa esperada: 1-10 kHz** (limitado por Python GIL e syscalls)

Para >10 kHz, considere:
- Implementar em C puro
- Usar DMA direto (driver kernel)
- Buffering circular na BRAM
