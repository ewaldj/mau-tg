-- mau_protocol.lua — Wireshark dissector for mau-send/mau-recv protocol
-- by ewald@jeitler.cc 2026 https://www.jeitler.guru
--
-- Install:
--   Copy this file to your Wireshark plugins directory:
--     Linux:   ~/.local/lib/wireshark/plugins/
--     macOS:   ~/.local/lib/wireshark/plugins/
--     Windows: %APPDATA%\Wireshark\plugins\
--   Or: Wireshark → Help → About → Folders → Personal Plugins
--   Then restart Wireshark or Ctrl+Shift+L to reload Lua plugins.
--
-- The dissector registers on UDP port 5005 by default.
-- To use a different port: right-click a packet → Decode As → UDP port → MAU
--
-- Packet format (UDP payload):
--   [0:4]   Sequence Number   uint32 big-endian
--   [4:12]  Timestamp (µs)    uint64 big-endian (CLOCK_REALTIME since epoch)
--   [12:N-4] Payload padding  filled with 0x58 ('X')
--   [N-4:N] CRC              uint32 big-endian (sum of bytes[0:N-4] & 0xFF)

local mau_proto = Proto("mau", "MAU Traffic Generator Protocol")

-- Field definitions
local f_seq       = ProtoField.uint32("mau.seq",       "Sequence Number", base.DEC)
local f_ts        = ProtoField.uint64("mau.timestamp",  "Timestamp (µs)",  base.DEC)
local f_payload   = ProtoField.bytes ("mau.payload",    "Payload")
local f_crc       = ProtoField.uint32("mau.crc",        "CRC",             base.HEX)
local f_crc_valid = ProtoField.string("mau.crc_status", "CRC Status")
local f_delay     = ProtoField.string("mau.delay",      "Sender Timestamp (UTC)")
local f_wire_size = ProtoField.uint32("mau.wire_size",  "Wire Size (bytes)", base.DEC)

mau_proto.fields = { f_seq, f_ts, f_payload, f_crc, f_crc_valid, f_delay, f_wire_size }

-- Expert info for CRC errors
local ef_crc_bad = ProtoExpert.new("mau.crc_bad", "MAU CRC mismatch",
                                    expert.group.CHECKSUM, expert.severity.ERROR)
mau_proto.experts = { ef_crc_bad }

-- Minimum packet size: 4(seq) + 8(ts) + 4(crc) = 16
local MIN_LEN = 16

function mau_proto.dissector(buffer, pinfo, tree)
    local buf_len = buffer:len()
    if buf_len < MIN_LEN then return 0 end

    pinfo.cols.protocol:set("MAU")

    local subtree = tree:add(mau_proto, buffer(), "MAU Protocol")

    -- Sequence number (bytes 0-3)
    local seq = buffer(0, 4):uint()
    subtree:add(f_seq, buffer(0, 4))

    -- Timestamp (bytes 4-11) — uint64 microseconds since epoch
    local ts_raw = buffer(4, 8):uint64()
    subtree:add(f_ts, buffer(4, 8))

    -- Convert timestamp to human-readable UTC
    local ts_sec = tonumber(tostring(ts_raw)) / 1000000.0
    if ts_sec > 0 then
        local time_str = os.date("!%Y-%m-%d %H:%M:%S", math.floor(ts_sec))
        local frac = ts_sec - math.floor(ts_sec)
        local full_str = string.format("%s.%06d UTC", time_str, math.floor(frac * 1000000))
        subtree:add(f_delay, buffer(4, 8), full_str)
    end

    -- Payload (bytes 12 to N-4)
    local payload_len = buf_len - MIN_LEN
    if payload_len > 0 then
        subtree:add(f_payload, buffer(12, payload_len))
    end

    -- CRC (last 4 bytes)
    local crc_offset = buf_len - 4
    local crc_received = buffer(crc_offset, 4):uint()
    local crc_item = subtree:add(f_crc, buffer(crc_offset, 4))

    -- Verify CRC: sum of all bytes before CRC field, masked to 0xFF
    local crc_calc = 0
    for i = 0, crc_offset - 1 do
        crc_calc = crc_calc + buffer(i, 1):uint()
    end
    crc_calc = bit.band(crc_calc, 0xFF)

    if crc_calc == crc_received then
        subtree:add(f_crc_valid, buffer(crc_offset, 4), "OK"):set_generated(true)
    else
        local bad = subtree:add(f_crc_valid, buffer(crc_offset, 4),
                                string.format("MISMATCH (expected 0x%02x)", crc_calc))
        bad:set_generated(true)
        bad:add_tvb_expert_info(ef_crc_bad, buffer(crc_offset, 4))
    end

    -- Wire size (UDP payload + 28 bytes IP/UDP overhead)
    local wire = buf_len + 28
    subtree:add(f_wire_size, buffer(), wire):set_generated(true)

    -- Info column
    pinfo.cols.info:set(string.format("Seq=%d  Len=%dB  CRC=%s",
        seq, wire, crc_calc == crc_received and "OK" or "BAD"))

    return buf_len
end

-- Register on default UDP port 5005
local udp_table = DissectorTable.get("udp.port")
udp_table:add(5005, mau_proto)
