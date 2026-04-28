#!/usr/bin/env python3
"""Build an Amstrad CPC Z80 port of Soul Player.

The CPC target keeps the model format and fixed-point arithmetic contract from
the C64 build, but emits native Z80 code and AMSDOS-loadable binary files.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

from assembler_z80 import assemble_z80
from build import build_tokenizer_tables, parse_soul_for_c64
from numerics import ED, EXP_LUT, FF, HD, NH, NL, SL, VS


TXT_OUTPUT = 0xBB5A
KM_WAIT_CHAR = 0xBB06

SEP_TOK = 1
END_TOK = 3
PAD_TOK = 0
MAXSEQ = SL
STRIDE = ED * 2

WEIGHTS_ADDR = 0x1800
BASIC_TOP = WEIGHTS_ADDR - 1
CODE_ADDR = 0x9000

WEIGHTS_END = 0x7CA0
BUF_BASE = 0x7D00
HIDDEN = BUF_BASE + 0x0000
K_ALL = BUF_BASE + 0x0500
V_ALL = BUF_BASE + 0x0A00
SCRATCH = BUF_BASE + 0x0F00

SCORES_BUF = SCRATCH + 0x000
WEIGHTS_BUF = SCRATCH + 0x030
XN_BUF = SCRATCH + 0x050
Z_BUF = SCRATCH + 0x090
W2_BUF = SCRATCH + 0x110
Q_BUF = SCRATCH + 0x150
ATT_VEC = SCRATCH + 0x190
LOGITS_BUF = SCRATCH + 0x1D0
TOKS = SCRATCH + 0x2D0
SLEN = SCRATCH + 0x2F0
GPOS = SCRATCH + 0x2F1
INPUT = SCRATCH + 0x300
BUF_END = SCRATCH + 0x340


def _db(data: bytes | bytearray, width: int = 24) -> str:
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i + width]
        lines.append("    db " + ",".join(str(int(b)) for b in chunk))
    return "\n".join(lines)


def _cpc_str(text: str) -> bytes:
    out = bytearray()
    for ch in text:
        if ch in "\r\n":
            out.extend((13, 10))
        else:
            out.append(ord(ch) & 0x7F)
    out.append(0)
    return bytes(out)


def amsdos_header(name: str, ext: str, payload: bytes, load_addr: int, exec_addr: int) -> bytes:
    """Return a 128-byte AMSDOS header for a binary file."""
    header = bytearray(128)
    base = name.upper()[:8].ljust(8)
    suffix = ext.upper()[:3].ljust(3)
    header[1:9] = base.encode("ascii")
    header[9:12] = suffix.encode("ascii")
    header[18] = 0x02  # unprotected binary
    length = len(payload)
    header[19:21] = struct.pack("<H", min(length, 0xFFFF))
    header[21:23] = struct.pack("<H", load_addr)
    header[23] = 0xFF
    header[24:26] = struct.pack("<H", min(length, 0xFFFF))
    header[26:28] = struct.pack("<H", exec_addr)
    header[64] = length & 0xFF
    header[65] = (length >> 8) & 0xFF
    header[66] = (length >> 16) & 0xFF
    checksum = sum(header[:67]) & 0xFFFF
    header[67:69] = struct.pack("<H", checksum)
    return bytes(header)


def build_headerless_ascii_file(text: str) -> bytes:
    """Build a headerless ASCII BASIC file.

    AMSDOS treats files without a valid header as ASCII text, which is the
    form produced by SAVE "name",A and accepted by RUN/LOAD as BASIC source.
    """
    payload = text.replace("\n", "\r\n").encode("ascii")
    return payload + b"\x1A"


def build_basic_loader_file() -> bytes:
    return build_headerless_ascii_file(
        f"10 MEMORY &{BASIC_TOP:04X}\n"
        "20 LOAD \"SOULW.BIN\"\n"
        "30 LOAD \"SOULCPC.BIN\"\n"
        f"40 CALL &{CODE_ADDR:04X}\n"
    )


def _split_amsdos_name(filename: str) -> tuple[str, str]:
    if "." in filename:
        base, ext = filename.rsplit(".", 1)
    else:
        base, ext = filename, ""
    base = base.upper()[:8].ljust(8)
    ext = ext.upper()[:3].ljust(3)
    return base, ext


def _write_directory_entry(directory: bytearray, entry_index: int, filename: str,
                           extent: int, records: int, blocks: list[int]) -> None:
    off = entry_index * 32
    base, ext = _split_amsdos_name(filename)
    directory[off:off + 32] = b"\x00" * 32
    directory[off] = 0
    directory[off + 1:off + 9] = base.encode("ascii")
    directory[off + 9:off + 12] = ext.encode("ascii")
    directory[off + 12] = extent & 0x1F
    directory[off + 13] = 0
    directory[off + 14] = (extent >> 5) & 0xFF
    directory[off + 15] = records & 0xFF
    for i, block in enumerate(blocks[:16]):
        directory[off + 16 + i] = block & 0xFF


def build_dsk_data_format(files: list[tuple[str, bytes]]) -> bytes:
    """Build a standard 40-track, single-sided CPC DATA-format DSK.

    The filesystem is AMSDOS/CP-M style:
      - 9 sectors per track, 512 bytes each, interleaved sector IDs
        &C1,&C6,&C2,&C7,&C3,&C8,&C4,&C9,&C5
      - 1 KiB allocation blocks
      - first two blocks are the 64-entry directory
    """
    tracks = 40
    sides = 1
    sectors_per_track = 9
    sector_size = 512
    sector_ids = [0xC1, 0xC6, 0xC2, 0xC7, 0xC3, 0xC8, 0xC4, 0xC9, 0xC5]
    track_data_size = sectors_per_track * sector_size
    track_size = 0x100 + track_data_size
    disk_payload_size = tracks * track_data_size
    block_size = 1024
    total_blocks = disk_payload_size // block_size
    directory_blocks = 2

    fs = bytearray([0xE5] * disk_payload_size)
    directory = bytearray([0xE5] * (directory_blocks * block_size))
    next_block = directory_blocks
    entry_index = 0

    for filename, data in files:
        records_total = (len(data) + 127) // 128
        padded = bytearray(data)
        padded.extend([0x1A] * (records_total * 128 - len(padded)))
        blocks_needed = (len(padded) + block_size - 1) // block_size
        if next_block + blocks_needed > total_blocks:
            raise ValueError(f"{filename} does not fit on CPC DATA-format disk")
        allocated = list(range(next_block, next_block + blocks_needed))
        next_block += blocks_needed

        for i, block in enumerate(allocated):
            start = i * block_size
            chunk = padded[start:start + block_size]
            disk_off = block * block_size
            fs[disk_off:disk_off + len(chunk)] = chunk

        remaining_records = records_total
        block_cursor = 0
        extent = 0
        while remaining_records > 0:
            extent_records = min(128, remaining_records)
            extent_blocks = (extent_records + 7) // 8
            extent_alloc = allocated[block_cursor:block_cursor + extent_blocks]
            _write_directory_entry(directory, entry_index, filename, extent,
                                   extent_records, extent_alloc)
            entry_index += 1
            if entry_index >= 64:
                raise ValueError("too many directory entries for CPC DATA-format disk")
            remaining_records -= extent_records
            block_cursor += extent_blocks
            extent += 1

    fs[:len(directory)] = directory

    dsk = bytearray()
    header = bytearray(0x100)
    header[0:34] = b"MV - CPCEMU Disk-File\r\nDisk-Info\r\n"
    header[34:48] = b"Soul Player".ljust(14, b" ")
    header[0x30] = tracks
    header[0x31] = sides
    header[0x32:0x34] = struct.pack("<H", track_size)
    dsk.extend(header)

    for track in range(tracks):
        th = bytearray(0x100)
        th[0:12] = b"Track-Info\r\n"
        th[0x10] = track
        th[0x11] = 0
        th[0x14] = 2
        th[0x15] = sectors_per_track
        th[0x16] = 0x4E
        th[0x17] = 0xE5
        for sector in range(sectors_per_track):
            p = 0x18 + sector * 8
            th[p + 0] = track
            th[p + 1] = 0
            th[p + 2] = sector_ids[sector]
            th[p + 3] = 2
            th[p + 4] = 0
            th[p + 5] = 0
            th[p + 6:p + 8] = struct.pack("<H", sector_size)
        dsk.extend(th)
        track_base = track * track_data_size
        for sector_id in sector_ids:
            logical_sector = sector_id - 0xC1
            start = track_base + logical_sector * sector_size
            dsk.extend(fs[start:start + sector_size])

    return bytes(dsk)


def _setup_matvec(lines, w_addr, src_addr, dst_addr, rows, cols, shift, bias_addr=None):
    lines += [
        f"    ld hl,{w_addr}",
        "    ld (MV_WP),hl",
        f"    ld hl,{src_addr}",
        "    ld (MV_SP),hl",
        f"    ld hl,{dst_addr}",
        "    ld (MV_DP),hl",
        f"    ld a,{rows}",
        "    ld (MV_ROWS),a",
        f"    ld a,{cols}",
        "    ld (MV_COLS),a",
        f"    ld a,{shift}",
        "    ld (MV_SHIFT),a",
    ]
    if bias_addr is None:
        lines.append("    call matvec")
    else:
        lines += [
            f"    ld hl,{bias_addr}",
            "    ld (MV_BP),hl",
            "    call matvec_bias",
        ]


def _setup_matvec_dyn(lines, w_addr, src_var, dst_var, rows, cols, shift, bias_addr=None):
    lines += [
        f"    ld hl,{w_addr}",
        "    ld (MV_WP),hl",
        f"    ld hl,({src_var})",
        "    ld (MV_SP),hl",
        f"    ld hl,({dst_var})",
        "    ld (MV_DP),hl",
        f"    ld a,{rows}",
        "    ld (MV_ROWS),a",
        f"    ld a,{cols}",
        "    ld (MV_COLS),a",
        f"    ld a,{shift}",
        "    ld (MV_SHIFT),a",
    ]
    if bias_addr is None:
        lines.append("    call matvec")
    else:
        lines += [
            f"    ld hl,{bias_addr}",
            "    ld (MV_BP),hl",
            "    call matvec_bias",
        ]


def _setup_rms_dyn(lines, x_var, g_addr, dst_addr, shift):
    lines += [
        f"    ld hl,({x_var})",
        "    ld (RMS_XP),hl",
        f"    ld hl,{g_addr}",
        "    ld (RMS_GP),hl",
        f"    ld hl,{dst_addr}",
        "    ld (RMS_DP),hl",
        f"    ld a,{shift}",
        "    ld (RMS_SG),a",
        "    call rms_norm",
    ]


def _layer_block(layer: int, w_addrs: dict[str, tuple[int, int]]) -> str:
    p = f"l{layer}"
    lay = {k.split(".", 1)[1]: v for k, v in w_addrs.items() if k.startswith(f"l{layer}.")}
    lines: list[str] = []
    lines += [
        f"layer_{layer}:",
        "    xor a",
        "    ld (POS),a",
        f"layer_{layer}_kv_loop:",
        "    ld a,(POS)",
        f"    ld de,{HIDDEN}",
        "    call addr_pos_stride",
        "    ld (CUR_H),hl",
    ]
    _setup_rms_dyn(lines, "CUR_H", lay["n1"][0], XN_BUF, lay["n1"][1])
    lines += [
        "    ld a,(POS)",
        f"    ld de,{K_ALL}",
        "    call addr_pos_stride",
        "    ld (CUR_D),hl",
    ]
    _setup_matvec_dyn(lines, lay["k"][0], "CONST_XN", "CUR_D", ED, ED, lay["k"][1] + 1)
    lines += [
        "    ld a,(POS)",
        f"    ld de,{V_ALL}",
        "    call addr_pos_stride",
        "    ld (CUR_D),hl",
    ]
    _setup_matvec_dyn(lines, lay["v"][0], "CONST_XN", "CUR_D", ED, ED, lay["v"][1] + 1)
    lines += [
        "    ld hl,POS",
        "    inc (hl)",
        "    ld a,(POS)",
        "    ld b,a",
        "    ld a,(SLEN)",
        "    cp b",
        f"    jp nz,layer_{layer}_kv_loop",
        "",
        "    xor a",
        "    ld (POS),a",
        f"layer_{layer}_att_loop:",
        "    ld a,(POS)",
        f"    ld de,{HIDDEN}",
        "    call addr_pos_stride",
        "    ld (CUR_H),hl",
    ]
    _setup_rms_dyn(lines, "CUR_H", lay["n1"][0], XN_BUF, lay["n1"][1])
    _setup_matvec(lines, lay["q"][0], XN_BUF, Q_BUF, ED, ED, lay["q"][1] + 1)
    lines += [
        "    xor a",
        "    ld (HEAD),a",
        f"layer_{layer}_head_loop:",
        "    ld a,(HEAD)",
        "    call head_offset",
        f"    ld de,{Q_BUF}",
        "    add hl,de",
        "    ld (QP),hl",
        f"    ld hl,{K_ALL}",
        "    ld (KB),hl",
        f"    ld hl,{V_ALL}",
        "    ld (VB),hl",
        "    ld a,(HEAD)",
        "    call head_offset",
        f"    ld de,{ATT_VEC}",
        "    add hl,de",
        "    ld (OP),hl",
        "    ld a,(POS)",
        "    inc a",
        "    ld (NKEYS),a",
        "    ld a,(HEAD)",
        "    ld (HEAD_PARAM),a",
        "    call attn_head",
        "    ld hl,HEAD",
        "    inc (hl)",
        "    ld a,(HEAD)",
        f"    cp {NH}",
        f"    jp nz,layer_{layer}_head_loop",
    ]
    _setup_matvec(lines, lay["proj"][0], ATT_VEC, W2_BUF, ED, ED, lay["proj"][1] + 1)
    lines += [
        "    ld a,(POS)",
        f"    ld de,{HIDDEN}",
        "    call addr_pos_stride",
        "    ld (RES_DST),hl",
        f"    ld hl,{W2_BUF}",
        "    ld (RES_SRC),hl",
        "    call residual_add",
        "    ld hl,POS",
        "    inc (hl)",
        "    ld a,(POS)",
        "    ld b,a",
        "    ld a,(SLEN)",
        "    cp b",
        f"    jp nz,layer_{layer}_att_loop",
        "",
        "    xor a",
        "    ld (POS),a",
        f"layer_{layer}_ffn_loop:",
        "    ld a,(POS)",
        f"    ld de,{HIDDEN}",
        "    call addr_pos_stride",
        "    ld (CUR_H),hl",
    ]
    _setup_rms_dyn(lines, "CUR_H", lay["n2"][0], XN_BUF, lay["n2"][1])
    _setup_matvec(lines, lay["fc1_w"][0], XN_BUF, Z_BUF, FF, ED, lay["fc1_w"][1] + 1, lay["fc1_b"][0])
    lines += [
        f"    ld hl,{Z_BUF}",
        "    ld (RELU_PTR),hl",
        f"    ld a,{FF}",
        "    ld (RELU_COUNT),a",
        "    call relu",
    ]
    _setup_matvec(lines, lay["fc2_w"][0], Z_BUF, W2_BUF, ED, FF, lay["fc2_w"][1] + 1, lay["fc2_b"][0])
    lines += [
        "    ld a,(POS)",
        f"    ld de,{HIDDEN}",
        "    call addr_pos_stride",
        "    ld (RES_DST),hl",
        f"    ld hl,{W2_BUF}",
        "    ld (RES_SRC),hl",
        "    call residual_add",
        "    ld hl,POS",
        "    inc (hl)",
        "    ld a,(POS)",
        "    ld b,a",
        "    ld a,(SLEN)",
        "    cp b",
        f"    jp nz,layer_{layer}_ffn_loop",
        "    ret",
    ]
    return "\n".join(lines)


def build_program(soul_blob: bytes, tensor_info, tok_offsets, tok_strings, tok_merges) -> tuple[bytes, str, dict[str, int]]:
    if len(soul_blob) + WEIGHTS_ADDR != WEIGHTS_END:
        raise ValueError(f"unexpected weight end ${WEIGHTS_ADDR + len(soul_blob):04X}")

    w_addrs = {name: (WEIGHTS_ADDR + offset, shift) for name, _kind, offset, _size, shift in tensor_info}

    asm = f"""
entry:
    ld hl,banner
    call print_str
    ld hl,ready_msg
    call print_str

main_loop:
    call newline
    ld hl,prompt_str
    call print_str
    call read_line
    ld a,(INPUT)
    cp 113
    jp z,quit
    cp 81
    jp z,quit
    call encode_input
    call run_inference
    jp main_loop

quit:
    call newline
    ld hl,quit_msg
    call print_str
    ret

print_str:
    ld a,(hl)
    or a
    ret z
    call {TXT_OUTPUT}
    inc hl
    jr print_str

newline:
    ld a,13
    call {TXT_OUTPUT}
    ld a,10
    call {TXT_OUTPUT}
    ret

read_line:
    ld hl,{INPUT}
    ld b,0
read_line_loop:
    call {KM_WAIT_CHAR}
    cp 13
    jr z,read_line_done
    ld c,a
    ld a,b
    cp 62
    jr nc,read_line_loop
    ld a,c
    ld (hl),a
    inc hl
    inc b
    call {TXT_OUTPUT}
    jr read_line_loop
read_line_done:
    ld (hl),0
    call newline
    ret

char_to_token:
    cp 32
    jr nz,ct_not_space
    ld a,4
    ret
ct_not_space:
    cp 97
    jr c,ct_upper
    cp 123
    jr nc,ct_upper
    sub 92
    ret
ct_upper:
    cp 65
    jr c,ct_punct
    cp 91
    jr nc,ct_punct
    sub 60
    ret
ct_punct:
    cp 46
    jr nz,ct_p2
    ld a,31
    ret
ct_p2:
    cp 39
    jr nz,ct_p3
    ld a,32
    ret
ct_p3:
    cp 33
    jr nz,ct_p4
    ld a,33
    ret
ct_p4:
    cp 63
    jr nz,ct_p5
    ld a,34
    ret
ct_p5:
    cp 44
    jr nz,ct_p6
    ld a,35
    ret
ct_p6:
    cp 59
    jr nz,ct_p7
    ld a,36
    ret
ct_p7:
    cp 58
    jr nz,ct_p8
    ld a,37
    ret
ct_p8:
    cp 45
    jr nz,ct_unknown
    ld a,38
    ret
ct_unknown:
    xor a
    ret

encode_input:
    ld a,{SEP_TOK}
    ld ({TOKS}),a
    ld hl,{INPUT}
    ld de,{TOKS + 1}
    ld b,1
enc_loop:
    ld a,(hl)
    or a
    jr z,enc_done
    push hl
    push de
    push bc
    call char_to_token
    pop bc
    pop de
    pop hl
    or a
    jr z,enc_skip
    ld (de),a
    inc de
    inc b
    ld a,b
    cp {MAXSEQ - 2}
    jr nc,enc_done
enc_skip:
    inc hl
    jr enc_loop
enc_done:
    ld a,{SEP_TOK}
    ld (de),a
    inc b
    ld a,b
    ld ({SLEN}),a
    call apply_bpe
    ret

apply_bpe:
    ld hl,merge_table
bpe_next:
    ld a,(hl)
    cp 255
    ret z
    ld (BPE_A),a
    inc hl
    ld a,(hl)
    ld (BPE_B),a
    inc hl
    ld a,(hl)
    ld (BPE_M),a
    inc hl
    ld (BPE_PTR),hl
    xor a
    ld (BPE_IDX),a
bpe_scan:
    ld a,({SLEN})
    dec a
    ld b,a
    ld a,(BPE_IDX)
    cp b
    jr nc,bpe_advance
    ld hl,{TOKS}
    ld e,a
    ld d,0
    add hl,de
    ld a,(hl)
    ld b,a
    ld a,(BPE_A)
    cp b
    jr nz,bpe_no_pair
    inc hl
    ld a,(hl)
    ld b,a
    ld a,(BPE_B)
    cp b
    jr nz,bpe_no_pair
    dec hl
    ld a,(BPE_M)
    ld (hl),a
    ld a,(BPE_IDX)
    inc a
    ld (BPE_SHIFT),a
bpe_shift_loop:
    ld a,(BPE_SHIFT)
    inc a
    ld c,a
    ld a,({SLEN})
    cp c
    jr z,bpe_shift_done
    jr c,bpe_shift_done
    ld a,(BPE_SHIFT)
    ld hl,{TOKS}
    ld e,a
    ld d,0
    add hl,de
    inc hl
    ld a,(hl)
    dec hl
    ld (hl),a
    ld hl,BPE_SHIFT
    inc (hl)
    jr bpe_shift_loop
bpe_shift_done:
    ld hl,{SLEN}
    dec (hl)
    jr bpe_scan
bpe_no_pair:
    ld hl,BPE_IDX
    inc (hl)
    jr bpe_scan
bpe_advance:
    ld hl,(BPE_PTR)
    jr bpe_next

print_token:
    ld l,a
    ld h,0
    add hl,hl
    ld de,decode_offsets
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld hl,decode_strings
    add hl,de
    call print_str
    ret

blip:
    ld a,7
    call {TXT_OUTPUT}
    ret

run_inference:
    call newline
    ld hl,cpc_str
    call print_str
    xor a
    ld ({GPOS}),a
gen_loop:
    call do_forward
    cp {END_TOK}
    ret z
    cp {SEP_TOK}
    ret z
    cp {PAD_TOK}
    ret z
    push af
    ld hl,{TOKS}
    ld a,({SLEN})
    ld e,a
    ld d,0
    add hl,de
    pop af
    ld (hl),a
    push af
    ld hl,{SLEN}
    inc (hl)
    pop af
    call print_token
    call blip
    ld hl,{GPOS}
    inc (hl)
    ld a,({GPOS})
    cp 20
    ret nc
    ld a,({SLEN})
    cp {MAXSEQ}
    ret nc
    jp gen_loop

addr_pos_stride:
    ld l,a
    ld h,0
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,de
    ret

addr_pos_ed:
    ld l,a
    ld h,0
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,de
    ret

head_offset:
    ld l,a
    ld h,0
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl
    ret

do_forward:
    xor a
    ld (POS),a
emb_loop:
    ld a,(POS)
    ld hl,{TOKS}
    ld e,a
    ld d,0
    add hl,de
    ld a,(hl)
    ld de,{w_addrs['te'][0]}
    call addr_pos_ed
    ld (EMB_TP),hl
    ld a,(POS)
    ld de,{w_addrs['pe'][0]}
    call addr_pos_ed
    ld (EMB_PP),hl
    ld a,(POS)
    ld de,{HIDDEN}
    call addr_pos_stride
    ld (EMB_DP),hl
    ld a,{w_addrs['te'][1]}
    ld (EMB_SH1),a
    ld a,{w_addrs['pe'][1]}
    ld (EMB_SH2),a
    call embed_one
    ld hl,POS
    inc (hl)
    ld a,(POS)
    ld b,a
    ld a,({SLEN})
    cp b
    jp nz,emb_loop

    call layer_0
    call layer_1

    ld a,({SLEN})
    dec a
    ld de,{HIDDEN}
    call addr_pos_stride
    ld (CUR_H),hl
    ld hl,(CUR_H)
    ld (RMS_XP),hl
    ld hl,{w_addrs['norm'][0]}
    ld (RMS_GP),hl
    ld hl,{XN_BUF}
    ld (RMS_DP),hl
    ld a,{w_addrs['norm'][1]}
    ld (RMS_SG),a
    call rms_norm
"""

    lines = [asm]
    final_lines: list[str] = []
    _setup_matvec(final_lines, w_addrs["out"][0], XN_BUF, LOGITS_BUF, VS, ED, w_addrs["out"][1])
    final_lines += [
        f"    ld hl,{LOGITS_BUF}",
        "    ld (ARG_PTR),hl",
        "    call argmax",
        "    ret",
        "",
        _layer_block(0, w_addrs),
        "",
        _layer_block(1, w_addrs),
        "",
        RUNTIME_ASM,
        "",
        "banner:",
        _db(_cpc_str(
    "   /\\   /\\\n"
    "  /  \\_/  \\\n"
    "  .-------.\n"
    " | >     < |\n"
    " |   ^^^   |\n"
    " |..|~~~|..|\n"
    "  \\  ---  /\n"
    "   \\_____/\n"
        "\n"
        "\n"
            "\rME MAFUL\rME EVIL TWIN OF MEFUL\r\r"
            "SOUL PLAYER CPC\r2026 - GIZMO64K | GIDEON\r\r"
            "REAL TRANSFORMER. REAL WEIGHTS.\rLOADED FOR AMSTRAD CPC.\r\r"
        )),
        "ready_msg:",
        _db(_cpc_str(
            "TYPE AND I WILL SCREAM AT YOU\rEVENTUALLY... AFTER MINUTES!\rTYPE 'Q' TO QUIT.\r"
        )),
        "prompt_str:",
        _db(_cpc_str("YOU> ")),
        "cpc_str:",
        _db(_cpc_str("CPC> ")),
        "quit_msg:",
        _db(_cpc_str("\r-- ATTENTION IS ALL THIS NEEDED\rGIZMO64K\r")),
        "exp_lut:",
        _db(bytes(int(v) for v in EXP_LUT.tolist())),
        "decode_offsets:",
        _db(tok_offsets),
        "decode_strings:",
        _db(tok_strings),
        "merge_table:",
        _db(tok_merges),
        "CONST_XN:",
        f"    dw {XN_BUF}",
        "vars_start:",
        "POS: db 0",
        "HEAD: db 0",
        "HEAD_PARAM: db 0",
        "CUR_H: dw 0",
        "CUR_D: dw 0",
        "EMB_TP: dw 0",
        "EMB_PP: dw 0",
        "EMB_DP: dw 0",
        "EMB_SH1: db 0",
        "EMB_SH2: db 0",
        "MV_WP: dw 0",
        "MV_SP: dw 0",
        "MV_DP: dw 0",
        "MV_BP: dw 0",
        "MV_ROWS: db 0",
        "MV_COLS: db 0",
        "MV_SHIFT: db 0",
        "MV_BFLAG: db 0",
        "MV_WCUR: dw 0",
        "MV_SCUR: dw 0",
        "MV_DCUR: dw 0",
        "MV_BCUR: dw 0",
        "MV_RCOUNT: db 0",
        "MV_CCOUNT: db 0",
        "RMS_XP: dw 0",
        "RMS_GP: dw 0",
        "RMS_DP: dw 0",
        "RMS_SG: db 0",
        "RMS_XCUR: dw 0",
        "RMS_GCUR: dw 0",
        "RMS_DCUR: dw 0",
        "RMS_COUNT: db 0",
        "QP: dw 0",
        "KB: dw 0",
        "VB: dw 0",
        "OP: dw 0",
        "NKEYS: db 0",
        "SCORES_P: dw 0",
        "WTS_P: dw 0",
        "KROW: dw 0",
        "VROW: dw 0",
        "TIDX: db 0",
        "JIDX: db 0",
        "MAXSF: dw 0",
        "WSUM: dw 0",
        "RES_DST: dw 0",
        "RES_SRC: dw 0",
        "RELU_PTR: dw 0",
        "RELU_COUNT: db 0",
        "ARG_PTR: dw 0",
        "BPE_A: db 0",
        "BPE_B: db 0",
        "BPE_M: db 0",
        "BPE_PTR: dw 0",
        "BPE_IDX: db 0",
        "BPE_SHIFT: db 0",
        "ACC32: ds 4",
        "T32: ds 4",
        "SCR_A: ds 4",
        "SCR_B: ds 4",
        "PROD: ds 4",
        "TMP: dw 0",
        "SRC16: dw 0",
        "SIGN: db 0",
        "RMS: dw 0",
        "INV: dw 0",
        "vars_end:",
    ]
    lines.append("\n".join(final_lines))
    source = "\n".join(lines)
    constants = {
        "INPUT": INPUT,
        "TOKS": TOKS,
        "SLEN": SLEN,
        "GPOS": GPOS,
    }
    code, labels = assemble_z80(source, CODE_ADDR, constants=constants)
    return code, source, labels


RUNTIME_ASM = f"""
embed_one:
    xor a
    ld (RMS_COUNT),a
embed_loop:
    ld hl,(EMB_TP)
    ld a,(hl)
    inc hl
    ld (EMB_TP),hl
    ld (TMP),a
    or a
    jp p,emb_te_pos
    ld a,255
    jr emb_te_hi
emb_te_pos:
    xor a
emb_te_hi:
    ld (TMP+1),a
    ld a,8
    ld b,a
    ld a,(EMB_SH1)
    ld c,a
    ld a,b
    sub c
    ld b,a
    call shl_tmp_b
    ld hl,(EMB_PP)
    ld a,(hl)
    inc hl
    ld (EMB_PP),hl
    ld (SRC16),a
    or a
    jp p,emb_pe_pos
    ld a,255
    jr emb_pe_hi
emb_pe_pos:
    xor a
emb_pe_hi:
    ld (SRC16+1),a
    ld a,8
    ld b,a
    ld a,(EMB_SH2)
    ld c,a
    ld a,b
    sub c
    ld b,a
    call shl_src_b
    ld hl,(TMP)
    ld de,(SRC16)
    add hl,de
    ex de,hl
    ld hl,(EMB_DP)
    ld a,e
    ld (hl),a
    inc hl
    ld a,d
    ld (hl),a
    inc hl
    ld (EMB_DP),hl
    ld hl,RMS_COUNT
    inc (hl)
    ld a,(RMS_COUNT)
    cp {ED}
    jp nz,embed_loop
    ret

shl_tmp_b:
    ld a,b
    or a
    ret z
shl_tmp_loop:
    ld hl,TMP
    sla (hl)
    inc hl
    rl (hl)
    djnz shl_tmp_loop
    ret

shl_src_b:
    ld a,b
    or a
    ret z
shl_src_loop:
    ld hl,SRC16
    sla (hl)
    inc hl
    rl (hl)
    djnz shl_src_loop
    ret

clear_acc32:
    ld hl,0
    ld (ACC32),hl
    ld (ACC32+2),hl
    ret

clear_t32:
    ld hl,0
    ld (T32),hl
    ld (T32+2),hl
    ret

clear_prod:
    ld hl,0
    ld (PROD),hl
    ld (PROD+2),hl
    ret

smul16:
    xor a
    ld (SIGN),a
    ld a,(TMP+1)
    or a
    jp p,sm16_a_pos
    call neg_tmp
    ld a,1
    ld (SIGN),a
sm16_a_pos:
    ld a,(SRC16+1)
    or a
    jp p,sm16_b_pos
    call neg_src
    ld a,(SIGN)
    xor 1
    ld (SIGN),a
sm16_b_pos:
    call clear_prod
    ld b,16
sm16_loop:
    ld hl,PROD
    sla (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    ld hl,TMP
    sla (hl)
    inc hl
    rl (hl)
    jr nc,sm16_skip_add
    ld hl,(PROD)
    ld de,(SRC16)
    add hl,de
    ld (PROD),hl
    ld hl,(PROD+2)
    ld de,0
    adc hl,de
    ld (PROD+2),hl
sm16_skip_add:
    djnz sm16_loop
    ld a,(SIGN)
    or a
    ret z
    call neg_prod
    ret

neg_tmp:
    ld hl,TMP
    ld a,(hl)
    cpl
    ld (hl),a
    inc hl
    ld a,(hl)
    cpl
    ld (hl),a
    ld hl,(TMP)
    inc hl
    ld (TMP),hl
    ret

neg_src:
    ld hl,SRC16
    ld a,(hl)
    cpl
    ld (hl),a
    inc hl
    ld a,(hl)
    cpl
    ld (hl),a
    ld hl,(SRC16)
    inc hl
    ld (SRC16),hl
    ret

neg_prod:
    ld hl,PROD
    ld b,4
neg_prod_cpl:
    ld a,(hl)
    cpl
    ld (hl),a
    inc hl
    djnz neg_prod_cpl
    ld hl,(PROD)
    inc hl
    ld (PROD),hl
    ld a,h
    or l
    ret nz
    ld hl,(PROD+2)
    inc hl
    ld (PROD+2),hl
    ret

neg_t32:
    ld hl,T32
    ld b,4
neg_t32_cpl:
    ld a,(hl)
    cpl
    ld (hl),a
    inc hl
    djnz neg_t32_cpl
    ld hl,(T32)
    inc hl
    ld (T32),hl
    ld a,h
    or l
    ret nz
    ld hl,(T32+2)
    inc hl
    ld (T32+2),hl
    ret

neg_scra:
    ld hl,SCR_A
    ld b,4
neg_scra_cpl:
    ld a,(hl)
    cpl
    ld (hl),a
    inc hl
    djnz neg_scra_cpl
    ld hl,(SCR_A)
    inc hl
    ld (SCR_A),hl
    ld a,h
    or l
    ret nz
    ld hl,(SCR_A+2)
    inc hl
    ld (SCR_A+2),hl
    ret

add_prod_to_acc32:
    ld hl,(ACC32)
    ld de,(PROD)
    add hl,de
    ld (ACC32),hl
    ld hl,(ACC32+2)
    ld de,(PROD+2)
    adc hl,de
    ld (ACC32+2),hl
    ret

add_prod_to_t32:
    ld hl,(T32)
    ld de,(PROD)
    add hl,de
    ld (T32),hl
    ld hl,(T32+2)
    ld de,(PROD+2)
    adc hl,de
    ld (T32+2),hl
    ret

copy_acc_to_prod:
    ld hl,(ACC32)
    ld (PROD),hl
    ld hl,(ACC32+2)
    ld (PROD+2),hl
    ret

copy_t32_to_prod:
    ld hl,(T32)
    ld (PROD),hl
    ld hl,(T32+2)
    ld (PROD+2),hl
    ret

copy_scra_to_prod:
    ld hl,(SCR_A)
    ld (PROD),hl
    ld hl,(SCR_A+2)
    ld (PROD+2),hl
    ret

asr_prod_b:
    ld a,b
    or a
    ret z
asr_prod_loop:
    ld hl,PROD+3
    ld a,(hl)
    rlca
    rr (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    djnz asr_prod_loop
    ret

lsr_acc32_b:
    ld a,b
    or a
    ret z
lsr_acc_loop:
    ld hl,ACC32+3
    or a
    rr (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    djnz lsr_acc_loop
    ret

sat_prod_hl:
    ld a,(PROD+3)
    or a
    jp m,sat_neg_chk
    ld a,(PROD+3)
    or a
    jr nz,sat_pos
    ld a,(PROD+2)
    or a
    jr nz,sat_pos
    ld a,(PROD+1)
    or a
    jp m,sat_pos
    ld hl,(PROD)
    ret
sat_pos:
    ld hl,32767
    ret
sat_neg_chk:
    ld a,(PROD+3)
    cp 255
    jr nz,sat_neg
    ld a,(PROD+2)
    cp 255
    jr nz,sat_neg
    ld a,(PROD+1)
    or a
    jp p,sat_neg
    ld hl,(PROD)
    ret
sat_neg:
    ld hl,32768
    ret

matvec_bias:
    ld a,1
    ld (MV_BFLAG),a
    jr matvec_init
matvec:
    xor a
    ld (MV_BFLAG),a
matvec_init:
    ld hl,(MV_WP)
    ld (MV_WCUR),hl
    ld hl,(MV_DP)
    ld (MV_DCUR),hl
    ld hl,(MV_BP)
    ld (MV_BCUR),hl
    ld a,(MV_ROWS)
    ld (MV_RCOUNT),a
mv_row:
    ld a,(MV_BFLAG)
    or a
    jr z,mv_zero_acc
    ld hl,(MV_BCUR)
    ld e,(hl)
    inc hl
    ld d,(hl)
    inc hl
    ld (MV_BCUR),hl
    ld (ACC32),de
    ld a,d
    or a
    jp p,mv_bias_pos
    ld hl,65535
    ld (ACC32+2),hl
    jr mv_acc_done
mv_bias_pos:
    ld hl,0
    ld (ACC32+2),hl
    jr mv_acc_done
mv_zero_acc:
    call clear_acc32
mv_acc_done:
    ld hl,(MV_SP)
    ld (MV_SCUR),hl
    ld a,(MV_COLS)
    ld (MV_CCOUNT),a
mv_col:
    ld hl,(MV_WCUR)
    ld a,(hl)
    inc hl
    ld (MV_WCUR),hl
    ld (TMP),a
    or a
    jp p,mv_w_pos
    ld a,255
    jr mv_w_hi
mv_w_pos:
    xor a
mv_w_hi:
    ld (TMP+1),a
    ld hl,(MV_SCUR)
    ld e,(hl)
    inc hl
    ld d,(hl)
    inc hl
    ld (MV_SCUR),hl
    ld (SRC16),de
    call smul16
    call add_prod_to_acc32
    ld hl,MV_CCOUNT
    dec (hl)
    jp nz,mv_col
    call copy_acc_to_prod
    ld a,(MV_SHIFT)
    ld b,a
    call asr_prod_b
    call sat_prod_hl
    ex de,hl
    ld hl,(MV_DCUR)
    ld a,e
    ld (hl),a
    inc hl
    ld a,d
    ld (hl),a
    inc hl
    ld (MV_DCUR),hl
    ld hl,MV_RCOUNT
    dec (hl)
    jp nz,mv_row
    ret

rms_norm:
    call clear_acc32
    ld hl,(RMS_XP)
    ld (RMS_XCUR),hl
    ld a,{ED}
    ld (RMS_COUNT),a
rms_sum_loop:
    ld hl,(RMS_XCUR)
    ld e,(hl)
    inc hl
    ld d,(hl)
    inc hl
    ld (RMS_XCUR),hl
    ld (TMP),de
    ld b,4
rms_x_shift:
    ld hl,TMP+1
    ld a,(hl)
    rlca
    rr (hl)
    dec hl
    rr (hl)
    djnz rms_x_shift
    ld hl,(TMP)
    ld (SRC16),hl
    call smul16
    call add_prod_to_acc32
    ld hl,RMS_COUNT
    dec (hl)
    jp nz,rms_sum_loop
    ld b,5
    call lsr_acc32_b
    ld a,(ACC32)
    ld hl,ACC32+1
    or (hl)
    inc hl
    or (hl)
    inc hl
    or (hl)
    jr nz,rms_nonzero
    ld hl,1
    ld (ACC32),hl
rms_nonzero:
    call isqrt32
    ld hl,(RMS)
    ld a,h
    or l
    jr nz,rms_have_rms
    ld hl,1
    ld (RMS),hl
rms_have_rms:
    call udiv_inv
    ld a,(INV+1)
    or a
    jp p,rms_inv_ok
    ld hl,32767
    ld (INV),hl
rms_inv_ok:
    ld hl,(RMS_XP)
    ld (RMS_XCUR),hl
    ld hl,(RMS_GP)
    ld (RMS_GCUR),hl
    ld hl,(RMS_DP)
    ld (RMS_DCUR),hl
    ld a,{ED}
    ld (RMS_COUNT),a
rms_out_loop:
    ld hl,(RMS_XCUR)
    ld e,(hl)
    inc hl
    ld d,(hl)
    inc hl
    ld (RMS_XCUR),hl
    ld (TMP),de
    ld hl,(INV)
    ld (SRC16),hl
    call smul16
    ld b,15
    call asr_prod_b
    ld hl,(PROD)
    ld (TMP),hl
    ld hl,(RMS_GCUR)
    ld a,(hl)
    inc hl
    ld (RMS_GCUR),hl
    ld (SRC16),a
    or a
    jp p,rms_g_pos
    ld a,255
    jr rms_g_hi
rms_g_pos:
    xor a
rms_g_hi:
    ld (SRC16+1),a
    call smul16
    ld a,(RMS_SG)
    ld b,a
    call asr_prod_b
    call sat_prod_hl
    ex de,hl
    ld hl,(RMS_DCUR)
    ld a,e
    ld (hl),a
    inc hl
    ld a,d
    ld (hl),a
    inc hl
    ld (RMS_DCUR),hl
    ld hl,RMS_COUNT
    dec (hl)
    jp nz,rms_out_loop
    ret

sub_scra_from_acc_to_scrb:
    or a
    ld hl,(ACC32)
    ld de,(SCR_A)
    sbc hl,de
    ld (SCR_B),hl
    ld hl,(ACC32+2)
    ld de,(SCR_A+2)
    sbc hl,de
    ld (SCR_B+2),hl
    ret

isqrt32:
    ld hl,0
    ld (RMS),hl
    ld hl,16384
    ld (T32),hl
    ld hl,0
    ld (T32+2),hl
    ld b,8
isq_loop:
    ld hl,(RMS)
    ld de,(T32)
    add hl,de
    ld (SCR_A),hl
    ld hl,0
    ld de,(T32+2)
    adc hl,de
    ld (SCR_A+2),hl
    push bc
    call sub_scra_from_acc_to_scrb
    pop bc
    jp c,isq_less
    ld hl,(SCR_B)
    ld (ACC32),hl
    ld hl,(SCR_B+2)
    ld (ACC32+2),hl
    ld hl,(RMS)
    srl h
    rr l
    ld de,(T32)
    add hl,de
    ld (RMS),hl
    jr isq_next
isq_less:
    ld hl,(RMS)
    srl h
    rr l
    ld (RMS),hl
isq_next:
    ld hl,T32+3
    or a
    rr (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    ld hl,T32+3
    or a
    rr (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    dec hl
    rr (hl)
    djnz isq_loop
    ret

udiv_inv:
    ld hl,0
    ld (T32),hl
    ld hl,8
    ld (T32+2),hl
    ld hl,0
    ld (INV),hl
    ld b,16
udiv_loop:
    ld hl,T32
    sla (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    ld hl,INV
    rl (hl)
    inc hl
    rl (hl)
    or a
    ld hl,(T32+2)
    ld de,(RMS)
    sbc hl,de
    jr c,udiv_no_sub
    ld (T32+2),hl
    ld hl,INV
    ld a,(hl)
    or 1
    ld (hl),a
udiv_no_sub:
    djnz udiv_loop
    ret

sdiv:
    xor a
    ld (SIGN),a
    ld a,(T32+3)
    or a
    jp p,sdiv_pos
    call neg_t32
    ld a,1
    ld (SIGN),a
sdiv_pos:
    ld hl,0
    ld (SCR_A),hl
    ld (SCR_A+2),hl
    ld (SCR_B),hl
    ld (SCR_B+2),hl
    ld b,32
sdiv_loop:
    ld hl,T32
    sla (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    ld hl,SCR_B
    rl (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    ld hl,SCR_A
    sla (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    inc hl
    rl (hl)
    or a
    ld hl,(SCR_B)
    ld de,(WSUM)
    sbc hl,de
    ld (PROD),hl
    ld hl,(SCR_B+2)
    ld de,0
    sbc hl,de
    ld (PROD+2),hl
    jr c,sdiv_no_commit
    ld hl,(PROD)
    ld (SCR_B),hl
    ld hl,(PROD+2)
    ld (SCR_B+2),hl
    ld hl,SCR_A
    ld a,(hl)
    or 1
    ld (hl),a
sdiv_no_commit:
    djnz sdiv_loop
    ld a,(SIGN)
    or a
    jr z,sdiv_sat
    ld a,(SCR_B)
    ld hl,SCR_B+1
    or (hl)
    inc hl
    or (hl)
    inc hl
    or (hl)
    jr z,sdiv_no_adj
    ld hl,(SCR_A)
    inc hl
    ld (SCR_A),hl
    ld a,h
    or l
    jr nz,sdiv_no_adj
    ld hl,(SCR_A+2)
    inc hl
    ld (SCR_A+2),hl
sdiv_no_adj:
    call neg_scra
sdiv_sat:
    call copy_scra_to_prod
    call sat_prod_hl
    ld (SCR_A),hl
    ret

attn_head:
    ld hl,{SCORES_BUF}
    ld (SCORES_P),hl
    ld hl,{WEIGHTS_BUF}
    ld (WTS_P),hl
    ld a,(HEAD_PARAM)
    call head_offset
    ld de,(KB)
    add hl,de
    ld (KROW),hl
    xor a
    ld (TIDX),a
ah_score_loop:
    call clear_t32
    xor a
    ld (JIDX),a
ah_dot_loop:
    ld a,(JIDX)
    ld l,a
    ld h,0
    add hl,hl
    ld de,(QP)
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld (TMP),de
    ld a,(JIDX)
    ld l,a
    ld h,0
    add hl,hl
    ld de,(KROW)
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld (SRC16),de
    call smul16
    call add_prod_to_t32
    ld hl,JIDX
    inc (hl)
    ld a,(JIDX)
    cp {HD}
    jp nz,ah_dot_loop
    call copy_t32_to_prod
    ld b,14
    call asr_prod_b
    ld a,(TIDX)
    ld l,a
    ld h,0
    add hl,hl
    ld de,(SCORES_P)
    add hl,de
    ld de,(PROD)
    ld a,e
    ld (hl),a
    inc hl
    ld a,d
    ld (hl),a
    ld hl,(KROW)
    ld de,{STRIDE}
    add hl,de
    ld (KROW),hl
    ld hl,TIDX
    inc (hl)
    ld a,(TIDX)
    ld b,a
    ld a,(NKEYS)
    cp b
    jp nz,ah_score_loop
    ld hl,(SCORES_P)
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld (MAXSF),de
    ld a,1
    ld (TIDX),a
ah_max_loop:
    ld a,(TIDX)
    ld b,a
    ld a,(NKEYS)
    cp b
    jp z,ah_max_done
    ld a,(TIDX)
    ld l,a
    ld h,0
    add hl,hl
    ld de,(SCORES_P)
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld a,d
    xor 128
    ld c,a
    ld a,(MAXSF+1)
    xor 128
    cp c
    jr c,ah_max_update
    jr nz,ah_max_next
    ld a,(MAXSF)
    cp e
    jr c,ah_max_update
    jr ah_max_next
ah_max_update:
    ld (MAXSF),de
ah_max_next:
    ld hl,TIDX
    inc (hl)
    jr ah_max_loop
ah_max_done:
    ld hl,0
    ld (WSUM),hl
    xor a
    ld (TIDX),a
ah_weight_loop:
    ld a,(TIDX)
    ld l,a
    ld h,0
    add hl,hl
    ld de,(SCORES_P)
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld hl,(MAXSF)
    or a
    sbc hl,de
    ld a,h
    or a
    jr z,ah_delta_byte
    jp m,ah_delta_zero
    ld a,127
    jr ah_delta_ready
ah_delta_byte:
    ld a,l
    cp 128
    jr c,ah_delta_ready
    ld a,127
    jr ah_delta_ready
ah_delta_zero:
    xor a
ah_delta_ready:
    ld e,a
    ld d,0
    ld hl,exp_lut
    add hl,de
    ld a,(hl)
    ld c,a
    ld a,(TIDX)
    ld l,a
    ld h,0
    ld de,(WTS_P)
    add hl,de
    ld (hl),c
    ld a,c
    ld hl,(WSUM)
    ld e,a
    ld d,0
    add hl,de
    ld (WSUM),hl
    ld hl,TIDX
    inc (hl)
    ld a,(TIDX)
    ld b,a
    ld a,(NKEYS)
    cp b
    jp nz,ah_weight_loop
    ld hl,(WSUM)
    ld a,h
    or l
    jr nz,ah_wsum_ok
    ld hl,1
    ld (WSUM),hl
ah_wsum_ok:
    xor a
    ld (JIDX),a
ah_out_loop:
    call clear_t32
    ld a,(HEAD_PARAM)
    call head_offset
    ld de,(VB)
    add hl,de
    ld (VROW),hl
    xor a
    ld (TIDX),a
ah_v_loop:
    ld a,(TIDX)
    ld l,a
    ld h,0
    ld de,(WTS_P)
    add hl,de
    ld a,(hl)
    ld (TMP),a
    xor a
    ld (TMP+1),a
    ld a,(JIDX)
    ld l,a
    ld h,0
    add hl,hl
    ld de,(VROW)
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld (SRC16),de
    call smul16
    call add_prod_to_t32
    ld hl,(VROW)
    ld de,{STRIDE}
    add hl,de
    ld (VROW),hl
    ld hl,TIDX
    inc (hl)
    ld a,(TIDX)
    ld b,a
    ld a,(NKEYS)
    cp b
    jp nz,ah_v_loop
    call sdiv
    ld a,(JIDX)
    ld l,a
    ld h,0
    add hl,hl
    ld de,(OP)
    add hl,de
    ld de,(SCR_A)
    ld a,e
    ld (hl),a
    inc hl
    ld a,d
    ld (hl),a
    ld hl,JIDX
    inc (hl)
    ld a,(JIDX)
    cp {HD}
    jp nz,ah_out_loop
    ret

residual_add:
    ld a,{ED}
    ld (RMS_COUNT),a
res_loop:
    ld hl,(RES_DST)
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld (TMP),de
    ld hl,(RES_SRC)
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld hl,(TMP)
    add hl,de
    ex de,hl
    ld hl,(RES_DST)
    ld a,e
    ld (hl),a
    inc hl
    ld a,d
    ld (hl),a
    inc hl
    ld (RES_DST),hl
    ld hl,(RES_SRC)
    inc hl
    inc hl
    ld (RES_SRC),hl
    ld hl,RMS_COUNT
    dec (hl)
    jp nz,res_loop
    ret

relu:
    ld hl,(RELU_PTR)
relu_loop:
    inc hl
    ld a,(hl)
    or a
    jp p,relu_skip
    xor a
    ld (hl),a
    dec hl
    ld (hl),a
    inc hl
relu_skip:
    inc hl
    ld (RELU_PTR),hl
    ld hl,RELU_COUNT
    dec (hl)
    jp nz,relu
    ret

argmax:
    ld hl,(ARG_PTR)
    ld de,8
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld (TMP),de
    ld a,4
    ld (BPE_IDX),a
    ld a,5
    ld (RMS_COUNT),a
arg_loop:
    ld a,(RMS_COUNT)
    cp {VS}
    jr z,arg_done
    ld l,a
    ld h,0
    add hl,hl
    ld de,(ARG_PTR)
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld a,d
    xor 128
    ld c,a
    ld a,(TMP+1)
    xor 128
    cp c
    jr c,arg_update
    jr nz,arg_next
    ld a,(TMP)
    cp e
    jr c,arg_update
    jr arg_next
arg_update:
    ld (TMP),de
    ld a,(RMS_COUNT)
    ld (BPE_IDX),a
arg_next:
    ld hl,RMS_COUNT
    inc (hl)
    jr arg_loop
arg_done:
    ld a,(BPE_IDX)
    ret
"""


def build_loader_text() -> str:
    return (
        "From disk/soulcpc.dsk:\n\n"
        "RUN\"SOUL.BAS\"\n\n"
        "Or load manually on an Amstrad CPC with AMSDOS:\n\n"
        f"MEMORY &{BASIC_TOP:04X}\n"
        "LOAD \"SOULW.BIN\"\n"
        "LOAD \"SOULCPC.BIN\"\n"
        f"CALL &{CODE_ADDR:04X}\n"
    )


def main(argv=None):
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Soul Player CPC builder")
    parser.add_argument("--soul", default=str(repo_root / "models" / "soul.bin"))
    parser.add_argument("--tokenizer", default=str(repo_root / "models" / "tokenizer.json"))
    parser.add_argument("--output", default=str(repo_root / "disk"))
    parser.add_argument("--asm", action="store_true", help="also write generated Z80 assembly")
    args = parser.parse_args(argv)

    soul_path = Path(args.soul)
    tok_path = Path(args.tokenizer)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 55)
    print("  SOUL CPC BUILDER — Z80 / AMSDOS")
    print("=" * 55)

    if not soul_path.exists():
        print(f"ERROR: {soul_path} not found")
        return 1
    if not tok_path.exists():
        print(f"ERROR: {tok_path} not found")
        return 1

    soul_blob, tensor_info = parse_soul_for_c64(soul_path)
    tok_offsets, tok_strings, tok_merges = build_tokenizer_tables(tok_path)
    print(f"  Weights: {len(soul_blob)} bytes at &{WEIGHTS_ADDR:04X}-&{WEIGHTS_ADDR + len(soul_blob):04X}")
    print(f"  Buffers: &{BUF_BASE:04X}-&{BUF_END:04X}")

    code, source, labels = build_program(soul_blob, tensor_info, tok_offsets, tok_strings, tok_merges)
    code_end = CODE_ADDR + len(code)
    print(f"  Code:    {len(code)} bytes at &{CODE_ADDR:04X}-&{code_end:04X}")
    if code_end > 0xA700:
        print("  WARNING: code extends above &A700, which may overlap AMSDOS workspace on some systems.")

    weights_file = amsdos_header("SOULW", "BIN", soul_blob, WEIGHTS_ADDR, WEIGHTS_ADDR) + soul_blob
    code_file = amsdos_header("SOULCPC", "BIN", code, CODE_ADDR, CODE_ADDR) + code
    loader_file = build_basic_loader_file()
    dsk = build_dsk_data_format([
        ("SOULW.BIN", weights_file),
        ("SOULCPC.BIN", code_file),
        ("SOUL.BAS", loader_file),
    ])

    (out_dir / "soulw.bin").write_bytes(weights_file)
    (out_dir / "soulcpc.bin").write_bytes(code_file)
    (out_dir / "soulcpc.dsk").write_bytes(dsk)
    (out_dir / "soulcpc_loader.txt").write_text(build_loader_text(), encoding="ascii")
    if args.asm:
        (out_dir / "soulcpc.asm").write_text(source, encoding="ascii")

    print(f"  {out_dir / 'soulw.bin'}: {len(weights_file)} bytes")
    print(f"  {out_dir / 'soulcpc.bin'}: {len(code_file)} bytes")
    print(f"  {out_dir / 'soulcpc.dsk'}: {len(dsk)} bytes")
    print(f"  {out_dir / 'soulcpc_loader.txt'}")
    print("\n  RUN\"SOUL.BAS\"")
    print("\n  Or manually:")
    print(f"  MEMORY &{BASIC_TOP:04X}")
    print("  LOAD \"SOULW.BIN\"")
    print("  LOAD \"SOULCPC.BIN\"")
    print(f"  CALL &{CODE_ADDR:04X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
