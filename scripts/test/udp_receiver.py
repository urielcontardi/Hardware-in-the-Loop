#!/usr/bin/env python3
"""
Receptor UDP para dados do solver EBAZ4205
Salva dados em CSV para análise
"""

import socket
import struct
import time
import csv
from datetime import datetime

UDP_IP = "0.0.0.0"  # Escuta em todas interfaces
UDP_PORT = 5005

def main():
    # Cria socket UDP
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    
    print(f"Receptor UDP iniciado em {UDP_IP}:{UDP_PORT}")
    print("Aguardando dados do EBAZ4205...")
    
    # Arquivo CSV para salvar dados
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = f"solver_data_{timestamp}.csv"
    
    with open(csv_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'speed_rad_s', 'ialpha_A', 'ibeta_A', 'flux_alpha_Wb', 'flux_beta_Wb'])
        
        packet_count = 0
        start_time = time.time()
        
        try:
            while True:
                # Recebe pacote
                data, addr = sock.recvfrom(1024)
                
                if len(data) == 20:  # 5 floats = 20 bytes
                    # Desempacota
                    speed, ialpha, ibeta, flux_alpha, flux_beta = struct.unpack('<fffff', data)
                    
                    # Timestamp relativo
                    timestamp = time.time() - start_time
                    
                    # Salva em CSV
                    writer.writerow([timestamp, speed, ialpha, ibeta, flux_alpha, flux_beta])
                    
                    packet_count += 1
                    
                    # Display a cada 50 pacotes
                    if packet_count % 50 == 0:
                        print(f"[{packet_count:6d}] t={timestamp:7.2f}s | "
                              f"speed={speed:7.2f} rad/s | "
                              f"ialpha={ialpha:6.2f}A | "
                              f"ibeta={ibeta:6.2f}A")
                        f.flush()  # Force write
                else:
                    print(f"Pacote com tamanho inválido: {len(data)} bytes (esperado 20)")
                    
        except KeyboardInterrupt:
            print(f"\n\nParando... {packet_count} pacotes recebidos")
            print(f"Dados salvos em: {csv_file}")
            
            # Estatísticas
            elapsed = time.time() - start_time
            rate = packet_count / elapsed if elapsed > 0 else 0
            print(f"Taxa média: {rate:.1f} Hz")
        
        finally:
            sock.close()


if __name__ == "__main__":
    main()
