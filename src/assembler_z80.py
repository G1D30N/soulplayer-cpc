#!/usr/bin/env python3
"""Tiny Z80 assembler for the CPC build target.

This intentionally implements only the instruction subset used by the
generated Soul Player CPC runtime. It mirrors the existing 6502 builder
philosophy: no external assembler dependency, labels, patches, and raw bytes.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass


REG8 = {"b": 0, "c": 1, "d": 2, "e": 3, "h": 4, "l": 5, "(hl)": 6, "a": 7}
REG16 = {"bc": 0, "de": 1, "hl": 2, "sp": 3}
REG16_STK = {"bc": 0, "de": 1, "hl": 2, "af": 3}

COND_JP = {
    "nz": 0xC2, "z": 0xCA, "nc": 0xD2, "c": 0xDA,
    "po": 0xE2, "pe": 0xEA, "p": 0xF2, "m": 0xFA,
}
COND_CALL = {
    "nz": 0xC4, "z": 0xCC, "nc": 0xD4, "c": 0xDC,
    "po": 0xE4, "pe": 0xEC, "p": 0xF4, "m": 0xFC,
}
COND_RET = {
    "nz": 0xC0, "z": 0xC8, "nc": 0xD0, "c": 0xD8,
    "po": 0xE0, "pe": 0xE8, "p": 0xF0, "m": 0xF8,
}
COND_JR = {"nz": 0x20, "z": 0x28, "nc": 0x30, "c": 0x38}


@dataclass
class Patch:
    foff: int
    expr: str
    kind: str
    line: int


class Z80Assembler:
    def __init__(self, org: int = 0x8000, constants: dict[str, int] | None = None):
        self.org = org
        self.buf = bytearray()
        self.labels: dict[str, int] = {}
        self.constants = dict(constants or {})
        self.patches: list[Patch] = []

    @property
    def pc(self) -> int:
        return self.org + len(self.buf)

    def emit(self, *bs: int) -> None:
        self.buf.extend(b & 0xFF for b in bs)

    def label(self, name: str, line_no: int) -> None:
        if name in self.labels:
            raise ValueError(f"line {line_no}: duplicate label {name}")
        self.labels[name] = self.pc

    def assemble(self, source: str) -> bytes:
        for line_no, raw in enumerate(source.splitlines(), 1):
            line = self._strip_comment(raw).strip()
            if not line:
                continue
            while True:
                m = re.match(r"^([A-Za-z_.$][\w.$]*):\s*(.*)$", line)
                if not m:
                    break
                self.label(m.group(1), line_no)
                line = m.group(2).strip()
                if not line:
                    break
            if line:
                self._assemble_line(line, line_no)
        self.resolve()
        return bytes(self.buf)

    def resolve(self) -> None:
        for p in self.patches:
            try:
                value = self.eval_expr(p.expr)
            except ValueError as exc:
                raise ValueError(f"line {p.line}: cannot resolve {p.expr!r}: {exc}") from exc
            if p.kind == "abs16":
                self.buf[p.foff] = value & 0xFF
                self.buf[p.foff + 1] = (value >> 8) & 0xFF
            elif p.kind == "byte":
                self.buf[p.foff] = value & 0xFF
            elif p.kind == "rel8":
                offset = value - (self.org + p.foff + 1)
                if offset < -128 or offset > 127:
                    raise ValueError(
                        f"line {p.line}: relative branch to {p.expr} out of range ({offset})"
                    )
                self.buf[p.foff] = offset & 0xFF
            else:
                raise ValueError(f"line {p.line}: unknown patch kind {p.kind}")

    def eval_expr(self, expr: str) -> int:
        expr = expr.strip()
        if not expr:
            raise ValueError("empty expression")
        total = 0
        sign = 1
        for part in re.split(r"([+-])", expr.replace(" ", "")):
            if not part:
                continue
            if part == "+":
                sign = 1
                continue
            if part == "-":
                sign = -1
                continue
            total += sign * self._eval_term(part)
            sign = 1
        return total & 0xFFFF_FFFF

    def _eval_term(self, term: str) -> int:
        if term.startswith("'") and term.endswith("'") and len(term) >= 3:
            return ord(term[1])
        if term.startswith("$"):
            return int(term[1:], 16)
        if term.startswith("&"):
            return int(term[1:], 16)
        if term.lower().startswith("0x"):
            return int(term, 16)
        if re.fullmatch(r"\d+", term):
            return int(term, 10)
        if term in self.labels:
            return self.labels[term]
        if term in self.constants:
            return self.constants[term]
        raise ValueError(f"unknown symbol {term!r}")

    def _emit_expr8(self, expr: str, line_no: int) -> None:
        foff = len(self.buf)
        self.emit(0)
        try:
            self.buf[foff] = self.eval_expr(expr) & 0xFF
        except ValueError:
            self.patches.append(Patch(foff, expr, "byte", line_no))

    def _emit_expr16(self, expr: str, line_no: int) -> None:
        foff = len(self.buf)
        self.emit(0, 0)
        try:
            value = self.eval_expr(expr)
            self.buf[foff] = value & 0xFF
            self.buf[foff + 1] = (value >> 8) & 0xFF
        except ValueError:
            self.patches.append(Patch(foff, expr, "abs16", line_no))

    def _emit_rel8(self, expr: str, line_no: int) -> None:
        foff = len(self.buf)
        self.emit(0)
        self.patches.append(Patch(foff, expr, "rel8", line_no))

    def _strip_comment(self, line: str) -> str:
        in_quote = False
        in_squote = False
        out = []
        for ch in line:
            if ch == '"':
                in_quote = not in_quote
            elif ch == "'":
                in_squote = not in_squote
            if ch == ";" and not in_quote and not in_squote:
                break
            out.append(ch)
        return "".join(out)

    def _split_operands(self, text: str) -> list[str]:
        if not text:
            return []
        lexer = shlex.shlex(text, posix=False)
        lexer.whitespace = ","
        lexer.whitespace_split = True
        lexer.commenters = ""
        return [x.strip() for x in lexer if x.strip()]

    def _assemble_line(self, line: str, line_no: int) -> None:
        parts = line.split(None, 1)
        op = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""
        try:
            args = self._split_operands(rest)
        except ValueError as exc:
            raise ValueError(f"line {line_no}: {exc}: {line}") from exc

        if op in ("db", ".db"):
            for arg in args:
                if len(arg) >= 2 and arg[0] == '"' and arg[-1] == '"':
                    for ch in bytes(arg[1:-1], "ascii"):
                        self.emit(ch)
                else:
                    self._emit_expr8(arg, line_no)
            return
        if op in ("dw", ".dw"):
            for arg in args:
                self._emit_expr16(arg, line_no)
            return
        if op in ("defs", "ds", ".ds"):
            if len(args) not in (1, 2):
                raise ValueError(f"line {line_no}: {op} expects count[,fill]")
            count = self.eval_expr(args[0])
            fill = self.eval_expr(args[1]) if len(args) == 2 else 0
            self.emit(*([fill & 0xFF] * count))
            return

        getattr(self, f"_op_{op}", self._unknown)(args, line_no)

    def _unknown(self, args: list[str], line_no: int) -> None:
        raise ValueError(f"line {line_no}: unsupported instruction")

    def _is_abs_mem(self, arg: str) -> bool:
        a = arg.lower()
        return a.startswith("(") and a.endswith(")") and a not in ("(hl)", "(bc)", "(de)", "(sp)")

    def _mem_expr(self, arg: str) -> str:
        return arg.strip()[1:-1].strip()

    def _op_ld(self, args: list[str], line_no: int) -> None:
        if len(args) != 2:
            raise ValueError(f"line {line_no}: ld expects two operands")
        dst, src = args
        dl, sl = dst.lower(), src.lower()

        if dl in REG8:
            if sl in REG8:
                self.emit(0x40 + REG8[dl] * 8 + REG8[sl])
                return
            if self._is_abs_mem(src) and dl == "a":
                self.emit(0x3A)
                self._emit_expr16(self._mem_expr(src), line_no)
                return
            if sl == "(bc)" and dl == "a":
                self.emit(0x0A)
                return
            if sl == "(de)" and dl == "a":
                self.emit(0x1A)
                return
            self.emit(0x06 + REG8[dl] * 8)
            self._emit_expr8(src, line_no)
            return

        if dl in REG16:
            if self._is_abs_mem(src):
                prefix = {"bc": 0x4B, "de": 0x5B, "hl": None, "sp": 0x7B}[dl]
                if dl == "hl":
                    self.emit(0x2A)
                else:
                    self.emit(0xED, prefix)
                self._emit_expr16(self._mem_expr(src), line_no)
                return
            self.emit(0x01 + REG16[dl] * 0x10)
            self._emit_expr16(src, line_no)
            return

        if dl == "sp" and sl == "hl":
            self.emit(0xF9)
            return

        if dl == "(hl)":
            if sl in REG8:
                self.emit(0x70 + REG8[sl])
                return
            self.emit(0x36)
            self._emit_expr8(src, line_no)
            return

        if dl == "(bc)" and sl == "a":
            self.emit(0x02)
            return
        if dl == "(de)" and sl == "a":
            self.emit(0x12)
            return

        if self._is_abs_mem(dst):
            expr = self._mem_expr(dst)
            if sl == "a":
                self.emit(0x32)
                self._emit_expr16(expr, line_no)
                return
            if sl in ("bc", "de", "hl", "sp"):
                prefix = {"bc": 0x43, "de": 0x53, "hl": None, "sp": 0x73}[sl]
                if sl == "hl":
                    self.emit(0x22)
                else:
                    self.emit(0xED, prefix)
                self._emit_expr16(expr, line_no)
                return

        raise ValueError(f"line {line_no}: unsupported ld {dst},{src}")

    def _alu_a(self, name: str, base_r: int, imm: int, args: list[str], line_no: int) -> None:
        if len(args) == 2:
            if args[0].lower() != "a":
                raise ValueError(f"line {line_no}: {name} first operand must be A")
            src = args[1]
        elif len(args) == 1:
            src = args[0]
        else:
            raise ValueError(f"line {line_no}: {name} expects one operand")
        sl = src.lower()
        if sl in REG8:
            self.emit(base_r + REG8[sl])
        else:
            self.emit(imm)
            self._emit_expr8(src, line_no)

    def _op_add(self, args: list[str], line_no: int) -> None:
        if len(args) != 2:
            raise ValueError(f"line {line_no}: add expects two operands")
        dst, src = args[0].lower(), args[1].lower()
        if dst == "hl" and src in REG16:
            self.emit(0x09 + REG16[src] * 0x10)
            return
        self._alu_a("add", 0x80, 0xC6, args, line_no)

    def _op_adc(self, args: list[str], line_no: int) -> None:
        if len(args) == 2 and args[0].lower() == "hl" and args[1].lower() in REG16:
            self.emit(0xED, 0x4A + REG16[args[1].lower()] * 0x10)
            return
        self._alu_a("adc", 0x88, 0xCE, args, line_no)

    def _op_sbc(self, args: list[str], line_no: int) -> None:
        if len(args) == 2 and args[0].lower() == "hl" and args[1].lower() in REG16:
            self.emit(0xED, 0x42 + REG16[args[1].lower()] * 0x10)
            return
        self._alu_a("sbc", 0x98, 0xDE, args, line_no)

    def _op_sub(self, args: list[str], line_no: int) -> None:
        self._alu_a("sub", 0x90, 0xD6, args, line_no)

    def _op_and(self, args: list[str], line_no: int) -> None:
        self._alu_a("and", 0xA0, 0xE6, args, line_no)

    def _op_xor(self, args: list[str], line_no: int) -> None:
        self._alu_a("xor", 0xA8, 0xEE, args, line_no)

    def _op_or(self, args: list[str], line_no: int) -> None:
        self._alu_a("or", 0xB0, 0xF6, args, line_no)

    def _op_cp(self, args: list[str], line_no: int) -> None:
        self._alu_a("cp", 0xB8, 0xFE, args, line_no)

    def _op_inc(self, args: list[str], line_no: int) -> None:
        if len(args) != 1:
            raise ValueError(f"line {line_no}: inc expects one operand")
        a = args[0].lower()
        if a in REG8:
            self.emit(0x04 + REG8[a] * 8)
            return
        if a in REG16:
            self.emit(0x03 + REG16[a] * 0x10)
            return
        raise ValueError(f"line {line_no}: unsupported inc {args[0]}")

    def _op_dec(self, args: list[str], line_no: int) -> None:
        if len(args) != 1:
            raise ValueError(f"line {line_no}: dec expects one operand")
        a = args[0].lower()
        if a in REG8:
            self.emit(0x05 + REG8[a] * 8)
            return
        if a in REG16:
            self.emit(0x0B + REG16[a] * 0x10)
            return
        raise ValueError(f"line {line_no}: unsupported dec {args[0]}")

    def _cb_reg(self, args: list[str], line_no: int, base: int) -> None:
        if len(args) != 1 or args[0].lower() not in REG8:
            raise ValueError(f"line {line_no}: unsupported CB instruction")
        self.emit(0xCB, base + REG8[args[0].lower()])

    def _op_rl(self, args: list[str], line_no: int) -> None: self._cb_reg(args, line_no, 0x10)
    def _op_rr(self, args: list[str], line_no: int) -> None: self._cb_reg(args, line_no, 0x18)
    def _op_sla(self, args: list[str], line_no: int) -> None: self._cb_reg(args, line_no, 0x20)
    def _op_sra(self, args: list[str], line_no: int) -> None: self._cb_reg(args, line_no, 0x28)
    def _op_srl(self, args: list[str], line_no: int) -> None: self._cb_reg(args, line_no, 0x38)

    def _op_bit(self, args: list[str], line_no: int) -> None:
        if len(args) != 2 or args[1].lower() not in REG8:
            raise ValueError(f"line {line_no}: bit expects bit,reg")
        bit = self.eval_expr(args[0])
        if bit < 0 or bit > 7:
            raise ValueError(f"line {line_no}: bit index out of range")
        self.emit(0xCB, 0x40 + bit * 8 + REG8[args[1].lower()])

    def _op_jp(self, args: list[str], line_no: int) -> None:
        if len(args) == 1:
            self.emit(0xC3)
            self._emit_expr16(args[0], line_no)
            return
        if len(args) == 2 and args[0].lower() in COND_JP:
            self.emit(COND_JP[args[0].lower()])
            self._emit_expr16(args[1], line_no)
            return
        raise ValueError(f"line {line_no}: unsupported jp")

    def _op_jr(self, args: list[str], line_no: int) -> None:
        if len(args) == 1:
            self.emit(0x18)
            self._emit_rel8(args[0], line_no)
            return
        if len(args) == 2 and args[0].lower() in COND_JR:
            self.emit(COND_JR[args[0].lower()])
            self._emit_rel8(args[1], line_no)
            return
        raise ValueError(f"line {line_no}: unsupported jr")

    def _op_djnz(self, args: list[str], line_no: int) -> None:
        if len(args) != 1:
            raise ValueError(f"line {line_no}: djnz expects one operand")
        self.emit(0x10)
        self._emit_rel8(args[0], line_no)

    def _op_call(self, args: list[str], line_no: int) -> None:
        if len(args) == 1:
            self.emit(0xCD)
            self._emit_expr16(args[0], line_no)
            return
        if len(args) == 2 and args[0].lower() in COND_CALL:
            self.emit(COND_CALL[args[0].lower()])
            self._emit_expr16(args[1], line_no)
            return
        raise ValueError(f"line {line_no}: unsupported call")

    def _op_ret(self, args: list[str], line_no: int) -> None:
        if not args:
            self.emit(0xC9)
            return
        if len(args) == 1 and args[0].lower() in COND_RET:
            self.emit(COND_RET[args[0].lower()])
            return
        raise ValueError(f"line {line_no}: unsupported ret")

    def _op_push(self, args: list[str], line_no: int) -> None:
        if len(args) != 1 or args[0].lower() not in REG16_STK:
            raise ValueError(f"line {line_no}: unsupported push")
        self.emit(0xC5 + REG16_STK[args[0].lower()] * 0x10)

    def _op_pop(self, args: list[str], line_no: int) -> None:
        if len(args) != 1 or args[0].lower() not in REG16_STK:
            raise ValueError(f"line {line_no}: unsupported pop")
        self.emit(0xC1 + REG16_STK[args[0].lower()] * 0x10)

    def _op_rlca(self, args: list[str], line_no: int) -> None: self.emit(0x07)
    def _op_rrca(self, args: list[str], line_no: int) -> None: self.emit(0x0F)
    def _op_rla(self, args: list[str], line_no: int) -> None: self.emit(0x17)
    def _op_rra(self, args: list[str], line_no: int) -> None: self.emit(0x1F)
    def _op_scf(self, args: list[str], line_no: int) -> None: self.emit(0x37)
    def _op_ccf(self, args: list[str], line_no: int) -> None: self.emit(0x3F)
    def _op_cpl(self, args: list[str], line_no: int) -> None: self.emit(0x2F)
    def _op_nop(self, args: list[str], line_no: int) -> None: self.emit(0x00)
    def _op_di(self, args: list[str], line_no: int) -> None: self.emit(0xF3)
    def _op_ei(self, args: list[str], line_no: int) -> None: self.emit(0xFB)

    def _op_ex(self, args: list[str], line_no: int) -> None:
        if len(args) == 2 and args[0].lower() == "de" and args[1].lower() == "hl":
            self.emit(0xEB)
            return
        raise ValueError(f"line {line_no}: unsupported ex")


def assemble_z80(source: str, org: int, constants: dict[str, int] | None = None) -> tuple[bytes, dict[str, int]]:
    asm = Z80Assembler(org=org, constants=constants)
    code = asm.assemble(source)
    return code, asm.labels
