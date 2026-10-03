#!/usr/bin/env python3
"""Pure-stdlib packer/unpacker for the OpenAppFilter FWXB feature format.

Format (verified against open-app-filter/src/fwx_feature.c/.h):

  Header (24 bytes, all little-endian):
    offset 0  : magic      4B  b'FWXB'
    offset 4  : version    1B  FEATURE_FORMAT_VERSION = 1
    offset 5  : algorithm  1B  FEATURE_ALGORITHM_XTEA_CTR = 1
    offset 6  : header_size 2B le16 = 24
    offset 8  : plain_len  4B le32
    offset 12 : crc        4B le32  (zlib crc32 of the PLAINTEXT)
    offset 16 : nonce      8B le64

  Body = XTEA-CTR over the plaintext (symmetric: encrypt == decrypt):
    key words feature_key[4] = {0x8f4c29a1, 0x73b6d502, 0xc14e87f3, 0x2ad95b60}
    standard XTEA, 32 rounds, delta 0x9e3779b9;
    v0 key index = sum & 3;  v1 key index = (sum >> 11) & 3 (AFTER sum += delta)
    CTR: counter starts at nonce (u64). Per 8-byte block:
      block[0] = lo32(counter), block[1] = hi32(counter)
      XTEA-encrypt block in place
      stream = le32(block[0]) || le32(block[1])   (LO WORD FIRST, little-endian)
      XOR stream with up to 8 data bytes; counter += 1

  crc = standard zlib crc32 (init 0xffffffff, reflected poly 0xedb88320,
        final xor 0xffffffff) over the PLAINTEXT == C's feature_crc32().

  FWX_FEATURE_MAX_SIZE = 20 MiB.

CLI:
  python3 fwxb_pack.py decrypt <in.bin> <out.txt>
  python3 fwxb_pack.py encrypt <in.txt> <out.bin> [nonce]
"""

import hashlib
import os
import secrets
import struct
import sys
import zlib

MAGIC = b"FWXB"
FORMAT_VERSION = 1
ALGORITHM_XTEA_CTR = 1
HEADER_SIZE = 24
MAX_SIZE = 20 * 1024 * 1024  # FWX_FEATURE_MAX_SIZE
DELTA = 0x9E3779B9
ROUNDS = 32
FEATURE_KEY = (0x8F4C29A1, 0x73B6D502, 0xC14E87F3, 0x2AD95B60)

M32 = 0xFFFFFFFF


class FwxBError(Exception):
    pass


def _xtea_encrypt_block(v0: int, v1: int):
    """One XTEA encryption of (v0, v1). Mirrors xtea_encrypt_block() exactly."""
    s = 0
    k = FEATURE_KEY
    for _ in range(ROUNDS):
        v0 = (v0 + ((((v1 << 4) ^ (v1 >> 5)) + v1) ^ (s + k[s & 3]))) & M32
        s = (s + DELTA) & M32
        v1 = (v1 + ((((v0 << 4) ^ (v0 >> 5)) + v0) ^ (s + k[(s >> 11) & 3]))) & M32
    return v0, v1


def xtea_ctr_crypt(data: bytes, nonce: int) -> bytes:
    """XTEA-CTR (symmetric). Mirrors xtea_ctr_crypt()."""
    out = bytearray(data)
    length = len(out)
    counter = nonce & 0xFFFFFFFFFFFFFFFF
    offset = 0
    while offset < length:
        v0, v1 = _xtea_encrypt_block(counter & M32, (counter >> 32) & M32)
        stream = struct.pack("<II", v0, v1)  # lo32 first, hi32 second, both LE
        n = min(8, length - offset)
        for i in range(n):
            out[offset + i] ^= stream[i]
        offset += n
        counter = (counter + 1) & 0xFFFFFFFFFFFFFFFF
    return bytes(out)


def parse_header(blob: bytes):
    if len(blob) < HEADER_SIZE:
        raise FwxBError("file shorter than 24-byte header")
    magic = blob[0:4]
    version = blob[4]
    alg = blob[5]
    (header_size,) = struct.unpack_from("<H", blob, 6)
    (plain_len,) = struct.unpack_from("<I", blob, 8)
    (crc,) = struct.unpack_from("<I", blob, 12)
    (nonce,) = struct.unpack_from("<Q", blob, 16)
    if magic != MAGIC:
        raise FwxBError(f"bad magic: {magic!r}")
    if version != FORMAT_VERSION:
        raise FwxBError(f"bad version: {version}")
    if alg != ALGORITHM_XTEA_CTR:
        raise FwxBError(f"bad algorithm: {alg}")
    if header_size != HEADER_SIZE:
        raise FwxBError(f"bad header_size: {header_size}")
    if plain_len == 0 or plain_len > MAX_SIZE:
        raise FwxBError(f"bad plain_len: {plain_len}")
    if len(blob) != HEADER_SIZE + plain_len:
        raise FwxBError(
            f"file_len {len(blob)} != header {HEADER_SIZE} + plain_len {plain_len}"
        )
    return {
        "version": version,
        "algorithm": alg,
        "header_size": header_size,
        "plain_len": plain_len,
        "crc": crc,
        "nonce": nonce,
    }


def build_header(version: int, algorithm: int, plain_len: int, crc: int, nonce: int) -> bytes:
    return struct.pack(
        "<4sBBHIIQ",
        MAGIC,
        version,
        algorithm,
        HEADER_SIZE,
        plain_len,
        crc,
        nonce & 0xFFFFFFFFFFFFFFFF,
    )


def decrypt_blob(blob: bytes):
    hdr = parse_header(blob)
    plain = xtea_ctr_crypt(blob[HEADER_SIZE:], hdr["nonce"])
    if len(plain) != hdr["plain_len"]:
        raise FwxBError("plain_len mismatch after decrypt")
    actual_crc = zlib.crc32(plain) & M32
    if actual_crc != hdr["crc"]:
        raise FwxBError(
            f"crc mismatch: header=0x{hdr['crc']:08x} computed=0x{actual_crc:08x}"
        )
    return hdr, plain


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def cmd_decrypt(argv):
    if len(argv) != 2:
        raise FwxBError("usage: fwxb_pack.py decrypt <in.bin> <out.txt>")
    in_path, out_path = argv
    with open(in_path, "rb") as f:
        blob = f.read()
    if len(blob) > HEADER_SIZE + MAX_SIZE:
        raise FwxBError("file exceeds FWX_FEATURE_MAX_SIZE")
    hdr, plain = decrypt_blob(blob)
    with open(out_path, "wb") as f:
        f.write(plain)
    print(f"decrypt OK")
    print(f"  version={hdr['version']} alg={hdr['algorithm']} "
          f"header_size={hdr['header_size']}")
    print(f"  plain_len={hdr['plain_len']}")
    print(f"  crc=0x{hdr['crc']:08x} (zlib crc32 of plaintext: verified)")
    print(f"  nonce=0x{hdr['nonce']:016x}")
    print(f"  plain md5={_md5(plain)}")
    print(f"  wrote {out_path} ({len(plain)} bytes)")
    return 0


def cmd_encrypt(argv):
    if len(argv) not in (2, 3):
        raise FwxBError("usage: fwxb_pack.py encrypt <in.txt> <out.bin> [nonce]")
    in_path, out_path = argv[0], argv[1]
    if len(argv) == 3:
        nonce = int(argv[2], 0)
        if not (0 <= nonce <= 0xFFFFFFFFFFFFFFFF):
            raise FwxBError("nonce must fit in u64")
    else:
        nonce = int.from_bytes(secrets.token_bytes(8), "little")
    with open(in_path, "rb") as f:
        plain = f.read()
    if len(plain) == 0:
        raise FwxBError("plaintext is empty")
    if len(plain) > MAX_SIZE:
        raise FwxBError(f"plaintext {len(plain)} exceeds FWX_FEATURE_MAX_SIZE (20MiB)")
    crc = zlib.crc32(plain) & M32
    body = xtea_ctr_crypt(plain, nonce)
    blob = build_header(FORMAT_VERSION, ALGORITHM_XTEA_CTR, len(plain), crc, nonce) + body
    with open(out_path, "wb") as f:
        f.write(blob)
    print(f"encrypt OK")
    print(f"  plain_len={len(plain)}")
    print(f"  nonce=0x{nonce:016x}")
    print(f"  crc=0x{crc:08x}")
    print(f"  plain md5={_md5(plain)}")
    print(f"  out md5={_md5(blob)}")
    print(f"  out size={len(blob)} bytes (<= {HEADER_SIZE + MAX_SIZE})")
    print(f"  wrote {out_path}")
    return 0


def main(argv):
    if len(argv) < 1:
        print(__doc__)
        return 2
    mode = argv[0]
    try:
        if mode == "decrypt":
            return cmd_decrypt(argv[1:])
        if mode == "encrypt":
            return cmd_encrypt(argv[1:])
        raise FwxBError(f"unknown mode: {mode!r} (expected 'decrypt' or 'encrypt')")
    except FwxBError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    except (OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
