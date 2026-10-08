#!/usr/bin/env python3
"""Offline-only QMI QMUX response decoder used by this diagnostic.

This program has no Windows/serial/USB code and never opens a device.  It
accepts already-captured hexadecimal QMUX messages solely so that a result
obtained through a documented API can be inspected without replaying it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SERVICE_NAMES = {0x01: "WDS", 0x03: "NAS", 0x21: "IMSA", 0x24: "PDC"}
IMSA_MESSAGES = {0x0020: "get-ims-registration-status", 0x0021: "get-ims-services-status"}


def u16(data: bytes) -> int:
    return int.from_bytes(data, "little")


def u32(data: bytes) -> int:
    return int.from_bytes(data, "little")


def decode_qmux(frame: bytes) -> dict:
    """Decode one complete QMUX service response; reject malformed frames."""
    if len(frame) < 13:
        raise ValueError("frame is shorter than the QMUX + QMI service header")
    if frame[0] != 0x01:
        raise ValueError("not a QMUX frame (marker must be 0x01)")
    advertised = u16(frame[1:3])
    if advertised + 3 != len(frame):
        raise ValueError(f"QMUX length mismatch: header={advertised}, actual={len(frame) - 3}")
    service = frame[4]
    flags = frame[6]
    transaction_id = u16(frame[7:9])
    message_id = u16(frame[9:11])
    tlv_bytes = u16(frame[11:13])
    if 13 + tlv_bytes != len(frame):
        raise ValueError(f"QMI TLV length mismatch: header={tlv_bytes}, actual={len(frame) - 13}")
    result = {
        "qmux": {"flags": frame[3], "service": service,
                 "service_name": SERVICE_NAMES.get(service, "unknown"), "client_id": frame[5]},
        "qmi": {"flags": flags, "transaction_id": transaction_id, "message_id": message_id,
                "message_name": IMSA_MESSAGES.get(message_id, "unknown"), "tlvs": []},
    }
    pos = 13
    while pos < len(frame):
        if pos + 3 > len(frame):
            raise ValueError("truncated TLV header")
        tag, size = frame[pos], u16(frame[pos + 1:pos + 3])
        pos += 3
        if pos + size > len(frame):
            raise ValueError(f"truncated TLV 0x{tag:02X}")
        value = frame[pos:pos + size]
        pos += size
        item = {"type": f"0x{tag:02X}", "length": size, "value_hex": value.hex()}
        # Operation Result is defined by libqmi qmi-common.json as two LE uint16s.
        if tag == 0x02 and size == 4:
            item["operation_result"] = {"result": u16(value[:2]), "error": u16(value[2:])}
        # These IMSA fields are LE uint32 according to qmi-service-imsa.json.
        if service == 0x21 and size == 4 and tag in range(0x10, 0x1A):
            item["imsa_uint32"] = u32(value)
        result["qmi"]["tlvs"].append(item)
    return result


def parse_hex(text: str) -> bytes:
    compact = re.sub(r"[^0-9a-fA-F]", "", text)
    if len(compact) % 2:
        raise ValueError("hex has an odd digit count")
    return bytes.fromhex(compact)


def self_test() -> None:
    # IMSA 0x0020 response, Operation Result=success.  It is synthetic,
    # contains no subscriber/device identifier, and is not sent anywhere.
    sample = "0111000021010201002000070002040000000000"
    decoded = decode_qmux(parse_hex(sample))
    assert decoded["qmux"]["service_name"] == "IMSA"
    assert decoded["qmi"]["message_name"] == "get-ims-registration-status"
    assert decoded["qmi"]["tlvs"][0]["operation_result"] == {"result": 0, "error": 0}
    try:
        decode_qmux(parse_hex("0111000021010201002000060002040000000000"))
    except ValueError as exc:
        assert "TLV length mismatch" in str(exc)
    else:
        raise AssertionError("malformed frame was accepted")


def main() -> int:
    p = argparse.ArgumentParser(description="Offline-only QMI QMUX response decoder")
    p.add_argument("--hex", help="captured QMUX frame in hex; do not use for identifiers")
    p.add_argument("--file", type=Path, help="captured hex text file")
    p.add_argument("--self-test", action="store_true")
    ns = p.parse_args()
    if ns.self_test:
        self_test()
        print("offline decoder self-test: PASS")
        return 0
    if bool(ns.hex) == bool(ns.file):
        p.error("supply exactly one of --hex or --file (or --self-test)")
    text = ns.hex if ns.hex else ns.file.read_text(encoding="utf-8")
    print(json.dumps(decode_qmux(parse_hex(text)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
