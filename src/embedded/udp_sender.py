#!/usr/bin/env python3
"""
Script UDP Python para EBAZ4205
Lê dados do solver na BRAM e envia via UDP
"""

import socket
import struct
import mmap
import time
import os

# Configurações
BRAM_ADDR = 0x40000000
BRAM_SIZE = 0x10000  # 64KB
UDP_IP = "192.168.1.100"  # IP destino (seu PC)
UDP_PORT = 5005
SAMPLE_RATE_HZ = 100  # Taxa de envio

# Layout da memória (ajuste conforme seu solver)
# Offset 0x00: speed_mech (8 bytes - 64bit, mask 42-bit)
# Offset 0x08: ialpha (8 bytes)
# Offset 0x10: ibeta (8 bytes)
# Offset 0x18: flux_alpha (8 bytes)
# Offset 0x20: flux_beta (8 bytes)

def q14_28_to_float(raw_value):
    """Converte Q14.28 fixed-point para float"""
    # Mask 42-bit
    value = raw_value & 0x3FFFFFFFFFF
    
    # Check sign bit (bit 41)
    if value & 0x20000000000:
        # Negative: extend sign
        value = value | (~0x3FFFFFFFFFF)
    
    return float(value) / (2**28)


def main():
    print(f"UDP Solver Sender iniciando...")
    print(f"Destino: {UDP_IP}:{UDP_PORT}")
    print(f"Taxa: {SAMPLE_RATE_HZ} Hz")
    
    # Mapeamento memória via /dev/mem (requer root)
    try:
        with open("/dev/mem", "r+b") as f:
            mem = mmap.mmap(f.fileno(), BRAM_SIZE, offset=BRAM_ADDR)
    except PermissionError:
        print("ERRO: Permissão negada. Execute como root (sudo python3 udp_sender.py)")
        return
    except Exception as e:
        print(f"ERRO ao mapear memória: {e}")
        return
    
    # Socket UDP
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    print("Enviando dados...")
    
    sample_period = 1.0 / SAMPLE_RATE_HZ
    packet_count = 0
    
    try:
        while True:
            start_time = time.time()
            
            # Lê dados da BRAM
            mem.seek(0)
            
            # Speed (offset 0x00)
            speed_raw = struct.unpack('<Q', mem.read(8))[0]
            speed = q14_28_to_float(speed_raw)
            
            # I_alpha (offset 0x08)
            ialpha_raw = struct.unpack('<Q', mem.read(8))[0]
            ialpha = q14_28_to_float(ialpha_raw)
            
            # I_beta (offset 0x10)
            ibeta_raw = struct.unpack('<Q', mem.read(8))[0]
            ibeta = q14_28_to_float(ibeta_raw)
            
            # Flux_alpha (offset 0x18)
            flux_alpha_raw = struct.unpack('<Q', mem.read(8))[0]
            flux_alpha = q14_28_to_float(flux_alpha_raw)
            
            # Flux_beta (offset 0x20)
            flux_beta_raw = struct.unpack('<Q', mem.read(8))[0]
            flux_beta = q14_28_to_float(flux_beta_raw)
            
            # Monta pacote UDP (struct: 5 floats = 20 bytes)
            packet = struct.pack('<fffff', speed, ialpha, ibeta, flux_alpha, flux_beta)
            
            # Envia
            sock.sendto(packet, (UDP_IP, UDP_PORT))
            
            packet_count += 1
            
            # Debug a cada 100 pacotes
            if packet_count % 100 == 0:
                print(f"[{packet_count}] speed={speed:.2f} rad/s, i_alpha={ialpha:.2f}A, i_beta={ibeta:.2f}A")
            
            # Sleep para manter taxa
            elapsed = time.time() - start_time
            sleep_time = sample_period - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
            
    except KeyboardInterrupt:
        print(f"\nParando... ({packet_count} pacotes enviados)")
    finally:
        sock.close()
        mem.close()


if __name__ == "__main__":
    main()
