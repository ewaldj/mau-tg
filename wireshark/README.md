# MAU Protocol — Wireshark Dissector

Lua dissector plugin for [Wireshark](https://www.wireshark.org/) that decodes the MAU traffic generator protocol used by `mau-send` and `mau-recv`.

## Protocol Format

MAU uses UDP to transmit fixed-size packets with embedded timestamps for one-way delay measurement.

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
|                                                               |
|                    Payload Padding                             |
|                   (filled with 0x58)                          |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                          CRC (32)                             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

| Offset | Length | Type | Description |
|--------|--------|------|-------------|
| 0 | 4 bytes | uint32 BE | Sequence number (starts at 0) |
| 4 | 8 bytes | uint64 BE | Timestamp in microseconds since Unix epoch |
| 12 | variable | bytes | Padding filled with `0x58` (`X`) |
| last 4 | 4 bytes | uint32 BE | CRC: `sum(all_preceding_bytes) & 0xFF` |

All multi-byte fields are **big-endian** (network byte order). The minimum UDP payload is 16 bytes (header only, no padding). The user-configured "packet size" refers to the IP wire size; the UDP payload is 28 bytes smaller (20 IP + 8 UDP header).

## Wireshark Decoded View

```
▼ MAU Protocol
    Sequence Number: 42
    Timestamp (µs): 1775400123456789
    Sender Timestamp (UTC): 2026-04-05 18:42:03.456789 UTC
    Payload: 585858585858...
    CRC: 0x00000025
    CRC Status: OK
    Wire Size (bytes): 1500
```

The info column shows a compact summary:

```
Seq=42  Len=1500B  CRC=OK
```

CRC mismatches are flagged as expert info errors and highlighted in the packet list.

## Installation

1. Find your Wireshark personal plugins directory:
   **Wireshark → Help → About Wireshark → Folders → Personal Plugins**

   Typical locations:

   | OS | Path |
   |----|------|
   | Linux | `~/.local/lib/wireshark/plugins/` |
   | macOS | `~/.local/lib/wireshark/plugins/` |
   | Windows | `%APPDATA%\Wireshark\plugins\` |

2. Copy the dissector file:

   ```bash
   # Linux / macOS
   mkdir -p ~/.local/lib/wireshark/plugins
   cp mau_protocol.lua ~/.local/lib/wireshark/plugins/
   ```

   ```powershell
   # Windows (PowerShell)
   Copy-Item mau_protocol.lua "$env:APPDATA\Wireshark\plugins\"
   ```

3. Reload: restart Wireshark or press **Ctrl+Shift+L** to reload Lua plugins.

## Usage

The dissector automatically registers on **UDP port 5005** (the default `mau-send` data port).

For a different port: right-click any UDP packet → **Decode As…** → set UDP port → select **MAU**.

### Display Filters

```
mau                          # all MAU packets
mau.seq >= 1000              # sequence number filter
mau.crc_status == "MISMATCH" # CRC errors only
```

### Capture Filter

```bash
wireshark -i eth0 -f "udp port 5005"
```

## Related

- [`mau-send`](../mau-send.py) — Multicast/Unicast/Broadcast traffic generator
- [`mau-recv`](../mau-recv.py) — Traffic receiver with OWD delay measurement

## License

MIT

## Author

ewald@jeitler.cc — [jeitler.guru](https://www.jeitler.guru)
