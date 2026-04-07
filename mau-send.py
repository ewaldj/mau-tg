#!/usr/bin/env python3
# - - - - - - - - - - - - - - - - - - - - - - - -
# mau-send.py  by ewald@jeitler.cc 2026 https://www.jeitler.guru
# - - - - - - - - - - - - - - - - - - - - - - - -
# When I wrote this code, only God and I knew how it worked.
# Now only God and the AI know it.
# And since the AI helped write it… good luck to all of us.
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - 

VERSION = "0.46"

import socket
import struct
import sys
import time
import json
import errno
import argparse
import threading
from pathlib import Path


# --- Terminal colors ----------------------------------------------------------

class Colors:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    GRAY = '\033[90m'
    BOLD = '\033[1m'
    ENDC = '\033[0m'


# --- OWD Time Sync Server (runs inside sender) -------------------------------

OWD_SYNC_PORT = 5556


class OWDSyncServer:
    """Embedded OWD time sync server — runs as daemon thread inside sender.

    Responds to 4-timestamp timing requests from receivers.
    Uses time.time_ns() (CLOCK_REALTIME) for cross-host compatibility.
    Supports stop/restart for port changes at runtime.
    """

    def __init__(self, port=OWD_SYNC_PORT, bind_addr='0.0.0.0'):
        self.port = port
        self.bind_addr = bind_addr
        self._running = False
        self._thread = None
        self._client_count = 0
        self._lock = threading.Lock()
        self._ready = threading.Event()

    def start(self):
        """Start sync server as daemon thread. Blocks briefly until socket is bound."""
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def restart(self, new_port):
        """Stop current server and restart on new port."""
        self.stop()
        if self._thread:
            self._thread.join(timeout=2.0)
        self.port = new_port
        self.start()

    def _run(self):
        """Main server loop."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)

        try:
            sock.bind((self.bind_addr, self.port))
        except OSError as e:
            print(f"{Colors.RED}✗ OWD sync server bind error on port {self.port}: {e}{Colors.ENDC}")
            self._ready.set()
            return

        self._running = True
        self._ready.set()
        print(f"{Colors.GREEN}✓ OWD sync server running on port {self.port}{Colors.ENDC}")

        while self._running:
            try:
                data, addr = sock.recvfrom(1024)
                t2_ns = time.time_ns()
                self._handle_request(sock, data, addr, t2_ns)
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    continue
                break

        sock.close()

    def _handle_request(self, sock, data, addr, t2_ns):
        """Process a single timing request."""
        try:
            msg = json.loads(data.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        if msg.get('type') != 'req':
            return

        t3_ns = time.time_ns()
        response = json.dumps({
            'type': 'rsp',
            't1_ns': msg.get('t1_ns', 0),
            't2_ns': t2_ns,
            't3_ns': t3_ns,
        }).encode('utf-8')

        sock.sendto(response, addr)

        with self._lock:
            self._client_count += 1

    def stop(self):
        self._running = False

    @property
    def client_count(self):
        with self._lock:
            return self._client_count


# --- Packet construction ------------------------------------------------------

CONFIG_DIR = Path.home() / '.mau-send'

_HDR_STRUCT = struct.Struct('!IQ')   # seq(4) + timestamp(8) = 12 bytes
_CRC_STRUCT = struct.Struct('!I')    # crc(4)
_HEADER_SIZE = _HDR_STRUCT.size + _CRC_STRUCT.size  # 16 bytes

# UDP/IP header overhead: 20 bytes IP + 8 bytes UDP = 28 bytes
# User enters wire size (e.g. 1500), we subtract this for UDP payload
_UDP_IP_OVERHEAD = 28


def load_config():
    """Load config from disk, falling back to defaults."""
    defaults = {
        'destination_address': '239.1.1.1',
        'destination_port': 5005,
        'packet_size': 256,
        'packets_per_second': 10,
        'source_address': '',
        'source_port': 0,
        'dscp_value': 0,
        'ttl': 32,
        'sync_port': OWD_SYNC_PORT,
        'burst_mbps': 0,  # 0 = unlimited
    }
    config_file = CONFIG_DIR / 'config.json'
    if config_file.exists():
        try:
            with open(config_file, 'r') as f:
                defaults.update(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            print(f"{Colors.YELLOW}⚠ Config load error: {e}{Colors.ENDC}")
    return defaults


def save_config(config):
    """Persist config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(CONFIG_DIR / 'config.json', 'w') as f:
            json.dump(config, f, indent=2)
    except OSError as e:
        print(f"{Colors.RED}✗ Config save error: {e}{Colors.ENDC}")


def interactive_menu(config, sync_server):
    """Interactive configuration menu. Returns ('normal'|'burst', config) or None.

    sync_server is already running and gets restarted if port changes.
    """
    print(f"\n{Colors.BOLD}{Colors.BLUE}"
          f"╔══════════════════════════════════════════════════════{Colors.ENDC}")
    print(f"{Colors.BLUE}║  mau-send v{VERSION} - by Ewald Jeitler{Colors.ENDC}")
    print(f"{Colors.BLUE}"
          f"╚══════════════════════════════════════════════════════{Colors.ENDC}\n")

    fields = {
        '1': ('destination_address', 'Destination Address', str),
        '2': ('destination_port', 'Destination Port', int),
        '3': ('packet_size', 'Packet Size (bytes)', int),
        '4': ('packets_per_second', 'Rate (pps)', float),
        '5': ('dscp_value', 'DSCP Value (0-63)', int),
        '7': ('ttl', 'TTL (1-255)', int),
        '8': ('burst_mbps', 'Burst Bandwidth Limit (Mbit/s, 0=unlimited)', float),
    }

    try:
        while True:
            burst_label = (f"{config['burst_mbps']:.0f} Mbit/s"
                           if config['burst_mbps'] > 0 else "unlimited")

            print(f"{Colors.CYAN}Current Settings:{Colors.ENDC}")
            print(f"  1. Destination Address:    {config['destination_address']}")
            print(f"  2. Destination Port:       {config['destination_port']}")
            print(f"  3. Packet Size:            {config['packet_size']} bytes")
            print(f"  4. Rate (pps):             {config['packets_per_second']:.1f}")
            print(f"  5. DSCP Value:             {config['dscp_value']}")
            print(f"  6. OWD Sync Port:          {config['sync_port']}")
            print(f"  7. TTL:                    {config['ttl']}")
            print(f"  8. Burst Bandwidth Limit:  {burst_label}")
            print(f"\n  {Colors.GREEN}0. START (Normal Mode){Colors.ENDC}")
            print(f"  {Colors.GREEN}b. BURST-MODE{Colors.ENDC}")
            print(f"  {Colors.YELLOW}s. Save Config{Colors.ENDC}")
            print(f"  {Colors.RED}e. Exit{Colors.ENDC}\n")

            try:
                choice = input(
                    f"{Colors.CYAN}Choose option [0-8/b/s/e]: {Colors.ENDC}"
                ).strip().lower()
            except (KeyboardInterrupt, EOFError):
                print(f"\n{Colors.YELLOW}⊘ Cancelled{Colors.ENDC}\n")
                return None

            if choice == 'e':
                return None
            elif choice == 's':
                save_config(config)
                print(f"{Colors.GREEN}✓ Config saved{Colors.ENDC}\n")
            elif choice == '0':
                return ('normal', config)
            elif choice == 'b':
                return ('burst', config)
            elif choice == '6':
                # Sync port — restart sync server on change
                try:
                    new_port = int(input("OWD Sync Port: ").strip())
                    if new_port != config['sync_port']:
                        config['sync_port'] = new_port
                        print(f"{Colors.CYAN}Restarting OWD sync server...{Colors.ENDC}")
                        sync_server.restart(new_port)
                except ValueError:
                    print(f"{Colors.RED}✗ Invalid port{Colors.ENDC}")
            elif choice in fields:
                key, label, cast = fields[choice]
                try:
                    config[key] = cast(input(f"{label}: ").strip())
                except ValueError:
                    print(f"{Colors.RED}✗ Invalid input{Colors.ENDC}")
            else:
                print(f"{Colors.RED}✗ Unknown option{Colors.ENDC}")

            print()

    except (KeyboardInterrupt, EOFError):
        print(f"\n{Colors.YELLOW}⊘ Cancelled{Colors.ENDC}\n")
        return None


def _is_broadcast(addr):
    """Check if address is a broadcast address."""
    try:
        octets = socket.inet_aton(addr)
    except OSError:
        return False
    if octets == b'\xff\xff\xff\xff':
        return True
    if octets[-1] == 255:
        return True
    return False


def _create_send_socket(config):
    """Create and configure UDP send socket."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Broadcast requires SO_BROADCAST — without it kernel returns EACCES
    if _is_broadcast(config['destination_address']):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    if config['source_address'] or config['source_port']:
        sock.bind((config['source_address'] or '', config['source_port'] or 0))

    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, config['ttl'])

    if sys.platform != 'win32' and config['dscp_value']:
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS,
                            config['dscp_value'] << 2)
        except OSError as e:
            print(f"{Colors.YELLOW}⚠ Could not set DSCP: {e}{Colors.ENDC}")

    return sock


def _build_packet_buffer(wire_size):
    """Pre-allocate mutable bytearray for packet construction.

    wire_size is the total IP packet size on the wire (as entered by user).
    UDP payload = wire_size - 28 (IP header 20 + UDP header 8).
    Layout: [seq:4][timestamp:8][payload:N][crc:4]
    """
    udp_payload = max(wire_size - _UDP_IP_OVERHEAD, _HEADER_SIZE)
    buf = bytearray(udp_payload)
    payload_size = udp_payload - _HEADER_SIZE
    buf[_HDR_STRUCT.size:_HDR_STRUCT.size + payload_size] = b'X' * payload_size
    return buf


def _get_timestamp_us():
    """Current wallclock time in microseconds (CLOCK_REALTIME)."""
    return time.time_ns() // 1000


def _pack_and_send(buf, seq, timestamp_us, sock, dest_addr):
    """Pack header + CRC into pre-allocated buffer and send.

    Retries on ENOBUFS (kernel send buffer full) with brief backoff.
    """
    _HDR_STRUCT.pack_into(buf, 0, seq, timestamp_us)
    crc = sum(buf[:-_CRC_STRUCT.size]) & 0xFF
    _CRC_STRUCT.pack_into(buf, len(buf) - _CRC_STRUCT.size, crc)
    while True:
        try:
            sock.sendto(buf, dest_addr)
            return
        except OSError as e:
            if e.errno == errno.ENOBUFS:
                time.sleep(0.001)  # 1ms backoff, then retry
                continue
            raise


def _print_banner(config, sync_server, mode_label):
    """Print startup banner."""
    print(f"\n{Colors.GREEN}╔══════════════════════════════════════════════════════{Colors.ENDC}")
    print(f"{Colors.GREEN}║   {mode_label}{Colors.ENDC}")
    print(f"{Colors.GREEN}║   Destination: "
          f"{config['destination_address']}:{config['destination_port']}{Colors.ENDC}")
    print(f"{Colors.GREEN}║   Packet size: {config['packet_size']} bytes{Colors.ENDC}")
    if 'BURST' not in mode_label:
        print(f"{Colors.GREEN}║   Rate: "
              f"{config['packets_per_second']:.1f} pps{Colors.ENDC}")
    else:
        bw = config.get('burst_mbps', 0)
        if bw > 0:
            print(f"{Colors.GREEN}║   Bandwidth limit: {bw:.0f} Mbit/s{Colors.ENDC}")
        else:
            print(f"{Colors.GREEN}║   Bandwidth: unlimited{Colors.ENDC}")
    print(f"{Colors.GREEN}║   OWD Sync: port {sync_server.port}{Colors.ENDC}")
    print(f"{Colors.GREEN}║   CTRL+C to stop{Colors.ENDC}")
    print(f"{Colors.GREEN}╚══════════════════════════════════════════════════════{Colors.ENDC}\n")


def send_packets(config, sync_server):
    """Send packets with precise timing using perf_counter."""
    sock = _create_send_socket(config)
    dest_addr = (config['destination_address'], config['destination_port'])
    buf = _build_packet_buffer(config['packet_size'])

    _print_banner(config, sync_server, 'Sender active')

    pps = config['packets_per_second']
    packet_interval = 1.0 / pps
    use_sleep = pps <= 1000
    seq = 0
    next_send_time = time.perf_counter()

    try:
        while True:
            now = time.perf_counter()
            if now < next_send_time:
                remaining = next_send_time - now
                if use_sleep and remaining > 0.001:
                    time.sleep(remaining - 0.0005)
                continue

            _pack_and_send(buf, seq, _get_timestamp_us(), sock, dest_addr)
            seq += 1
            next_send_time += packet_interval

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}⊘ Sender stopped after {seq:,} packets{Colors.ENDC}\n")
    except OSError as e:
        print(f"{Colors.RED}✗ Send error: {e}{Colors.ENDC}\n")
    finally:
        sock.close()


def send_packets_burst(config, sync_server, duration_seconds=60):
    """Send packets in burst mode with optional bandwidth limit.

    If burst_mbps > 0, packets are paced to match the target bandwidth.
    Uses perf_counter spin-wait for accurate pacing at high rates.
    If burst_mbps == 0, packets are sent as fast as possible (no pacing).
    """
    sock = _create_send_socket(config)
    dest_addr = (config['destination_address'], config['destination_port'])
    pkt_size = config['packet_size']
    buf = _build_packet_buffer(pkt_size)
    burst_mbps = config.get('burst_mbps', 0)

    if burst_mbps > 0:
        _print_banner(config, sync_server, f'BURST-MODE: {burst_mbps:.0f} Mbit/s')
    else:
        _print_banner(config, sync_server, 'BURST-MODE: Max Speed! 🚀')

    seq = 0
    start = time.perf_counter()
    last_report = start
    report_interval = 5.0

    # Rate limiting via pacing
    # target_pps = bits_per_second / bits_per_packet
    if burst_mbps > 0:
        bits_per_packet = pkt_size * 8
        target_pps = (burst_mbps * 1_000_000) / bits_per_packet
        packet_interval = 1.0 / target_pps
        use_sleep = target_pps <= 50000
        next_send_time = start
        pacing = True
    else:
        pacing = False

    try:
        while True:
            if pacing:
                now = time.perf_counter()
                if now < next_send_time:
                    remaining = next_send_time - now
                    if use_sleep and remaining > 0.0005:
                        time.sleep(remaining - 0.0003)
                    continue

            _pack_and_send(buf, seq, _get_timestamp_us(), sock, dest_addr)
            seq += 1

            if pacing:
                next_send_time += packet_interval

            # periodic status report
            check_interval = 0xFFF if not pacing else 0x3FF
            if seq & check_interval == 0:
                now = time.perf_counter()
                if now - last_report >= report_interval:
                    elapsed = now - start
                    actual_pps = seq / elapsed
                    actual_mbps = (seq * pkt_size * 8) / (elapsed * 1e6)
                    if pacing:
                        print(f"{Colors.CYAN}[{elapsed:6.1f}s] "
                              f"Pkts:{seq:10d} | {actual_pps:10.0f} pps | "
                              f"{actual_mbps:6.1f}/{burst_mbps:.0f} Mbit/s{Colors.ENDC}")
                    else:
                        print(f"{Colors.CYAN}[{elapsed:6.1f}s] "
                              f"Pkts:{seq:10d} | {actual_pps:10.0f} pps | "
                              f"{actual_mbps:6.1f} Mbit/s{Colors.ENDC}")
                    last_report = now

                if duration_seconds > 0 and (now - start) >= duration_seconds:
                    break

    except KeyboardInterrupt:
        pass
    except OSError as e:
        print(f"{Colors.RED}✗ Send error: {e}{Colors.ENDC}")
    finally:
        sock.close()

    # final stats
    elapsed = time.perf_counter() - start
    if elapsed > 0 and seq > 0:
        actual_pps = seq / elapsed
        actual_mbps = (seq * pkt_size * 8) / (elapsed * 1e6)
        data_mb = seq * pkt_size / 1e6

        print(f"\n{Colors.GREEN}╔══════════════════════════════════════════════════════{Colors.ENDC}")
        print(f"{Colors.GREEN}║   BURST Statistics{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Time: {elapsed:.1f}s{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Packets: {seq:,}{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Rate: {actual_pps:,.0f} pps{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Throughput: {actual_mbps:.1f} Mbit/s{Colors.ENDC}")
        if burst_mbps > 0:
            print(f"{Colors.GREEN}║   Target: {burst_mbps:.0f} Mbit/s{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Data: {data_mb:.1f} MB{Colors.ENDC}")
        print(f"{Colors.GREEN}╚══════════════════════════════════════════════════════{Colors.ENDC}\n")


# --- Main ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=f'mau-send v{VERSION} - Multicast/Unicast Traffic Generator'
    )
    parser.add_argument('-d', '--destination', help='Destination address')
    parser.add_argument('-p', '--port', type=int, help='Destination port')
    parser.add_argument('-s', '--size', type=int, help='Packet size')
    parser.add_argument('--pps', type=float, help='Packets per second')
    parser.add_argument('--dscp', type=int, help='DSCP value')
    parser.add_argument('--sync-port', type=int, help='OWD sync server port')
    parser.add_argument('--burst', action='store_true',
                        help='Burst mode')
    parser.add_argument('--burst-mbps', type=float,
                        help='Burst bandwidth limit in Mbit/s (0=unlimited)')
    parser.add_argument('-m', '--menu', action='store_true',
                        help='Interactive menu')
    parser.add_argument('--version', action='store_true', help='Version')

    args = parser.parse_args()

    if args.version:
        print(f"mau-send v{VERSION}\n")
        return

    print(f"\n{Colors.CYAN}{Colors.BOLD}mau-send v{VERSION}{Colors.ENDC}\n")

    config = load_config()

    # CLI overrides
    cli_overrides = {
        'destination': 'destination_address',
        'port': 'destination_port',
        'size': 'packet_size',
        'pps': 'packets_per_second',
        'dscp': 'dscp_value',
        'sync_port': 'sync_port',
        'burst_mbps': 'burst_mbps',
    }
    for arg_name, config_key in cli_overrides.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            config[config_key] = val

    mode = 'burst' if args.burst else 'normal'

    # Start OWD sync server immediately (before menu)
    sync_server = OWDSyncServer(port=config.get('sync_port', OWD_SYNC_PORT))
    sync_server.start()

    use_menu = args.menu or (not args.destination and not args.burst)

    if not use_menu:
        # CLI mode: single run, no menu loop
        mode = 'burst' if args.burst else 'normal'
        if mode == 'burst':
            send_packets_burst(config, sync_server, duration_seconds=0)
        else:
            send_packets(config, sync_server)
        sync_server.stop()
        return

    # Menu mode: loop back after Ctrl+C stops sending
    while True:
        result = interactive_menu(config, sync_server)
        if result is None:
            sync_server.stop()
            return
        mode, config = result

        if mode == 'burst':
            send_packets_burst(config, sync_server, duration_seconds=0)
        else:
            send_packets(config, sync_server)

        # After Ctrl+C stops sending, loop back to menu
        print(f"{Colors.CYAN}Returning to menu...{Colors.ENDC}\n")


if __name__ == '__main__':
    main()
