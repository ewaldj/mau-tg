# MAU — Multicast/AND/Unicast Traffic Generator & Analyzer

A lightweight, dependency-free Python toolkit for generating and analyzing network traffic with accurate one-way delay (OWD) measurement. Designed for network engineers who need to verify QoS policies, measure path latency, detect packet loss, and stress-test links.

## Features

- **Multicast, Unicast & Broadcast** — send to any destination type
- **One-Way Delay Measurement** — NTP-style 4-timestamp protocol, no third-party time server required
- **Per-Interval Statistics** — throughput, delay (avg/min/max), loss, DSCP tracking
- **Burst Mode** — saturate links at max speed or with a configurable bandwidth limit
- **DSCP/QoS Marking** — set and track DiffServ code points end-to-end
- **Sender Restart Detection** — receiver automatically resets sequence tracking
- **CSV Export** — log every packet for post-analysis
- **Wireshark Dissector** — included Lua plugin for protocol inspection
- **Zero Dependencies** — Python 3.10+ standard library only
- **Cross-Platform** — tested on Linux (x86/ARM), macOS, Raspberry Pi OS

## Installation

```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/ewaldj/mau-tg/refs/heads/main/e-install.sh)"
```
 
or 

```bash
git clone https://github.com/ewaldj/mau.git
cd mau
chmod +x mau-send.py mau-recv.py
```

## Quick Start

```bash
# Terminal 1: Start sender (includes embedded time sync server)
./mau-send.py -d 239.1.1.1 -p 5005 --pps 100

# Terminal 2: Start receiver with OWD delay measurement
./mau-recv.py -g 239.1.1.1 -p 5005 --sender-ip 192.168.1.10 -s 5
```

## mau-send

Traffic generator with interactive menu and CLI modes.

### Interactive Menu

```bash
./mau-send.py
```

```
╔════════════════════════════════════╗
║  mau-send v0.37 - Configuration
╚════════════════════════════════════╝

Current Settings:
  1. Destination Address:    239.1.1.1
  2. Destination Port:       5005
  3. Packet Size:            1500 bytes
  4. Rate (pps):             100.0
  5. DSCP Value:             46
  6. OWD Sync Port:          5556
  7. TTL:                    32
  8. Burst Bandwidth Limit:  unlimited

  0. START (Normal Mode)
  b. BURST-MODE
  s. Save Config
  q. Exit
```

Ctrl+C during sending returns to the menu. The OWD sync server starts immediately and runs throughout.

### CLI Mode

```bash
# Constant rate
./mau-send.py -d 239.1.1.1 -p 5005 -s 1500 --pps 1000 --dscp 46

# Burst: maximum speed
./mau-send.py -d 10.0.0.5 --burst

# Burst: limited to 200 Mbit/s
./mau-send.py -d 10.0.0.5 -s 1500 --burst --burst-mbps 200

# Broadcast
./mau-send.py -d 172.17.17.255 -p 5005 --pps 50
```

### CLI Options

| Option | Description |
|--------|-------------|
| `-d`, `--destination` | Destination IP address |
| `-p`, `--port` | Destination UDP port |
| `-s`, `--size` | Packet size in bytes (wire size, including IP/UDP headers) |
| `--pps` | Packets per second |
| `--dscp` | DSCP value (0–63) |
| `--burst` | Burst mode (send as fast as possible) |
| `--burst-mbps` | Bandwidth limit for burst mode in Mbit/s (0 = unlimited) |
| `--sync-port` | OWD time sync server port (default: 5556) |
| `-m`, `--menu` | Force interactive menu |
| `--version` | Show version |

### Packet Size

The `--size` / menu option specifies the **wire size** (Layer 3 IP packet). The tool automatically subtracts the 28-byte IP/UDP header overhead. For example, entering 1500 produces a 1472-byte UDP payload, resulting in exactly 1500 bytes on the wire — compatible with standard 1500-byte MTU without fragmentation.

### Configuration

Settings are persisted to `~/.mau-send/config.json` when saved via the menu.

## mau-recv

Traffic receiver with real-time statistics, OWD measurement, and CSV logging.

### Usage

```bash
# Multicast with per-packet display
./mau-recv.py -g 239.1.1.1 -p 5005 --sender-ip 192.168.1.10

# Summary every 5 seconds
./mau-recv.py -g 239.1.1.1 -p 5005 --sender-ip 192.168.1.10 -s 5

# Unicast mode
./mau-recv.py -u -p 5005 --sender-ip 192.168.1.10 -s 2

# With CSV logging
./mau-recv.py -g 239.1.1.1 --sender-ip 192.168.1.10 -s 10 -l capture.csv
```

### Per-Packet Display (default)

```
10:45:16 | Seq:    27 | Size: 1500 | DSCP:EF    | Delay:  0.42ms | OK    | Loss:  0.00%
10:45:16 | Seq:    28 | Size: 1500 | DSCP:EF    | Delay:  0.38ms | OK    | Loss:  0.00%
```

### Interval Summary (`-s`)

```
20:47:37 |      0–2s |  695.81 Mbps |  1500B | DSCP:BE    | OK     | Pkt:    58023 | Loss: 0.00% Pkt:     0 | Dly(ms): avg:0.42 min:0.33 max:0.55
20:47:39 |      2–4s |  697.24 Mbps |  1500B | DSCP:BE    | OK     | Pkt:    58104 | Loss: 0.00% Pkt:     0 | Dly(ms): avg:0.28 min:0.19 max:0.96
20:47:41 |      4–6s |    0.00 Mbps |  1500B | DSCP:BE    | no traffic received
```

All values are calculated **per interval** and reset after each line. The final summary on Ctrl+C shows lifetime totals.

### CLI Options

| Option | Description |
|--------|-------------|
| `-g`, `--group` | Multicast group (default: 239.1.1.1) |
| `-p`, `--port` | Listen port (default: 5005) |
| `-u`, `--unicast` | Unicast mode (bind to own IP) |
| `-s`, `--summary` | Summary interval in seconds (default: per-packet) |
| `-l`, `--log` | CSV log file (saved to `~/.mau-recv/`) |
| `--sender-ip` | Sender IP for OWD time sync (required for delay values) |
| `--sync-port` | OWD sync port on sender (default: 5556) |
| `--version` | Show version |

### Delay Measurement

Without `--sender-ip`, delay values are shown as `n/a`. When specified, the receiver performs an NTP-style 4-timestamp handshake with the sender's embedded sync server:

1. Warmup phase (3 packets, discarded)
2. Best-of-5 measurement (lowest RTT selected)
3. Background resync every 30 seconds to track clock drift

The accuracy depends on path symmetry. For symmetric paths the OWD is exact; for asymmetric paths the error is half the asymmetry — typically well within ±1–2ms on LAN/WAN.

## Protocol

MAU uses a custom UDP protocol with embedded timestamps:

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                      Sequence Number (32)                     |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
|                   Timestamp in µs (64)                        |
|                    CLOCK_REALTIME                              |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                      Payload Padding                          |
|                    (filled with 0x58)                         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                          CRC (32)                             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

| Field | Offset | Size | Format | Description |
|-------|--------|------|--------|-------------|
| Sequence | 0 | 4 bytes | uint32 BE | Packet counter, starts at 0 |
| Timestamp | 4 | 8 bytes | uint64 BE | Microseconds since Unix epoch |
| Padding | 12 | variable | bytes | Filled with `0x58` (`X`) |
| CRC | last 4 | 4 bytes | uint32 BE | `sum(preceding_bytes) & 0xFF` |

Minimum UDP payload: 16 bytes. All fields are big-endian.

### OWD Time Sync Protocol

The sender runs an embedded UDP time sync server (default port 5556). Receivers measure their clock offset using a 4-timestamp exchange:

```
Receiver                          Sender
   |--- REQ {t1_ns} ------------->|  T1: receiver TX
   |                              |  T2: sender RX
   |<-- RSP {t1,t2,t3_ns} -------|  T3: sender TX
   |                              |  T4: receiver RX
```

```
RTT    = (T4 - T1) - (T3 - T2)
Offset = ((T2 - T1) + (T3 - T4)) / 2
OWD    = receiver_now - sender_timestamp + offset
```

Wire format: JSON over UDP (`{"type":"req","t1_ns":<int>}` / `{"type":"rsp","t1_ns":...,"t2_ns":...,"t3_ns":...}`).

## Wireshark Integration

A Lua dissector is included for protocol analysis. See [mau_protocol.lua](wireshark/mau_protocol.lua) and its [README](wireshark/README.md) for installation and usage.

## Examples

### QoS Verification

Verify that DSCP EF (46) traffic receives priority treatment:

```bash
# Sender: mark traffic as EF
./mau-send.py -d 239.1.1.1 -s 1500 --pps 1000 --dscp 46

# Receiver: check delay and loss
./mau-recv.py -g 239.1.1.1 --sender-ip 10.0.0.1 -s 5
```

### Link Stress Test

Saturate a link at a specific bandwidth:

```bash
# 500 Mbit/s burst with 1500-byte packets
./mau-send.py -d 10.0.0.5 -s 1500 --burst --burst-mbps 500
```

### Multipath / Asymmetry Detection

Compare OWD in both directions by running sender+receiver on each end:

```bash
# Host A → Host B
hostA$ ./mau-send.py -d 10.0.0.2 --pps 10
hostB$ ./mau-recv.py -u --sender-ip 10.0.0.1 -s 10

# Host B → Host A
hostB$ ./mau-send.py -d 10.0.0.1 --pps 10
hostA$ ./mau-recv.py -u --sender-ip 10.0.0.2 -s 10
```

### Broadcast Testing

```bash
# Subnet broadcast /24 
./mau-send.py -d 172.17.17.255 -p 5005 -s 256 --pps 10
```

## Project Structure

```
├── mau-send.py          # Traffic generator (sender + time sync server)
├── mau-recv.py          # Traffic receiver with OWD measurement
├── wireshark/
│   ├── mau_protocol.lua # Wireshark Lua dissector
│   └── README.md        # Dissector documentation
└── README.md            # This file
```

## Requirements

- Python 3.10+
- No external packages

## Author

Ewald Jeitler — [www.jeitler.guru](https://www.jeitler.guru)
