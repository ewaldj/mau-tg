#!/usr/bin/env python3
# - - - - - - - - - - - - - - - - - - - - - - - -
# mau-time.py  by ewald@jeitler.cc 2026 https://www.jeitler.guru 
# - - - - - - - - - - - - - - - - - - - - - - - -
# When I wrote this code, only god and 
# I knew how it worked. 
# Now, only god knows it! 
# - - - - - - - - - - - - - - - - - - - - - - - -

__version__ = "1.0"

import socket
import struct
import time
import sys
import threading
from datetime import datetime

class Colors:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


class TimeSyncServer:
    def __init__(self, port=443):
        self.port = port
        self.start_time = time.time()  # Server reference point
        self.client_count = 0
        
    def run(self):
        """Start Time Sync Server"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('0.0.0.0', self.port))
            sock.listen(5)
            
            print(f"\n{Colors.CYAN}{Colors.BOLD}╔═════════════════════════════════════{Colors.ENDC}")
            print(f"{Colors.CYAN}║   mau-time v{__version__} Server running{Colors.ENDC}")
            print(f"{Colors.CYAN}║   Port: {self.port}{Colors.ENDC}")
            print(f"{Colors.CYAN}║   Sends RELATIVE time (not absolute){Colors.ENDC}")
            print(f"{Colors.CYAN}║   CTRL+C to stop{Colors.ENDC}")
            print(f"{Colors.CYAN}╚═════════════════════════════════════{Colors.ENDC}\n")
            
            while True:
                try:
                    client_sock, addr = sock.accept()
                    thread = threading.Thread(target=self.handle_client, args=(client_sock, addr))
                    thread.daemon = True
                    thread.start()
                except KeyboardInterrupt:
                    print(f"\n{Colors.YELLOW}⊘ Server stopped ({self.client_count} clients served){Colors.ENDC}\n")
                    break
        except PermissionError:
            print(f"{Colors.RED}✗ Port {self.port} requires admin privileges!{Colors.ENDC}")
            print(f"{Colors.YELLOW}  Trying port 8443 instead...{Colors.ENDC}\n")
            self.port = 8443
            self.run()
        except Exception as e:
            print(f"{Colors.RED}✗ Error: {e}{Colors.ENDC}\n")
        finally:
            sock.close()
    
    def handle_client(self, client_sock, addr):
        """Handle client request"""
        try:
            request = client_sock.recv(1)
            
            if request == b'\x01':  # TIME_REQUEST
                # IMPORTANT: Send RELATIVE time since server start (not absolute!)
                relative_time_us = int((time.time() - self.start_time) * 1_000_000)
                response = struct.pack('!Q', relative_time_us)
                client_sock.send(response)
                
                client_type = "UNKNOWN"
                try:
                    extra = client_sock.recv(10)
                    if extra == b'SENDER':
                        client_type = "SENDER"
                    elif extra == b'RECEIVER':
                        client_type = "RECEIVER"
                except:
                    pass
                
                self.client_count += 1
                
                print(f"{Colors.GREEN}[{datetime.now().strftime('%H:%M:%S')}] "
                      f"{client_type:8s} from {addr[0]:15s} → Relative time: {relative_time_us:15d} µs{Colors.ENDC}")
            
        except Exception as e:
            print(f"{Colors.RED}Error with {addr}: {e}{Colors.ENDC}")
        finally:
            client_sock.close()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='mau-time v1.0 - Time Sync Server')
    parser.add_argument('-p', '--port', type=int, default=443, 
                       help='Port (default: 443, fallback: 8443)')
    parser.add_argument('--version', action='store_true', help='Show version')
    
    args = parser.parse_args()
    
    if args.version:
        print(f"mau-time v{__version__}\n")
        return
    
    server = TimeSyncServer(args.port)
    try:
        server.run()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Server terminated{Colors.ENDC}\n")


if __name__ == '__main__':
    main()
