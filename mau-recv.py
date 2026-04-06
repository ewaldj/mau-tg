#!/usr/bin/env python3
# - - - - - - - - - - - - - - - - - - - - - - - -
# mau-recv.py  by ewald@jeitler.cc 2026 https://www.jeitler.guru
# - - - - - - - - - - - - - - - - - - - - - - - -
# When I wrote this code, only God and I knew how it worked.
# Now only God and the AI know it.
# And since the AI helped write it… good luck to all of us.
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - 

VERSION = "0.43"

import argparse
import socket
import struct
import time
import json
import sys
import csv
import threading
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import NamedTuple

LOG_DIR = Path.home() / ".mau-recv"


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


# --- DSCP names ---------------------------------------------------------------

DSCP_NAMES = {
    0: "BE", 8: "CS1", 10: "AF11", 12: "AF12", 14: "AF13", 16: "CS2",
    18: "AF21", 20: "AF22", 22: "AF23", 24: "CS3", 26: "AF31", 28: "AF32",
    30: "AF33", 32: "CS4", 34: "AF41", 36: "AF42", 38: "AF43", 40: "CS5",
    46: "EF", 48: "CS6", 56: "CS7",
}


def dscp_to_name(dscp):
    return DSCP_NAMES.get(dscp, f"DSCP-{dscp}")


def format_elapsed(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# --- OWD Sync Client ----------------------------------------------------------

OWD_SYNC_PORT = 5556
OWD_WARMUP_COUNT = 3
OWD_RESYNC_INTERVAL = 30.0  # re-measure offset every N seconds


class OWDSyncClient:
    """OWD time sync client — measures clock offset to sender via 4-timestamp protocol.

    Uses time.time_ns() (CLOCK_REALTIME) on both sides.
    The sender embeds CLOCK_REALTIME timestamps (us) in data packets.
    This client measures the clock offset between sender and receiver,
    allowing accurate one-way delay calculation without a third-party time server.

    The offset is re-measured periodically to track clock drift.
    """

    def __init__(self, sender_ip, sync_port=OWD_SYNC_PORT,
                 resync_interval=OWD_RESYNC_INTERVAL):
        self.sender_addr = (sender_ip, sync_port)
        self.resync_interval = resync_interval

        # clock offset in microseconds: sender_time = local_time + offset_us
        self.offset_us = 0.0
        self.rtt_ms = 0.0
        self.synced = False

        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    def initial_sync(self) -> bool:
        """Perform initial sync with warmup. Returns True on success."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2.0)

        try:
            # warmup: prime ARP, conntrack, buffers
            for _ in range(OWD_WARMUP_COUNT):
                self._measure_once(sock)
                time.sleep(0.05)

            # actual measurement: take best of 5 (lowest RTT = most accurate)
            results = []
            for _ in range(5):
                r = self._measure_once(sock)
                if r is not None:
                    results.append(r)
                time.sleep(0.05)

            if not results:
                return False

            # select measurement with lowest RTT (most accurate offset)
            best = min(results, key=lambda x: x[0])
            with self._lock:
                self.rtt_ms = best[0]
                self.offset_us = best[1]
                self.synced = True

            return True

        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}⊘ Sync cancelled{Colors.ENDC}")
            return False
        except Exception as e:
            print(f"{Colors.YELLOW}⚠ OWD sync error: {e}{Colors.ENDC}")
            return False
        finally:
            sock.close()

    def start_background_resync(self):
        """Start background thread for periodic offset re-measurement."""
        self._running = True
        self._thread = threading.Thread(target=self._resync_loop, daemon=True)
        self._thread.start()

    def _resync_loop(self):
        """Periodically re-measure clock offset to track drift."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2.0)

        while self._running:
            time.sleep(self.resync_interval)
            try:
                results = []
                for _ in range(3):
                    r = self._measure_once(sock)
                    if r is not None:
                        results.append(r)
                    time.sleep(0.05)

                if results:
                    best = min(results, key=lambda x: x[0])
                    with self._lock:
                        self.rtt_ms = best[0]
                        self.offset_us = best[1]
                        self.synced = True
            except OSError:
                pass

        sock.close()

    def _measure_once(self, sock) -> tuple | None:
        """Single 4-timestamp measurement.

        Returns (rtt_ms, offset_us) or None on failure.
        """
        request = json.dumps({
            'type': 'req',
            't1_ns': time.time_ns(),
        }).encode('utf-8')

        # stamp T1 as late as possible
        t1_ns = time.time_ns()
        request = json.dumps({
            'type': 'req',
            't1_ns': t1_ns,
        }).encode('utf-8')

        try:
            sock.sendto(request, self.sender_addr)
            data, _ = sock.recvfrom(1024)
            t4_ns = time.time_ns()
        except (socket.timeout, OSError):
            return None

        try:
            msg = json.loads(data.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

        if msg.get('type') != 'rsp' or msg.get('t1_ns') != t1_ns:
            return None

        t2_ns = msg['t2_ns']
        t3_ns = msg['t3_ns']

        # RTT = (T4-T1) - (T3-T2)  (total round-trip minus server processing)
        rtt_ns = (t4_ns - t1_ns) - (t3_ns - t2_ns)

        # clock offset theta = ((T2-T1) + (T3-T4)) / 2
        # positive = sender clock is ahead of receiver clock
        offset_ns = ((t2_ns - t1_ns) + (t3_ns - t4_ns)) / 2.0

        rtt_ms = rtt_ns / 1_000_000.0
        offset_us = offset_ns / 1_000.0

        return (rtt_ms, offset_us)

    def get_delay_us(self, sender_timestamp_us: int) -> float | None:
        """Compute one-way delay in microseconds from sender timestamp.

        Returns None if not synced.

        Derivation:
          offset theta = ((T2-T1)+(T3-T4))/2 where T1/T4=receiver, T2/T3=sender
          theta > 0 means sender clock is AHEAD of receiver clock
          sender_time = receiver_time + theta
          For a data packet:  receiver_now = sender_stamp - theta + delay
          Therefore:          delay = receiver_now - sender_stamp + theta
        """
        with self._lock:
            if not self.synced:
                return None
            offset = self.offset_us

        local_us = time.time_ns() / 1_000.0
        delay_us = local_us - sender_timestamp_us + offset
        return delay_us

    def stop(self):
        self._running = False


# --- Packet parsing -----------------------------------------------------------

_HDR_STRUCT = struct.Struct('!IQ')   # seq(4) + timestamp(8)
_CRC_STRUCT = struct.Struct('!I')    # crc(4)
_MIN_PACKET_SIZE = _HDR_STRUCT.size + _CRC_STRUCT.size  # 16 bytes

# UDP/IP header overhead: 20 bytes IP + 8 bytes UDP = 28 bytes
# len(packet) returns UDP payload; add this for wire size display
_UDP_IP_OVERHEAD = 28


class PacketInfo(NamedTuple):
    """Parsed packet data."""
    seq: int
    delay_ms: float | None  # None if sync unavailable
    packet_size: int
    dscp: int


# --- Statistics ---------------------------------------------------------------

class RunningStats:
    """O(1) running statistics — no unbounded list growth."""
    __slots__ = ('count', 'total', 'min_val', 'max_val')

    def __init__(self):
        self.count = 0
        self.total = 0.0
        self.min_val = float('inf')
        self.max_val = float('-inf')

    def add(self, value):
        self.count += 1
        self.total += value
        if value < self.min_val:
            self.min_val = value
        if value > self.max_val:
            self.max_val = value

    @property
    def avg(self):
        return self.total / self.count if self.count else 0.0

    @property
    def minimum(self):
        return self.min_val if self.count else 0.0

    @property
    def maximum(self):
        return self.max_val if self.count else 0.0


class DscpStats:
    """Per-DSCP running statistics."""
    __slots__ = ('packets', 'delays', 'loss')

    def __init__(self):
        self.packets = 0
        self.delays = RunningStats()
        self.loss = 0


# --- Receiver -----------------------------------------------------------------

class PacketReceiver:
    def __init__(self, group, port, interface=None, log_file=None,
                 summary_interval=None, sync_client=None, unicast_mode=False,
                 summary_compact=False):
        self.group = group
        self.port = port
        self.interface = interface
        self.log_file = log_file
        self.summary_interval = summary_interval
        self.summary_compact = summary_compact
        self.sync_client = sync_client
        self.unicast_mode = unicast_mode

        self.own_ip = self._get_own_ip() if unicast_mode else None

        # counters (lifetime totals for final summary)
        self.total_packets = 0
        self.total_bytes = 0
        self.delay_stats = RunningStats()

        # interval counters (reset after each summary)
        self.iv_packets = 0
        self.iv_bytes = 0
        self.iv_delay = RunningStats()
        self.iv_missing = 0
        self.iv_misorder = 0
        self.iv_start_time = time.monotonic()

        # sequence tracking
        self.expected_seq = None
        self.last_seq = -1
        self.total_missing = 0
        self.total_misorder = 0

        # per-DSCP (lifetime)
        self.dscp_stats = defaultdict(DscpStats)
        # per-DSCP (interval)
        self.iv_dscp_stats = defaultdict(DscpStats)

        # timing
        self.start_time = time.monotonic()
        self.last_summary_time = self.start_time

        # CSV
        self.csv_file = None
        self.csv_writer = None
        if log_file:
            self.csv_file = open(log_file, 'w', newline='', buffering=8192)
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow([
                'Timestamp', 'Seq', 'Delay_ms', 'DSCP', 'DSCP_Name', 'Status'
            ])

        self.sock = self._setup_socket()

    @staticmethod
    def _get_own_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except OSError:
            return "127.0.0.1"

    def _setup_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # SO_REUSEPORT allows multiple processes to bind to the same port.
        # Required on macOS/BSD; on Linux it enables kernel load-balancing.
        if hasattr(socket, 'SO_REUSEPORT'):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass

        if hasattr(socket, 'IP_RECVTOS'):
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_RECVTOS, 1)
            except OSError:
                pass

        if self.unicast_mode:
            sock.bind((self.own_ip, self.port))
        else:
            sock.bind(('', self.port))
            self._join_multicast(sock)

        sock.settimeout(1.0)
        return sock

    def _join_multicast(self, sock):
        if not self.group:
            return
        try:
            group_int = struct.unpack('!I', socket.inet_aton(self.group))[0]
        except OSError:
            return

        if not (0xE0000000 <= group_int <= 0xEFFFFFFF):
            return

        group_bytes = socket.inet_aton(self.group)
        if self.interface:
            iface_bytes = socket.inet_aton(self.interface)
            mreq = struct.pack('4s4s', group_bytes, iface_bytes)
        else:
            mreq = struct.pack('4sL', group_bytes, socket.INADDR_ANY)

        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    @staticmethod
    def _extract_dscp(ancillary):
        for level, type_, data in ancillary:
            if level == socket.IPPROTO_IP and type_ == socket.IP_TOS:
                tos = data[0] if isinstance(data, bytes) else data
                return (tos >> 2) & 0x3F
        return 0

    def _parse_packet(self, packet, dscp=0):
        """Parse packet and compute one-way delay via OWD sync.

        Returns PacketInfo. delay_ms is None if sync is unavailable.
        """
        if len(packet) < _MIN_PACKET_SIZE:
            return None

        try:
            seq, timestamp_us = _HDR_STRUCT.unpack_from(packet, 0)
        except struct.error:
            return None

        delay_ms = None
        if self.sync_client:
            delay_us = self.sync_client.get_delay_us(timestamp_us)
            if delay_us is not None:
                delay_ms = delay_us / 1000.0

        return PacketInfo(
            seq=seq,
            delay_ms=delay_ms,
            packet_size=len(packet) + _UDP_IP_OVERHEAD,  # wire size
            dscp=dscp,
        )

    # Sender restart detection: if seq drops by more than this threshold
    # relative to last_seq, treat it as a sender restart, not misorder.
    _RESTART_THRESHOLD = 10

    def _check_order(self, seq):
        """Check sequence order. Returns (status, gap).

        gap = number of missing packets for LOSS status, else 0.
        Detects sender restart:
          1) seq == 0 always indicates a fresh sender start
          2) seq drops by more than _RESTART_THRESHOLD
        """
        if self.expected_seq is None:
            self.expected_seq = seq

        gap = 0
        is_restart = False

        if seq == 0 and self.last_seq > 0:
            is_restart = True
        elif seq < self.last_seq and (self.last_seq - seq) > self._RESTART_THRESHOLD:
            is_restart = True

        if is_restart:
            print(f"{Colors.YELLOW}⚠ Sender restart detected "
                  f"(seq {self.last_seq} → {seq}) — "
                  f"resetting sequence tracker{Colors.ENDC}")
            self.expected_seq = seq
            self.last_seq = -1
            status = 'RESTART'
        elif seq < self.last_seq:
            self.total_misorder += 1
            status = 'MISORDER'
        elif seq > self.expected_seq:
            gap = seq - self.expected_seq
            self.total_missing += gap
            status = 'LOSS'
        else:
            status = 'OK'

        if seq >= self.expected_seq:
            self.expected_seq = seq + 1
        self.last_seq = max(self.last_seq, seq)

        return status, gap

    def _loss_pct(self):
        total_expected = self.total_packets + self.total_missing
        if total_expected <= 0:
            return 0.0
        return (self.total_missing / total_expected) * 100

    def _print_packet_line(self, pkt, status):
        time_str = datetime.now().strftime('%H:%M:%S')
        if status in ('OK', 'RESTART'):
            sc = Colors.GREEN
        elif status == 'LOSS':
            sc = Colors.YELLOW
        else:
            sc = Colors.RED

        if pkt.delay_ms is not None:
            delay_str = f"Delay:{pkt.delay_ms:7.2f}ms"
        else:
            delay_str = "Delay:   n/a  "

        print(f"{time_str} | Seq:{pkt.seq:6d} | Size:{pkt.packet_size:5d} "
              f"| DSCP:{dscp_to_name(pkt.dscp):6s}| "
              f"{delay_str} | {sc}{status:5s}{Colors.ENDC} "
              f"| Loss:{self._loss_pct():6.2f}%")

    def _print_summary(self):
        """Print single-line interval summary."""
        now = time.monotonic()
        iv_elapsed = now - self.iv_start_time
        total_elapsed = now - self.start_time

        # time range as clean integer seconds
        iv_end = round(total_elapsed)
        iv_start = round(total_elapsed - iv_elapsed)
        if iv_start < 0:
            iv_start = 0
        time_str = datetime.now().strftime('%H:%M:%S')
        # fixed-width range: "   0–2s  " or " 100–102s" — always 10 chars
        range_str = f"{iv_start}–{iv_end}s"
        range_str = f"{range_str:>10s}"

        if self.iv_packets == 0:
            if self.summary_compact:
                print(f"{range_str} "
                      f"| {Colors.YELLOW}no traffic{Colors.ENDC}")
            else:
                print(f"{time_str} | {range_str} "
                      f"| {Colors.YELLOW}no traffic received{Colors.ENDC}")
            self.iv_start_time = now
            return

        # throughput
        iv_throughput = (self.iv_bytes * 8) / (iv_elapsed * 1e6) if iv_elapsed > 0 else 0

        # packet size
        pkt_size = self.iv_bytes // self.iv_packets if self.iv_packets > 0 else 0

        # dominant DSCP
        if self.iv_dscp_stats:
            top_dscp = max(self.iv_dscp_stats, key=lambda d: self.iv_dscp_stats[d].packets)
        else:
            top_dscp = 0

        # delay
        if self.iv_delay.count > 0:
            delay_str = (f"Dly(ms): avg:{self.iv_delay.avg:.2f} "
                         f"min:{self.iv_delay.minimum:.2f} "
                         f"max:{self.iv_delay.maximum:.2f}")
        else:
            delay_str = "Dly(ms): n/a"

        # loss
        iv_expected = self.iv_packets + self.iv_missing
        iv_loss_pct = (self.iv_missing / iv_expected * 100) if iv_expected > 0 else 0.0

        # status
        if self.iv_missing > 0:
            status = 'LOSS'
            sc = Colors.YELLOW
        elif self.iv_misorder > 0:
            status = 'MISORD'
            sc = Colors.RED
        else:
            status = 'OK'
            sc = Colors.GREEN

        if self.summary_compact:
            # compact: no timestamp, no size, short DSCP, short delay
            dly_str = f"Dly:{self.iv_delay.avg:.2f}" if self.iv_delay.count > 0 else "Dly:n/a"
            print(f"{range_str} "
                  f"| {iv_throughput:7.2f} Mbps "
                  f"| {dscp_to_name(top_dscp):6s}"
                  f"| {sc}{status:4s}{Colors.ENDC} "
                  f"| Pkt:{self.iv_packets:9d} "
                  f"| LPkt:{self.iv_missing:7d} "
                  f"| {dly_str}")
        else:
            print(f"{time_str} | {range_str} "
                  f"| {iv_throughput:7.2f} Mbps "
                  f"| {pkt_size:5d}B "
                  f"| DSCP:{dscp_to_name(top_dscp):6s}"
                  f"| {sc}{status:6s}{Colors.ENDC} "
                  f"| Pkt:{self.iv_packets:9d} "
                  f"| Loss:{iv_loss_pct:5.2f}% Pkt:{self.iv_missing:6d} "
                  f"| {delay_str}")

        # reset interval counters
        self.iv_packets = 0
        self.iv_bytes = 0
        self.iv_delay = RunningStats()
        self.iv_missing = 0
        self.iv_misorder = 0
        self.iv_dscp_stats = defaultdict(DscpStats)
        self.iv_start_time = now

    def _print_final_summary(self):
        elapsed = time.monotonic() - self.start_time

        if self.total_packets == 0:
            print(f"{Colors.YELLOW}No packets received{Colors.ENDC}\n")
            return

        throughput = (self.total_bytes * 8) / (elapsed * 1e6) if elapsed > 0 else 0
        ds = self.delay_stats

        print(f"\n{Colors.GREEN}╔═════════════════════════════════════════════════════╗{Colors.ENDC}")
        print(f"{Colors.GREEN}║  Final Statistics{Colors.ENDC}")
        print(f"{Colors.GREEN}║  Time: {format_elapsed(elapsed)}{Colors.ENDC}")
        print(f"{Colors.GREEN}║  Packets: {self.total_packets:,}{Colors.ENDC}")
        print(f"{Colors.GREEN}║  Data: {self.total_bytes / 1e6:.1f} MB{Colors.ENDC}")
        print(f"{Colors.GREEN}║  Throughput: {throughput:.2f} Mbit/s{Colors.ENDC}")
        if ds.count > 0:
            print(f"{Colors.GREEN}║  Delay: {ds.avg:.2f}ms "
                  f"(min:{ds.minimum:.2f}ms max:{ds.maximum:.2f}ms){Colors.ENDC}")
        else:
            print(f"{Colors.GREEN}║  Delay: n/a (sync unavailable){Colors.ENDC}")
        print(f"{Colors.GREEN}║  Loss: {self._loss_pct():.2f}% "
              f"({self.total_missing} packets){Colors.ENDC}")
        print(f"{Colors.GREEN}║  Misorder: {self.total_misorder}{Colors.ENDC}")
        print(f"{Colors.GREEN}╚═════════════════════════════════════════════════════╝{Colors.ENDC}\n")

    def receive_loop(self):
        """Main receive loop."""
        if self.unicast_mode:
            mode_text = f"Unicast only (local IP: {self.own_ip})"
        elif self.group:
            mode_text = f"Multicast {self.group}, Unicast and Broadcast"
        else:
            mode_text = "Unicast + Multicast"

        sync_status = "active" if (self.sync_client and self.sync_client.synced) else "failed — set  -–sender-ip <ip>"

        print(f"\n{Colors.GREEN}╔═════════════════════════════════════════════════════╗{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Receiver active{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Mode: {mode_text:<28}{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Port: {self.port:<33}{Colors.ENDC}")
        print(f"{Colors.GREEN}║   OWD Sync: {sync_status:<29}{Colors.ENDC}")
        if self.summary_interval:
            print(f"{Colors.GREEN}║   Summary every {self.summary_interval}s{Colors.ENDC}")
        else:
            print(f"{Colors.GREEN}║   View: per-packet display{Colors.ENDC}")
        print(f"{Colors.GREEN}║   Stop: CTRL+C{Colors.ENDC}")
        print(f"{Colors.GREEN}╚═════════════════════════════════════════════════════╝{Colors.ENDC}\n")

        use_recvmsg = hasattr(self.sock, 'recvmsg')

        try:
            while True:
                try:
                    if use_recvmsg:
                        packet, ancillary, _flags, _addr = self.sock.recvmsg(
                            65535, 256
                        )
                        dscp = self._extract_dscp(ancillary)
                    else:
                        packet, _addr = self.sock.recvfrom(65535)
                        dscp = 0

                    pkt = self._parse_packet(packet, dscp)
                    if pkt is None:
                        continue

                    status, gap = self._check_order(pkt.seq)

                    self.total_packets += 1
                    self.total_bytes += pkt.packet_size
                    if pkt.delay_ms is not None:
                        self.delay_stats.add(pkt.delay_ms)

                    ds = self.dscp_stats[pkt.dscp]
                    ds.packets += 1
                    if pkt.delay_ms is not None:
                        ds.delays.add(pkt.delay_ms)
                    if status == 'LOSS':
                        ds.loss += gap

                    # interval counters
                    self.iv_packets += 1
                    self.iv_bytes += pkt.packet_size
                    if pkt.delay_ms is not None:
                        self.iv_delay.add(pkt.delay_ms)
                    if status == 'LOSS':
                        self.iv_missing += gap
                    if status == 'MISORDER':
                        self.iv_misorder += 1
                        # late arrival of a previously loss-counted packet
                        if self.iv_missing > 0:
                            self.iv_missing -= 1

                    iv_ds = self.iv_dscp_stats[pkt.dscp]
                    iv_ds.packets += 1
                    if pkt.delay_ms is not None:
                        iv_ds.delays.add(pkt.delay_ms)
                    if status == 'LOSS':
                        iv_ds.loss += gap

                    # CSV
                    if self.csv_writer:
                        self.csv_writer.writerow([
                            datetime.now().isoformat(),
                            pkt.seq,
                            f"{pkt.delay_ms:.3f}" if pkt.delay_ms is not None else "",
                            pkt.dscp,
                            dscp_to_name(pkt.dscp),
                            status,
                        ])

                    # display
                    if not self.summary_interval:
                        self._print_packet_line(pkt, status)
                    else:
                        now = time.monotonic()
                        if now - self.last_summary_time >= self.summary_interval:
                            self._print_summary()
                            self.last_summary_time = now

                except socket.timeout:
                    if self.summary_interval:
                        now = time.monotonic()
                        if now - self.last_summary_time >= self.summary_interval:
                            self._print_summary()
                            self.last_summary_time = now

        except KeyboardInterrupt:
            self._print_final_summary()
        finally:
            self.sock.close()
            if self.csv_file:
                self.csv_file.close()
            if self.sync_client:
                self.sync_client.stop()


# --- Main ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=f'mau-recv v{VERSION} - Multicast/Unicast Traffic Receiver'
    )
    parser.add_argument('-g', '--group', default='239.1.1.1',
                        help='Multicast group (default: 239.1.1.1)')
    parser.add_argument('-p', '--port', type=int, default=5005,
                        help='Data port (default: 5005)')
    parser.add_argument('-u', '--unicast', action='store_true',
                        help='Unicast mode (listen on own IP)')
    parser.add_argument('-s', '--summary', type=int,
                        help='Summary interval (seconds)')
    parser.add_argument('-sc', '--summary-compact', type=int,
                        help='Compact summary interval (seconds)')
    parser.add_argument('-l', '--log', help='CSV log file')
    parser.add_argument('--sender-ip', default=None,
                        help='Sender IP for OWD sync (required for delay measurement)')
    parser.add_argument('--sync-port', type=int, default=OWD_SYNC_PORT,
                        help=f'OWD sync port on sender (default: {OWD_SYNC_PORT})')
    parser.add_argument('--version', action='store_true', help='Version')

    args = parser.parse_args()

    if args.version:
        print(f"mau-recv v{VERSION}\n")
        return

    print(f"\n{Colors.BOLD}{Colors.BLUE}"
          f"╔═════════════════════════════════════════════════════╗{Colors.ENDC}")
    print(f"{Colors.BLUE}║  mau-recv v{VERSION} - by Ewald Jeitler {Colors.ENDC} ")
    print(f"{Colors.BLUE}"
          f"╚═════════════════════════════════════════════════════╝{Colors.ENDC}\n")



    # OWD sync
    sync_client = None
    if args.sender_ip:
        print(f"{Colors.CYAN}Synchronizing with sender {args.sender_ip}:{args.sync_port}...{Colors.ENDC}")
        sync_client = OWDSyncClient(args.sender_ip, args.sync_port)
        if sync_client.initial_sync():
            print(f"{Colors.GREEN}✓ OWD sync OK — RTT: {sync_client.rtt_ms:.2f}ms, "
                  f"offset: {sync_client.offset_us:+.1f}µs{Colors.ENDC}")
            sync_client.start_background_resync()
        else:
            print(f"{Colors.YELLOW}⚠ OWD sync failed — delay values will not be shown{Colors.ENDC}")
            sync_client = None
    else:
        print(f"{Colors.YELLOW}⚠ –sender-ip missing — delay values disabled{Colors.ENDC}")

    log_file = None
    if args.log:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOG_DIR / args.log

    multicast_group = args.group if not args.unicast else None

    # Resolve summary mode: -sc overrides -s
    summary_interval = None
    summary_compact = False
    if args.summary_compact:
        summary_interval = args.summary_compact
        summary_compact = True
    elif args.summary:
        summary_interval = args.summary

    receiver = PacketReceiver(
        multicast_group,
        args.port,
        log_file=log_file,
        summary_interval=summary_interval,
        summary_compact=summary_compact,
        sync_client=sync_client,
        unicast_mode=args.unicast,
    )
    receiver.receive_loop()


if __name__ == '__main__':
    main()