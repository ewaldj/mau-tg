#!/usr/bin/env python3
# - - - - - - - - - - - - - - - - - - - - - - - -
# mau-recv.py  by ewald@jeitler.cc 2026 https://www.jeitler.guru 
# - - - - - - - - - - - - - - - - - - - - - - - -
# When I wrote this code, only god and 
# I knew how it worked. 
# Now, only god knows it! 
# - - - - - - - - - - - - - - - - - - - - - - - -

__version__ = "1.0"

import argparse
import socket
import struct
import time
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import csv

LOG_DIR = Path.home() / ".mau-recv"

class Colors:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    GRAY = '\033[90m'


DSCP_NAMES = {
    0: "BE", 8: "CS1", 10: "AF11", 12: "AF12", 14: "AF13", 16: "CS2",
    18: "AF21", 20: "AF22", 22: "AF23", 24: "CS3", 26: "AF31", 28: "AF32",
    30: "AF33", 32: "CS4", 34: "AF41", 36: "AF42", 38: "AF43", 40: "CS5",
    46: "EF", 48: "CS6", 56: "CS7",
}


def dscp_to_name(dscp):
    return DSCP_NAMES.get(dscp, f"DSCP-{dscp}")


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
            
            sock.send(b'\x01RECEIVER')
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
    
    def get_current_time_us(self):
        """Get current time relative to server start"""
        if self.synced:
            local_elapsed_us = (time.time() - self.local_time_at_sync) * 1_000_000
            return int(self.server_time_at_sync + local_elapsed_us)
        return 0


class PacketReceiver:
    def __init__(self, group, port, interface=None, log_file=None, summary_interval=None, sync_client=None, unicast_mode=False):
        self.group = group
        self.port = port
        self.interface = interface
        self.log_file = log_file
        self.summary_interval = summary_interval
        self.sync_client = sync_client or TimeSyncClientV2()
        self.unicast_mode = unicast_mode
        
        # For unicast: determine own IP
        self.own_ip = None
        if unicast_mode:
            self.own_ip = self.get_own_ip()
        
        self.total_packets = 0
        self.total_bytes = 0
        self.all_delays = []
        self.expected_seq = 0
        self.last_seq = -1
        self.total_missing = 0
        self.total_misorder = 0
        
        self.dscp_stats = defaultdict(lambda: {'packets': 0, 'delays': [], 'loss': 0})
        
        self.start_time = time.time()
        self.last_summary_time = self.start_time
        
        self.csv_file = None
        self.csv_writer = None
        if log_file:
            self.csv_file = open(log_file, 'w', newline='')
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow(['Timestamp', 'Seq', 'Delay_ms', 'DSCP', 'DSCP_Name', 'Status'])
        
        self.setup_socket()
    
    def get_own_ip(self):
        """Determine own IP address"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            sock.close()
            return ip
        except:
            return "127.0.0.1"
    
    def setup_socket(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Enable TOS byte reception for DSCP
        try:
            if hasattr(socket, 'IP_RECVTOS'):
                self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_RECVTOS, 1)
        except:
            pass
        
        if self.unicast_mode:
            # Unicast: bind to own IP
            self.sock.bind((self.own_ip, self.port))
        else:
            # Multicast
            self.sock.bind(('', self.port))
            
            # Check if multicast or unicast
            try:
                group_int = struct.unpack('!I', socket.inet_aton(self.group))[0]
                is_multicast = (group_int >= 0xE0000000) and (group_int <= 0xEFFFFFFF)
            except:
                is_multicast = False
            
            if is_multicast:
                # Multicast setup
                group = socket.inet_aton(self.group)
                if self.interface:
                    iface = socket.inet_aton(self.interface)
                    mreq = struct.pack('4s4s', group, iface)
                else:
                    mreq = struct.pack('4sL', group, socket.INADDR_ANY)
                
                self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        
        self.sock.settimeout(1.0)
    
    def extract_dscp_from_ancillary(self, ancillary):
        """Extract DSCP from ancillary data (IP_RECVTOS)"""
        try:
            for level, type_, data in ancillary:
                if level == socket.IPPROTO_IP and type_ == socket.IP_TOS:
                    tos = data[0] if isinstance(data, bytes) else data
                    return (tos >> 2) & 0x3F
        except:
            pass
        return 0
    
    def process_packet(self, packet, dscp=0):
        """Process packet - calculate delay relative to server"""
        try:
            if len(packet) < 16:
                return None
            
            seq = struct.unpack('!I', packet[0:4])[0]
            timestamp_us = struct.unpack('!Q', packet[4:12])[0]
            crc = struct.unpack('!I', packet[-4:])[0]
            
            current_time_us = self.sync_client.get_current_time_us()
            delay_us = current_time_us - timestamp_us
            delay_ms = max(0, delay_us / 1000.0)
            
            return {
                'seq': seq,
                'delay_ms': delay_ms,
                'packet_size': len(packet),
                'dscp': dscp
            }
        except:
            return None
    
    def check_order(self, seq):
        """Check sequence number order"""
        # Initialize expected_seq on first packet received
        if self.expected_seq == 0 and self.total_packets == 0:
            self.expected_seq = seq
        
        if seq < self.last_seq:
            self.total_misorder += 1
            status = 'MISORDER'
        elif seq > self.expected_seq:
            missing_count = seq - self.expected_seq
            self.total_missing += missing_count
            status = 'LOSS'
        else:
            status = 'OK'
        
        self.expected_seq = max(self.expected_seq, seq) + 1
        self.last_seq = max(self.last_seq, seq)
        
        return status
    
    def print_packet_line(self, result, status):
        """Print per-packet display with DSCP"""
        time_str = datetime.now().strftime('%H:%M:%S')
        status_color = Colors.GREEN if status == 'OK' else Colors.YELLOW if status == 'LOSS' else Colors.RED
        
        loss_pct = (self.total_missing / self.expected_seq * 100) if self.expected_seq > 0 else 0
        dscp_name = dscp_to_name(result['dscp'])
        
        print(f"{time_str} | Seq:{result['seq']:6d} | Size:{result['packet_size']:5d} "
              f"| DSCP:{dscp_name:6s}| Delay:{result['delay_ms']:7.2f}ms |  {status_color}{status:5s}{Colors.ENDC} "
              f"| Loss:{loss_pct:6.2f}%")
    
    def print_summary(self):
        """Summary line with DSCP details"""
        elapsed = time.time() - self.start_time
        if self.total_packets == 0:
            return
        
        avg_delay = sum(self.all_delays) / len(self.all_delays) if self.all_delays else 0
        throughput = (self.total_bytes * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0
        loss_pct = (self.total_missing / self.expected_seq * 100) if self.expected_seq > 0 else 0
        
        time_str = self.format_elapsed(elapsed)
        
        print(f"\n{Colors.CYAN}[{time_str}] Pkts:{self.total_packets:6d} "
              f"Tput:{throughput:6.2f}Mbps Delay:{avg_delay:6.2f}ms "
              f"Loss:{loss_pct:6.2f}% Misorder:{self.total_misorder:3d}{Colors.ENDC}")
        
        # DSCP details if multiple classes present
        if len(self.dscp_stats) > 0:
            for dscp in sorted(self.dscp_stats.keys()):
                stats = self.dscp_stats[dscp]
                if stats['packets'] > 0:
                    dscp_name = dscp_to_name(dscp)
                    dscp_percent = (stats['packets'] / self.total_packets * 100)
                    dscp_avg_delay = sum(stats['delays']) / len(stats['delays']) if stats['delays'] else 0
                    print(f"{Colors.GRAY}  └─ {dscp_name:6s}: {stats['packets']:6d} pkts ({dscp_percent:5.1f}%) "
                          f"Delay:{dscp_avg_delay:6.2f}ms{Colors.ENDC}")
        print()
    
    def format_elapsed(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
    
    def print_final_summary(self):
        """Final summary box"""
        elapsed = time.time() - self.start_time
        
        if self.total_packets == 0:
            print(f"{Colors.YELLOW}No packets received{Colors.ENDC}\n")
            return
        
        avg_delay = sum(self.all_delays) / len(self.all_delays) if self.all_delays else 0
        min_delay = min(self.all_delays) if self.all_delays else 0
        max_delay = max(self.all_delays) if self.all_delays else 0
        throughput = (self.total_bytes * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0
        loss_pct = (self.total_missing / self.expected_seq * 100) if self.expected_seq > 0 else 0
        
        time_str = self.format_elapsed(elapsed)
        
        print(f"\n{Colors.GREEN}╔═══════════════════════════════════════{Colors.ENDC}")
        print(f"{Colors.GREEN}║  Final Statistics{Colors.ENDC}")
        print(f"{Colors.GREEN}║  Time: {time_str}{Colors.ENDC}")
        print(f"{Colors.GREEN}║  Packets: {self.total_packets:,}{Colors.ENDC}")
        print(f"{Colors.GREEN}║  Data: {self.total_bytes / 1_000_000:.1f} MB{Colors.ENDC}")
        print(f"{Colors.GREEN}║  Throughput: {throughput:.2f} Mbit/s{Colors.ENDC}")
        print(f"{Colors.GREEN}║  Delay: {avg_delay:.2f}ms (min:{min_delay:.2f}ms max:{max_delay:.2f}ms){Colors.ENDC}")
        print(f"{Colors.GREEN}║  Loss: {loss_pct:.2f}% ({self.total_missing} packets){Colors.ENDC}")
        print(f"{Colors.GREEN}║  Misorder: {self.total_misorder}{Colors.ENDC}")
        print(f"{Colors.GREEN}╚═══════════════════════════════════════{Colors.ENDC}\n")
    
    def receive_loop(self):
        if self.unicast_mode:
            mode_text = f"Unicast (own IP: {self.own_ip})"
        elif self.group:
            mode_text = f"Multicast ({self.group})"
        else:
            mode_text = "Unicast + Multicast"
        
        print(f"\n{Colors.GREEN}╔═══════════════════════════════════════{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Receiver running...{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Mode: {mode_text:<28}{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Port: {self.port:<33}{Colors.ENDC}")
        if self.summary_interval:
            print(f"{Colors.GREEN}║   Summary every {self.summary_interval}s{Colors.ENDC}")
        else:
            print(f"{Colors.GREEN}║   Per-packet display{Colors.ENDC}")
        print(f"{Colors.GREEN}║   CTRL+C to stop{Colors.ENDC}")
        print(f"{Colors.GREEN}╚═══════════════════════════════════════{Colors.ENDC}\n")
        
        try:
            while True:
                try:
                    # Receive packet with ancillary data (IP_RECVTOS)
                    try:
                        packet, ancillary, flags, addr = self.sock.recvmsg(65535, 256)
                        dscp = self.extract_dscp_from_ancillary(ancillary)
                    except (TypeError, AttributeError):
                        # Fallback for systems without recvmsg
                        packet, addr = self.sock.recvfrom(65535)
                        dscp = 0
                    
                    current_time = time.time()
                    
                    result = self.process_packet(packet, dscp)
                    if result:
                        status = self.check_order(result['seq'])
                        
                        self.total_packets += 1
                        self.total_bytes += result['packet_size']
                        self.all_delays.append(result['delay_ms'])
                        
                        # Update DSCP stats
                        dscp = result['dscp']
                        self.dscp_stats[dscp]['packets'] += 1
                        self.dscp_stats[dscp]['delays'].append(result['delay_ms'])
                        if status == 'LOSS':
                            self.dscp_stats[dscp]['loss'] += 1
                        
                        if self.csv_writer:
                            self.csv_writer.writerow([
                                datetime.now().isoformat(),
                                result['seq'],
                                f"{result['delay_ms']:.3f}",
                                result['dscp'],
                                dscp_to_name(result['dscp']),
                                status
                            ])
                        
                        # Display: per-packet or summary
                        if not self.summary_interval:
                            self.print_packet_line(result, status)
                        elif current_time - self.last_summary_time >= self.summary_interval:
                            self.print_summary()
                            self.last_summary_time = current_time
                
                except socket.timeout:
                    if self.summary_interval and self.total_packets > 0:
                        current_time = time.time()
                        if current_time - self.last_summary_time >= self.summary_interval:
                            self.print_summary()
                            self.last_summary_time = current_time
        
        except KeyboardInterrupt:
            self.print_final_summary()
        finally:
            self.sock.close()
            if self.csv_file:
                self.csv_file.close()


def main():
    parser = argparse.ArgumentParser(description='mau-recv v1.0 - Multicast/Unicast Traffic Receiver')
    
    parser.add_argument('-g', '--group', default='239.1.1.1', help='Multicast group (default: 239.1.1.1)')
    parser.add_argument('-p', '--port', type=int, default=5005, help='Port (default: 5005)')
    parser.add_argument('-u', '--unicast', action='store_true', help='Unicast mode (listen on own IP)')
    parser.add_argument('-s', '--summary', type=int, help='Summary interval (seconds) - optional')
    parser.add_argument('-l', '--log', help='CSV log file')
    parser.add_argument('--sync-server', default='localhost', help='Time Sync Server')
    parser.add_argument('--sync-port', type=int, default=443, help='Time Sync Port')
    parser.add_argument('--version', action='store_true', help='Version')
    
    args = parser.parse_args()
    
    if args.version:
        print(f"mau-recv v{__version__}\n")
        return
    
    print(f"\n{Colors.CYAN}{Colors.BOLD}mau-recv v{__version__}{Colors.ENDC}\n")
    
    sync_client = TimeSyncClientV2(args.sync_server, args.sync_port)
    print(f"{Colors.CYAN}Synchronizing with Time Sync Server...{Colors.ENDC}")
    sync_client.sync()
    
    log_file = None
    if args.log:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOG_DIR / args.log
    
    # If -u is set, ignore -g for multicast join, but listen on both if -g is specified
    multicast_group = args.group if not args.unicast else None
    
    receiver = PacketReceiver(
        multicast_group,
        args.port,
        log_file=log_file,
        summary_interval=args.summary,
        sync_client=sync_client,
        unicast_mode=args.unicast
    )
    
    receiver.receive_loop()


if __name__ == '__main__':
    main()