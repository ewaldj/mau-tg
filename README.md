# MAU — Multicast/AND/Unicast Traffic Generator & Analyzer

A lightweight, dependency-free Python toolkit for generating and analyzing network traffic with accurate one-way delay (OWD) measurement. Designed for network engineers who need to verify QoS policies, measure path latency, detect packet loss, and stress-test links.

## Features

- **Multicast, Unicast & Broadcast** — send to any destination type
- **One-Way Delay Measurement** — NTP-style 4-timestamp protocol, no third-party time server required
- **Kernel-Level RX Timestamping** — uses `SO_TIMESTAMPNS` on Linux to keep Python/GIL scheduling jitter out of the delay measurement
- **Drift-Aware Clock Tracking** — periodic resync (default 3s, configurable) with a clock-filter (outlier rejection) and linear drift extrapolation between syncs
- **Per-Interval Statistics** — throughput, delay (avg/min/max), loss, DSCP tracking
- **Burst Mode** — saturate links at max speed or with a configurable bandwidth limit
- **DSCP/QoS Marking** — set and track DiffServ code points end-to-end
- **Don't Fragment (DF) Bit** — optionally set DF on all packets (Linux)
- **Sender Restart Detection** — receiver automatically resets sequence tracking
- **CSV Export** — log every packet for post-analysis (raw, unclamped delay values)
- **Wireshark Dissector** — included Lua plugin for data-packet protocol inspection
- **Zero Dependencies** — Python 3.10+ standard library only
- **Cross-Platform** — tested on Linux (x86/ARM), macOS, Raspberry Pi OS (kernel RX timestamping is Linux-only; falls back cleanly elsewhere)

## Installation / Update

```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/ewaldj/mau-tg/refs/heads/main/e-install.sh)"
```

or

```bash
git clone https://github.com/ewaldj/mau-tg.git
cd mau-tg
chmod +x mau-send.py mau-recv.py
```

> **Note:** the repository name in this section was previously shown as `ewaldj/mau.git`, which didn't match `e-install.sh` (which pulls from `ewaldj/mau-tg`). Fixed here to match the installer — please correct if the actual repo is named differently.

> **Compatibility:** `mau-send` and `mau-recv` must run matching major versions of the OWD sync protocol. Versions **0.51+** use a binary (`struct`) sync protocol; earlier versions used JSON. A 0.51+ receiver will not sync against a pre-0.51 sender and vice versa (the data-plane protocol on the traffic port is unaffected and always compatible). Keep both tools updated together.

## Quick Start

```bash
# Terminal 1: Start sender (includes embedded time sync server)
./mau-send.py -d 239.1.1.1 -p 5005 --pps 100

# Terminal 2: Start receiver with OWD delay measurement
./mau-recv.py -g 239.1.1.1 -p 5005 --sender-ip 192.168.1.10 -s 5
```

## mau-send

Traffic generator with interactive menu and CLI modes, including an embedded OWD time-sync server.

### Interactive Menu

```bash
./mau-send.py
```

```
╔══════════════════════════════════════════════════════
║  mau-send - Configuration
╚══════════════════════════════════════════════════════

Current Settings:
  1. Destination Address:    239.1.1.1
  2. Destination Port:       5005
  3. Packet Size:            1500 bytes
  4. Rate (pps):             100.0
  5. DSCP Value:             46
  6. OWD Sync Port:          5556
  7. TTL:                    32
  8. Burst Bandwidth Limit:  unlimited
  9. Don't Fragment (DF):    off

  0. START (Normal Mode)
  b. BURST-MODE
  s. Save Config
  e. Exit
```

Ctrl+C during sending returns to the menu. The OWD sync server starts immediately (before the menu) and runs throughout.

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

# Set the Don't Fragment bit (Linux only)
./mau-send.py -d 10.0.0.5 -s 1500 --pps 100 --df
```

### CLI Options

| Option | Description |
|--------|-------------|
| `-d`, `--destination` | Destination IP address |
| `-p`, `--port` | Destination UDP port |
| `-s`, `--size` | Packet size in bytes (wire size, including IP/UDP headers) |
| `--pps` | Packets per second |
| `--dscp` | DSCP value (0–63) |
| `--burst` | Burst mode (send as fast as possible, or paced with `--burst-mbps`) |
| `--burst-mbps` | Bandwidth limit for burst mode in Mbit/s (0 = unlimited) |
| `--df` | Set the Don't Fragment (DF) bit on all packets (Linux only) |
| `--sync-port` | OWD time sync server port (default: 5556) |
| `-m`, `--menu` | Force interactive menu |
| `--version` | Show version |

Running with no arguments (and without `--burst`) also opens the interactive menu.

### Packet Size

The `--size` / menu option specifies the **wire size** (Layer 3 IP packet). The tool automatically subtracts the 28-byte IP/UDP header overhead. For example, entering 1500 produces a 1472-byte UDP payload, resulting in exactly 1500 bytes on the wire — compatible with standard 1500-byte MTU without fragmentation.

### Configuration

Settings are persisted to `~/.mau-send/config.json` when saved via the menu (`s`).

## mau-recv

Traffic receiver with real-time statistics, OWD measurement, and CSV logging.

### Usage

```bash
# Multicast with per-packet display
./mau-recv.py -g 239.1.1.1 -p 5005 --sender-ip 192.168.1.10

# Summary every 5 seconds
./mau-recv.py -g 239.1.1.1 -p 5005 --sender-ip 192.168.1.10 -s 5

# Compact summary every 1 second (no timestamp/size columns)
./mau-recv.py -g 239.1.1.1 -p 5005 --sender-ip 192.168.1.10 -sc 1

# Unicast mode
./mau-recv.py -u -p 5005 --sender-ip 192.168.1.10 -s 2

# With CSV logging
./mau-recv.py -g 239.1.1.1 --sender-ip 192.168.1.10 -s 10 -l capture.csv

# Custom resync interval (default: 3s)
./mau-recv.py -g 239.1.1.1 --sender-ip 192.168.1.10 -s 5 --resync-interval 30
```

### Per-Packet Display (default)

```
18:15:59 | Seq:    21 | Size:  256 | DSCP:EF    | Delay:   0.25ms | OK    | Loss:  0.00%
18:15:59 | Seq:    22 | Size:  256 | DSCP:EF    | Delay:   0.30ms | OK    | Loss:  0.00%
```

A `~` in place of the leading space before the delay value (e.g. `Delay:~  0.00ms`) marks a reading that measured negative and was floored to 0 for display — see [Delay Measurement](#delay-measurement) below. The CSV log (`-l`) always keeps the raw, unclamped value.

### Interval Summary (`-s`)

```
20:47:37 |      0–2s |  695.81 Mbps |  1500B | DSCP:BE    | OK     | Pkt:    58023 | Loss: 0.00% Pkt:     0 | Dly(ms): avg:0.42 min:0.33 max:0.55
20:47:39 |      2–4s |  697.24 Mbps |  1500B | DSCP:BE    | OK     | Pkt:    58104 | Loss: 0.00% Pkt:     0 | Dly(ms): avg:0.28 min:0.19 max:0.96
20:47:41 |      4–6s |    0.00 Mbps |  1500B | DSCP:BE    | no traffic received
```

### Compact Interval Summary (`-sc`)

A narrower one-line form (no timestamp, size or full DSCP columns) meant for tmux panes / `muxpi`-style multi-stream layouts:

```
      0–1s |    0.04 Mbps | BE    | OK   | Pkt:       21 | LPkt:      0 | Dly:0.29
      1–2s |    0.04 Mbps | BE    | OK   | Pkt:       20 | LPkt:      0 | Dly:0.34
```

All values are calculated **per interval** and reset after each line. The final summary on Ctrl+C shows lifetime totals.

### CLI Options

| Option | Description |
|--------|-------------|
| `-g`, `--group` | Multicast group (default: 239.1.1.1) |
| `-p`, `--port` | Listen port (default: 5005) |
| `-u`, `--unicast` | Unicast mode (bind to own IP) |
| `-s`, `--summary` | Summary interval in seconds (default: per-packet) |
| `-sc`, `--summary-compact` | Compact summary interval in seconds (overrides `-s`) |
| `-l`, `--log` | CSV log file (saved to `~/.mau-recv/`) |
| `--sender-ip` | Sender IP for OWD time sync (required for delay values) |
| `--sync-port` | OWD sync port on sender (default: 5556) |
| `--resync-interval` | OWD resync interval in seconds (default: 3) |
| `--version` | Show version |

### Delay Measurement

Without `--sender-ip`, delay values are shown as `n/a`. When specified, the receiver performs an NTP-style 4-timestamp handshake with the sender's embedded sync server:

1. Warmup phase (3 packets, discarded)
2. Initial sync: 16 samples, filtered by an NTP-style clock filter (median/MAD outlier rejection, then lowest-RTT sample selected)
3. Background resync every 3 seconds by default (`--resync-interval`), 8 samples per round, same clock filter
4. Between resyncs, the offset is **extrapolated** using a tracked linear drift rate rather than held flat as a step function
5. On Linux, both the sync exchange and data-packet reception use kernel-level RX timestamps (`SO_TIMESTAMPNS`) instead of a Python-level `time.time_ns()` call, removing scheduler/GIL jitter from the measurement

The accuracy depends on path symmetry — this is a fundamental limit of any two-way exchange without a shared external clock (GPS/PTP), not something software can fully correct. On an asymmetric path the offset error is roughly half the asymmetry, which can occasionally make a true near-zero delay measure very slightly negative; these readings are floored to 0 for on-screen display (marked with `~`) while the CSV log keeps the raw value for analysis.

## Protocol

MAU uses a custom UDP protocol with embedded timestamps for the data plane.

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                      Sequence Number (32)                     |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
|                   Timestamp in µs (64)                        |
|                    CLOCK_REALTIME                             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                      Payload Padding                          |
|                    (filled with 0x58)                         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                          CRC (32)                              |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

| Field | Offset | Size | Format | Description |
|-------|--------|------|--------|-------------|
| Sequence | 0 | 4 bytes | uint32 BE | Packet counter, starts at 0 |
| Timestamp | 4 | 8 bytes | uint64 BE | Microseconds since Unix epoch |
| Padding | 12 | variable | bytes | Filled with `0x58` (`X`) |
| CRC | last 4 | 4 bytes | uint32 BE | `sum(preceding_bytes) & 0xFF` |

Minimum UDP payload: 16 bytes. All fields are big-endian. **This format is unchanged since the initial release** — the Wireshark dissector below stays valid across versions.

### OWD Time Sync Protocol

The sender runs an embedded UDP time sync server (default port 5556, one instance per `mau-send` process — see [Running Multiple Instances](#running-multiple-instances-on-one-host) below). Receivers measure their clock offset using a 4-timestamp exchange:

```
Receiver                          Sender
   |--- REQ {t1_ns} ------------->|  T1: receiver TX
   |                              |  T2: sender RX
   |<-- RSP {t1,t2,t3_ns} --------|  T3: sender TX
   |                              |  T4: receiver RX
```

```
RTT    = (T4 - T1) - (T3 - T2)
Offset = ((T2 - T1) + (T3 - T4)) / 2
OWD    = receiver_now - sender_timestamp + offset
```

**Wire format (v0.51+): fixed-size binary (`struct`), not JSON.**

| Message | Size | Layout |
|---------|------|--------|
| Request | 9 bytes | `!B` type (`0x01`) + `!Q` t1_ns |
| Response | 25 bytes | `!B` type (`0x02`) + `!Q` t1_ns + `!Q` t2_ns + `!Q` t3_ns |

All integers big-endian. A packet of the wrong size or with an unrecognized type byte is silently discarded — this also means the sync port safely ignores stray/foreign UDP traffic instead of raising a decode error. (Versions before 0.51 used JSON: `{"type":"req","t1_ns":<int>}` / `{"type":"rsp","t1_ns":...,"t2_ns":...,"t3_ns":...}` — incompatible with 0.51+, see the Compatibility note above.)

### Running Multiple Instances on One Host

Each `mau-send` process embeds its own OWD sync server. If you run several `mau-send` instances **on the same host** (e.g. several parallel DSCP test streams) without giving each one a distinct `--sync-port`, they will all bind the same UDP port without raising an error (the socket uses `SO_REUSEADDR`) — but only one of them will actually receive sync requests; the kernel decides which, and it's implementation-defined. On a single host this typically doesn't corrupt the measured offset (all instances share the same system clock), but it does make the "✓ OWD sync server running" messages from the other instances misleading. Give each concurrently-running sender its own `--sync-port`, the same way you already give each its own data `-p` port.

## Wireshark Integration

Two Lua dissectors are included: [mau_protocol.lua](wireshark/mau_protocol.lua) for the data-packet protocol (UDP port 5005) and [mau_owd_sync_protocol.lua](wireshark/mau_owd_sync_protocol.lua) for the OWD clock-sync exchange (UDP port 5556, v0.51+ binary format only). See the [Wireshark README](wireshark/README.md) for installation and usage of both.

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
├── mau-send.py           # Traffic generator (sender + time sync server)
├── mau-recv.py           # Traffic receiver with OWD measurement
├── e-install.sh          # One-line installer/updater (fetches from GitHub)
├── wireshark/
│   ├── mau_protocol.lua           # Wireshark Lua dissector (data-packet protocol)
│   ├── mau_owd_sync_protocol.lua  # Wireshark Lua dissector (OWD sync protocol, v0.51+)
│   └── README.md                  # Dissector documentation
├── LICENSE
└── README.md              # This file
```

## Requirements

- Python 3.10+
- No external packages
- Kernel-level RX timestamping (`SO_TIMESTAMPNS`) requires Linux; other platforms fall back automatically to a slightly noisier userspace timestamp

## Author

Ewald Jeitler — [www.jeitler.guru](https://www.jeitler.guru)
