#!/usr/bin/env python3
# - - - - - - - - - - - - - - - - - - - - - - - -
# mau-send.py  by ewald@jeitler.cc 2026 https://www.jeitler.guru 
# - - - - - - - - - - - - - - - - - - - - - - - -
# When I wrote this code, only god and 
# I knew how it worked. 
# Now, only god knows it! 
# - - - - - - - - - - - - - - - - - - - - - - - -

__version__ = "1.0"

import socket
import struct
import sys
import time
import json
import argparse
from pathlib import Path

class Colors:
    CYAN = '\033[36m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    RED = '\033[31m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    ENDC = '\033[0m'

CONFIG_DIR = Path.home() / '.mau-send'


class TimeSyncClientV2:
    """Time Sync Client v2 - Stores server time only at first sync"""
    
    def __init__(self, server_host='localhost', server_port=443):
        self.server_host = server_host
        self.server_port = server_port
        self.server_time_at_sync = 0
        self.local_time_at_sync = 0
        self.synced = False
    
    def sync(self):
        """Synchronize with server - only at startup"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            
            try:
                sock.connect((self.server_host, self.server_port))
            except:
                self.server_port = 8443
                sock.connect((self.server_host, self.server_port))
            
            sock.send(b'\x01SENDER')
            response = sock.recv(8)
            
            if len(response) == 8:
                self.server_time_at_sync = struct.unpack('!Q', response)[0]
                self.local_time_at_sync = time.time()
                self.synced = True
                print(f"{Colors.GREEN}✓ Time Sync: Server time = {self.server_time_at_sync:d} µs{Colors.ENDC}")
            
            sock.close()
        except Exception as e:
            print(f"{Colors.YELLOW}⚠ Time Sync error: {e}{Colors.ENDC}")
            self.synced = False
    
    def get_timestamp_us(self):
        """Get timestamp relative to server start"""
        if self.synced:
            local_elapsed_us = (time.time() - self.local_time_at_sync) * 1_000_000
            return int(self.server_time_at_sync + local_elapsed_us)
        return 0


def load_config():
    """Load or create config"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_file = CONFIG_DIR / 'config.json'
    
    defaults = {
        'destination_address': '239.1.1.1',
        'destination_port': 5005,
        'packet_size': 256,
        'packets_per_second': 10,
        'source_address': '',
        'source_port': 0,
        'dscp_value': 0,
        'ttl': 32,
        'time_sync_server': 'localhost',
        'time_sync_port': 443
    }
    
    if config_file.exists():
        try:
            with open(config_file, 'r') as f:
                loaded = json.load(f)
                defaults.update(loaded)
        except:
            pass
    
    return defaults


def save_config(config):
    """Save config"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(CONFIG_DIR / 'config.json', 'w') as f:
            json.dump(config, f, indent=2)
    except:
        pass


def interactive_menu(config):
    """Interactive configuration menu"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}╔════════════════════════════════════╗{Colors.ENDC}")
    print(f"{Colors.BLUE}║  mau-send v{__version__} - Configuration{Colors.ENDC}")
    print(f"{Colors.BLUE}╚════════════════════════════════════╝{Colors.ENDC}\n")
    
    try:
        while True:
            print(f"{Colors.CYAN}Current Settings:{Colors.ENDC}")
            print(f"  1. Destination Address:    {config['destination_address']}")
            print(f"  2. Destination Port:       {config['destination_port']}")
            print(f"  3. Packet Size:            {config['packet_size']} bytes")
            print(f"  4. Rate (pps):             {config['packets_per_second']:.1f}")
            print(f"  5. DSCP Value:             {config['dscp_value']}")
            print(f"  6. Time Sync Server:       {config['time_sync_server']}:{config['time_sync_port']}")
            print(f"  7. TTL:                    {config['ttl']}")
            print(f"\n  {Colors.GREEN}0. START (Normal Mode){Colors.ENDC}")
            print(f"  {Colors.GREEN}b. BURST-MODE (Max Speed!){Colors.ENDC}")
            print(f"  {Colors.YELLOW}s. Save & Exit{Colors.ENDC}")
            print(f"  {Colors.RED}q. Exit{Colors.ENDC}\n")
            
            try:
                choice = input(f"{Colors.CYAN}Choose option [0-7/b/s/q]: {Colors.ENDC}").strip().lower()
            except KeyboardInterrupt:
                print(f"\n{Colors.YELLOW}⊘ Cancelled{Colors.ENDC}\n")
                return None
            
            if choice == 'q':
                return None
            elif choice == 's':
                save_config(config)
                print(f"{Colors.GREEN}✓ Config saved{Colors.ENDC}\n")
                return config
            elif choice == '0':
                return ('normal', config)
            elif choice == 'b':
                return ('burst', config)
            elif choice == '1':
                config['destination_address'] = input("Destination address: ").strip()
            elif choice == '2':
                try:
                    config['destination_port'] = int(input("Destination port: ").strip())
                except:
                    print(f"{Colors.RED}✗ Invalid{Colors.ENDC}")
            elif choice == '3':
                try:
                    config['packet_size'] = int(input("Packet size (bytes): ").strip())
                except:
                    print(f"{Colors.RED}✗ Invalid{Colors.ENDC}")
            elif choice == '4':
                try:
                    config['packets_per_second'] = float(input("Rate (pps): ").strip())
                except:
                    print(f"{Colors.RED}✗ Invalid{Colors.ENDC}")
            elif choice == '5':
                try:
                    config['dscp_value'] = int(input("DSCP value (0-63): ").strip())
                except:
                    print(f"{Colors.RED}✗ Invalid{Colors.ENDC}")
            elif choice == '6':
                config['time_sync_server'] = input("Time Sync Server: ").strip()
                try:
                    config['time_sync_port'] = int(input("Time Sync Port: ").strip())
                except:
                    print(f"{Colors.RED}✗ Invalid{Colors.ENDC}")
            elif choice == '7':
                try:
                    config['ttl'] = int(input("TTL (1-255): ").strip())
                except:
                    print(f"{Colors.RED}✗ Invalid{Colors.ENDC}")
            else:
                print(f"{Colors.RED}✗ Invalid{Colors.ENDC}")
            
            print()
    
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}⊘ Cancelled{Colors.ENDC}\n")
        return None


def send_packets(config, time_sync_client):
    """Send packets with precise timing"""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        if config['source_address'] or config['source_port']:
            src_addr = config['source_address'] or ''
            src_port = config['source_port'] or 0
            sock.bind((src_addr, src_port))
        
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, config['ttl'])
        
        if sys.platform != 'win32':
            try:
                dscp_value = config['dscp_value'] << 2
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, dscp_value)
            except:
                pass
        
        dest_addr = (config['destination_address'], config['destination_port'])
        
        print(f"\n{Colors.GREEN}╔════════════════════════════════════{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Sender running...{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Destination: {config['destination_address']}:{config['destination_port']:<20}{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Packet size: {config['packet_size']} bytes{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Rate: {config['packets_per_second']:.1f} pps{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Time Sync: {'✓ Active' if time_sync_client.synced else '✗ Offline'}{Colors.ENDC}")
        print(f"{Colors.GREEN}║   CTRL+C to stop{Colors.ENDC}")
        print(f"{Colors.GREEN}╚════════════════════════════════════{Colors.ENDC}\n")
        
        sequence_num = 0
        packet_interval = 1.0 / config['packets_per_second']
        
        header_size = 4 + 8 + 4
        payload_size = max(0, config['packet_size'] - header_size)
        payload_template = b'X' * payload_size
        
        next_send_time = time.perf_counter()
        
        while True:
            current_perf_time = time.perf_counter()
            
            if current_perf_time >= next_send_time:
                timestamp_us = time_sync_client.get_timestamp_us()
                
                packet = struct.pack('!I', sequence_num)
                packet += struct.pack('!Q', timestamp_us)
                packet += payload_template
                crc = sum(packet) % 256
                packet += struct.pack('!I', crc)
                
                try:
                    sock.sendto(packet, dest_addr)
                    sequence_num += 1
                    next_send_time += packet_interval
                except Exception as e:
                    print(f"{Colors.RED}✗ Error: {e}{Colors.ENDC}")
            else:
                if config['packets_per_second'] > 100:
                    pass
                else:
                    time.sleep(0.00001)
        
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}⊘ Sender stopped{Colors.ENDC}\n")
    except Exception as e:
        print(f"{Colors.RED}✗ Error: {e}{Colors.ENDC}\n")
    finally:
        if sock:
            sock.close()


def send_packets_burst(config, time_sync_client, duration_seconds=60):
    """Send packets in burst mode - as fast as possible!"""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        if config['source_address'] or config['source_port']:
            src_addr = config['source_address'] or ''
            src_port = config['source_port'] or 0
            sock.bind((src_addr, src_port))
        
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, config['ttl'])
        
        if sys.platform != 'win32':
            try:
                dscp_value = config['dscp_value'] << 2
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, dscp_value)
            except:
                pass
        
        dest_addr = (config['destination_address'], config['destination_port'])
        
        print(f"\n{Colors.GREEN}╔════════════════════════════════════{Colors.ENDC}")
        print(f"{Colors.GREEN}║   BURST-MODE: Max Speed! 🚀{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Destination: {config['destination_address']}:{config['destination_port']:<20}{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Packet size: {config['packet_size']} bytes{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Duration: {duration_seconds}s{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Time Sync: {'✓ Active' if time_sync_client.synced else '✗ Offline'}{Colors.ENDC}")
        print(f"{Colors.GREEN}║   CTRL+C to stop{Colors.ENDC}")
        print(f"{Colors.GREEN}╚════════════════════════════════════{Colors.ENDC}\n")
        
        sequence_num = 0
        packet_count = 0
        
        header_size = 4 + 8 + 4
        payload_size = max(0, config['packet_size'] - header_size)
        payload_template = b'X' * payload_size
        
        start_time = time.time()
        last_report_time = start_time
        
        while True:
            try:
                current_time = time.time()
                elapsed = current_time - start_time
                
                timestamp_us = time_sync_client.get_timestamp_us()
                
                packet = struct.pack('!I', sequence_num)
                packet += struct.pack('!Q', timestamp_us)
                packet += payload_template
                crc = sum(packet) % 256
                packet += struct.pack('!I', crc)
                
                sock.sendto(packet, dest_addr)
                packet_count += 1
                sequence_num += 1
                
                # Status every 5 seconds
                if current_time - last_report_time >= 5.0:
                    pps = packet_count / elapsed if elapsed > 0 else 0
                    mbps = (packet_count * config['packet_size'] * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0
                    print(f"{Colors.CYAN}[{elapsed:6.1f}s] Pkts:{packet_count:8d} | {pps:8.0f} pps | {mbps:6.1f} Mbit/s{Colors.ENDC}")
                    last_report_time = current_time
                
                if duration_seconds > 0 and elapsed >= duration_seconds:
                    break
                    
            except Exception as e:
                print(f"{Colors.RED}✗ Error: {e}{Colors.ENDC}")
                break
        
        # Final stats
        elapsed = time.time() - start_time
        pps = packet_count / elapsed if elapsed > 0 else 0
        mbps = (packet_count * config['packet_size'] * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0
        
        print(f"\n{Colors.GREEN}╔════════════════════════════════════{Colors.ENDC}")
        print(f"{Colors.GREEN}║   BURST Statistics{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Time: {elapsed:.1f}s{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Packets: {packet_count:,}{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Rate: {pps:,.0f} pps{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Throughput: {mbps:.1f} Mbit/s{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Data: {packet_count * config['packet_size'] / 1_000_000:.1f} MB{Colors.ENDC}")
        print(f"{Colors.GREEN}╚════════════════════════════════════{Colors.ENDC}\n")
        
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}⊘ Burst stopped{Colors.ENDC}\n")
    except Exception as e:
        print(f"{Colors.RED}✗ Error: {e}{Colors.ENDC}\n")
    finally:
        if sock:
            sock.close()


def main():
    parser = argparse.ArgumentParser(description='mau-send v1.0 - Multicast/Unicast Traffic Generator')
    parser.add_argument('-d', '--destination', help='Destination address')
    parser.add_argument('-p', '--port', type=int, help='Destination port')
    parser.add_argument('-s', '--size', type=int, help='Packet size')
    parser.add_argument('--pps', type=float, help='Packets per second')
    parser.add_argument('--dscp', type=int, help='DSCP value')
    parser.add_argument('--sync-server', help='Time Sync Server')
    parser.add_argument('--sync-port', type=int, help='Time Sync Port')
    parser.add_argument('--burst', action='store_true', help='Burst mode: send as fast as possible')
    parser.add_argument('-m', '--menu', action='store_true', help='Interactive menu')
    parser.add_argument('--version', action='store_true', help='Version')
    
    args = parser.parse_args()
    
    if args.version:
        print(f"mau-send v{__version__}\n")
        return
    
    print(f"\n{Colors.CYAN}{Colors.BOLD}mau-send v{__version__}{Colors.ENDC}\n")
    
    config = load_config()
    
    # CLI arguments override config
    if args.destination:
        config['destination_address'] = args.destination
    if args.port:
        config['destination_port'] = args.port
    if args.size:
        config['packet_size'] = args.size
    if args.pps:
        config['packets_per_second'] = args.pps
    if args.dscp:
        config['dscp_value'] = args.dscp
    if args.sync_server:
        config['time_sync_server'] = args.sync_server
    if args.sync_port:
        config['time_sync_port'] = args.sync_port
    
    # Menu or direct send
    mode = 'normal'  # default
    
    if args.menu or (not args.destination and not args.burst):
        result = interactive_menu(config)
        if result is None:
            return
        
        if isinstance(result, tuple):
            mode, config = result
        else:
            config = result
    
    if args.burst:
        mode = 'burst'
    
    print(f"{Colors.CYAN}Synchronizing with Time Sync Server...{Colors.ENDC}")
    time_sync_client = TimeSyncClientV2(config['time_sync_server'], config['time_sync_port'])
    time_sync_client.sync()
    
    if mode == 'burst':
        send_packets_burst(config, time_sync_client, duration_seconds=60)
    else:
        send_packets(config, time_sync_client)


if __name__ == '__main__':
    main()
