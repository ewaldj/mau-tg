# MAU - Multicast AND Unicast Traffic Generator v1.0

Performance multicast and unicast traffic generation and analysis tool suite with Time Sync support for accurate one-way delay measurement.

## MAU-TOOLS 

### mau-send.py - Multicast/Unicast Sender
- **Normal Mode**: Precise rate-limited packet transmission (configurable pps)
- **Burst Mode**: Maximum speed transmission (500+ Mbit/s)
- **Multicast & Unicast**: Support for both protocols
- **Time Sync**: Accurate one-way delay measurement
- **DSCP Support**: QoS tagging with automatic naming
- **Interactive Menu**: Easy configuration UI
- **Persistent Config**: Save and load settings

### mau-recv.py - Multicast/Unicast Receiver 
- **Multicast Receiver**: Join multicast groups automatically
- **Unicast Receiver**: Listen on own IP address
- **Dual Mode**: Receive both unicast and multicast simultaneously
- **Per-Packet Tracking**: Display each packet with DSCP, delay, status
- **Optional Summary**: Aggregate statistics at configurable intervals
- **DSCP Analysis**: Per-DSCP-class statistics and delay tracking
- **CSV Logging**: Export detailed packet data
- **Loss Detection**: Track missing and out-of-order packets

### mau-time v1.0 - Time Sync Server
Central time synchronization server providing relative time reference for accurate delay measurement across distributed systems.

**Key Features:**
- Sends relative time (microseconds since server start)
- Consistent time reference for all clients
- Tracks sender and receiver connections
- Thread-based concurrent client handling
- Automatic fallback from port 443 to 8443


## Installation

```bash
# Make executable
chmod +x mau-time mau-send mau-recv

# Run directly
./mau-time
./mau-send
./mau-recv
```

Or copy to PATH:
```bash
sudo cp mau-time mau-send mau-recv /usr/local/bin/
mau-time
mau-send
mau-recv
```

## Quick Start

### Terminal 1: Start Time Sync Server
```bash
mau-time
# or with custom port
mau-time --port 8443
```

### Terminal 2: Send Multicast Traffic
```bash
# Interactive menu
mau-send

# Or direct with CLI
mau-send -d 239.1.1.1 -p 5005 -s 1400 --pps 5000

# Burst mode (max speed)
mau-send -d 239.1.1.1 -p 5005 -s 1400 --burst
```

### Terminal 3: Receive and Analyze
```bash
# Multicast reception
mau-recv -g 239.1.1.1 -p 5005

# With 10-second summary intervals
mau-recv -g 239.1.1.1 -p 5005 -s 10

# Unicast mode (listen on own IP)
mau-recv -u -p 5005

# With CSV logging
mau-recv -g 239.1.1.1 -p 5005 -l traffic.csv
```

## Command Line Options

### mau-time

```
-p, --port PORT             Listen port (default: 443, fallback: 8443)
--version                   Show version
```

### mau-send

```
-d, --destination ADDRESS   Destination address (default: 239.1.1.1)
-p, --port PORT             Destination port (default: 5005)
-s, --size BYTES            Packet size (default: 256)
--pps RATE                  Packets per second (default: 10)
--dscp VALUE                DSCP value (0-63, default: 0)
--sync-server HOST          Time Sync Server (default: localhost)
--sync-port PORT            Time Sync Port (default: 443)
--burst                     Burst mode: send as fast as possible
-m, --menu                  Interactive configuration menu
--version                   Show version
```

### mau-recv

```
-g, --group ADDRESS         Multicast group (default: 239.1.1.1)
-p, --port PORT             Listen port (default: 5005)
-u, --unicast               Unicast mode (listen on own IP)
-s, --summary SECONDS       Summary interval (optional, per-packet default)
-l, --log FILE              CSV log file (optional)
--sync-server HOST          Time Sync Server (default: localhost)
--sync-port PORT            Time Sync Port (default: 443)
--version                   Show version
```

## Examples

### Multicast Throughput Test
```bash
# Sender: 1400 byte packets at 10,000 pps = 112 Mbit/s
mau-send -d 239.1.1.1 -p 5005 -s 1400 --pps 10000

# Receiver with 10-second summaries
mau-recv -g 239.1.1.1 -p 5005 -s 10
```

### Burst Mode Performance Test
```bash
# Sender: Maximum speed (500+ Mbit/s possible)
mau-send -d 239.1.1.1 -p 5005 -s 1400 --burst

# Receiver
mau-recv -g 239.1.1.1 -p 5005 -s 5
```

### Unicast Stream
```bash
# Sender to specific IP
mau-send -d 192.168.1.100 -p 5005 -s 1400 --pps 1000

# Receiver on that IP
mau-recv -u -p 5005
```

### QoS Testing with DSCP
```bash
# Sender with EF (Expedited Forwarding)
mau-send -d 239.1.1.1 -p 5005 -s 1400 --dscp 46 --pps 5000

# Receiver - shows DSCP in output
mau-recv -g 239.1.1.1 -p 5005 -s 10
```

### Data Logging
```bash
# Receiver logs to CSV
mau-recv -g 239.1.1.1 -p 5005 -l traffic.csv

# CSV contains: Timestamp, Seq, Delay_ms, DSCP, DSCP_Name, Status
```

## Output Format

### Per-Packet Display
```
HH:MM:SS Seq:      0 Size:  1400 DSCP:EF     Delay:   5.47ms OK       Loss:  0.00%
HH:MM:SS Seq:      1 Size:  1400 DSCP:EF     Delay:   5.87ms OK       Loss:  0.00%
HH:MM:SS Seq:      2 Size:  1400 DSCP:AF21   Delay:   5.59ms OK       Loss:  0.00%
```

### Summary Display (every N seconds)
```
[00:00:10] Pkts:  10000 Tput:112.00Mbps Delay:  5.23ms Loss:  0.00% Misorder:  0
  └─ BE    : 5000 pkts (50.0%) Delay:  5.25ms
  └─ EF    : 5000 pkts (50.0%) Delay:  5.21ms
```

### Burst Mode Statistics
```
╔════════════════════════════════════
║   BURST Statistics
║   Time: 60.0s
║   Packets: 600,000,000
║   Rate: 10,000,000 pps
║   Throughput: 112.0 Mbit/s
║   Data: 840.0 MB
╚════════════════════════════════════
```

## Configuration

Settings are stored in:
- **mau-send**: `~/.mau-send/config.json`
- **mau-recv**: Uses command-line args (no persistent config)

### Edit Sender Config
```bash
cat ~/.mau-send/config.json
```

Example config:
```json
{
  "destination_address": "239.1.1.1",
  "destination_port": 5005,
  "packet_size": 1400,
  "packets_per_second": 10000,
  "dscp_value": 46,
  "ttl": 32,
  "time_sync_server": "localhost",
  "time_sync_port": 443
}
```

## DSCP Values

Common DSCP values (divide by 2 for cos value):

| DSCP | Name | Description |
|------|------|-------------|
| 0    | BE   | Best Effort |
| 8    | CS1  | Class Selector 1 |
| 10   | AF11 | Assured Forwarding 1,1 |
| 16   | CS2  | Class Selector 2 |
| 18   | AF21 | Assured Forwarding 2,1 |
| 24   | CS3  | Class Selector 3 |
| 26   | AF31 | Assured Forwarding 3,1 |
| 32   | CS4  | Class Selector 4 |
| 34   | AF41 | Assured Forwarding 4,1 |
| 40   | CS5  | Class Selector 5 |
| 46   | EF   | Expedited Forwarding |
| 48   | CS6  | Class Selector 6 |
| 56   | CS7  | Class Selector 7 |

## Packet Format

```
[0:4]   Sequence Number        (uint32)
[4:12]  Timestamp µs           (uint64, relative to server start)
[12:-4] Payload                (variable, 'X' bytes)
[-4:]   CRC32                  (uint32)
```

## Performance Notes

### Maximum Throughput

With **Burst Mode** on Apple M3 with Gigabit Ethernet:
- **500+ Mbit/s** achieved
- Limited by kernel UDP socket throughput
- Larger packets (1400 bytes) = better efficiency

### Optimal Settings

| Scenario | Packet Size | Rate | Result |
|----------|------------|------|--------|
| Voice/Video | 256 bytes | 100 pps | 20 Kbit/s |
| Audio Stream | 1024 bytes | 1000 pps | 8 Mbit/s |
| Video Stream | 1400 bytes | 5000 pps | 56 Mbit/s |
| Line Rate Test | 1400 bytes | --burst | 500+ Mbit/s |

## Requirements

- Python 3.6+
- Standard library only (no external dependencies)
- Network with multicast support (for multicast testing)

