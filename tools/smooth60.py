"""Smooth rendering for The Entente: extra frames between game ticks with interpolated unit positions.

Applied on top of build_patched_exe.py output. usage: python smooth60.py IN.exe OUT.exe

The game runs logic and rendering in one loop and sleeps until the tick (game-speed value, 51 ms by
default) is over, so it shows ~20 fps. This keeps the logic untouched and only fills the sleep:
- 0x535530 (end of every main-loop iteration, stores GetTickCount as the tick start) also stores a
  QueryPerformanceCounter timestamp and bumps our tick counter.
- 0x46e2d5 (Sleep until the next tick) becomes smooth_wait: while more than one frame of the tick
  remains it renders another frame (0x42b1d0, which ends with Flip) instead of sleeping. Only in the
  plain map view: not while scrolling, in menus, or in the alternate render path.
- 0x5187f0 draws one unit (thiscall, arg = unit; position floats at +0x1c x, +0x20 y, +0x24, +0x28).
  It is wrapped: the unit's position is replaced by prev + (cur - prev) * alpha for the duration of
  the draw and restored right after, so game logic never sees it. prev/cur are the positions seen
  at the last two ticks; alpha = time since tick start / tick length. Jumps over 64 px snap.
Code lives in the raw tail of .reloc (never applied: fixed image base), data in an extension of
.reloc's virtual size (zero-filled by the loader).
"""
import struct, sys
import pefile
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

src, dst = sys.argv[1:]
data = bytearray(open(src, 'rb').read())
pe = pefile.PE(data=bytes(data))
B = pe.OPTIONAL_HEADER.ImageBase
off = lambda va: pe.get_offset_from_rva(va - B)

def expect(va, hexbytes):
    got = bytes(data[off(va):off(va) + len(bytes.fromhex(hexbytes))])
    if got != bytes.fromhex(hexbytes):
        sys.exit(f'unexpected bytes at {va:#x}: {got.hex()}')

expect(0x535530, 'ff15e4889c00a39c549c00c3')
expect(0x46e2d5, 'ff1548889c00')
expect(0x5187f0, '81ecd8000000')
expect(0x51a2c4, '81c4d8000000c20400')           # single exit: add esp, 0xd8 / ret 4

reloc = next(s for s in pe.sections if s.Name.startswith(b'.reloc'))
CODE = (B + reloc.VirtualAddress + reloc.Misc_VirtualSize + 15) & ~15
CODE_END = B + reloc.VirtualAddress + reloc.SizeOfRawData
DATA = B + reloc.VirtualAddress + reloc.SizeOfRawData          # first byte past the raw data
N = 4096                                                       # interpolation table entries
ENTRY = 40                                                     # key, tick, prev[4 floats], cur[4 floats]
G_TICK, G_TS, G_QPF, G_NOW, G_TMP, G_ALPHA = (DATA + o for o in (0, 8, 16, 24, 32, 40))
TABLE = DATA + 0x100
DATA_SIZE = TABLE - DATA + N * ENTRY

GetTickCount, Sleep, QPC, QPF = 0x9c88e4, 0x9c8848, 0x9c87e8, 0x9c87f8
RENDER = 0x42b1d0
POS = 0x1c                                                     # unit position block: 4 floats

asm = f'''
; ---------------- tick start: replaces 0x535530 ----------------
tick_start:
    call dword ptr [{GetTickCount:#x}]
    mov dword ptr [0x9c549c], eax
    push eax
    push {G_TS:#x}
    call dword ptr [{QPC:#x}]
    inc dword ptr [{G_TICK:#x}]
    pop eax
    ret

; ---------------- milliseconds since tick start -> st(0) ----------------
elapsed_ms:
    cmp dword ptr [{G_QPF:#x}], 0
    jne have_qpf
    push {G_QPF:#x}
    call dword ptr [{QPF:#x}]
have_qpf:
    push {G_NOW:#x}
    call dword ptr [{QPC:#x}]
    mov eax, dword ptr [{G_NOW:#x}]
    mov edx, dword ptr [{G_NOW + 4:#x}]
    sub eax, dword ptr [{G_TS:#x}]
    sbb edx, dword ptr [{G_TS + 4:#x}]
    mov dword ptr [{G_TMP:#x}], eax
    mov dword ptr [{G_TMP + 4:#x}], edx
    fild qword ptr [{G_TMP:#x}]
    mov dword ptr [{G_TMP:#x}], 1000
    fimul dword ptr [{G_TMP:#x}]
    fild qword ptr [{G_QPF:#x}]
    fdivp st(1), st(0)
    ret

; ---------------- alpha in [0,1] -> [G_ALPHA] ----------------
calc_alpha:
    call elapsed_ms
    movzx eax, byte ptr [0x998ed0]
    movzx eax, byte ptr [eax + 0x998db0]
    test eax, eax
    jz alpha_one_pop
    mov dword ptr [{G_TMP:#x}], eax
    fidiv dword ptr [{G_TMP:#x}]
    fldz
    fcomip st(0), st(1)
    jbe not_neg
    fstp st(0)
    fldz
not_neg:
    fld1
    fcomip st(0), st(1)
    jae store_alpha
alpha_one_pop:
    fstp st(0)
    fld1
store_alpha:
    fstp dword ptr [{G_ALPHA:#x}]
    ret

; ---------------- interp_unit: eax = unit; overwrites its position with the interpolated one ----------
interp_unit:
    pushal
    mov ebp, eax
    mov ebx, eax
    shr ebx, 3
    and ebx, {N - 1}
    mov ecx, 32
probe:
    imul edi, ebx, {ENTRY}
    add edi, {TABLE:#x}
    mov edx, dword ptr [edi]
    cmp edx, ebp
    je found
    test edx, edx
    je new_entry
    inc ebx
    and ebx, {N - 1}
    dec ecx
    jnz probe
new_entry:
    mov dword ptr [edi], ebp
    mov edx, dword ptr [{G_TICK:#x}]
    mov dword ptr [edi + 4], edx
    jmp reset_both
found:
    mov edx, dword ptr [{G_TICK:#x}]
    cmp dword ptr [edi + 4], edx
    je same_tick
    mov dword ptr [edi + 4], edx
    lea esi, [edi + 24]                 ; prev = cur
    push edi
    lea edi, [edi + 8]
    mov ecx, 4
    rep movsd dword ptr es:[edi], dword ptr [esi]
    pop edi
    lea esi, [ebp + {POS}]              ; cur = unit position
    push edi
    lea edi, [edi + 24]
    mov ecx, 4
    rep movsd dword ptr es:[edi], dword ptr [esi]
    pop edi
    fld dword ptr [edi + 24]            ; snap when the unit moved more than 64 px in one tick
    fsub dword ptr [edi + 8]
    fabs
    fld dword ptr [edi + 28]
    fsub dword ptr [edi + 12]
    fabs
    faddp st(1), st(0)
    mov dword ptr [{G_TMP:#x}], 64
    fild dword ptr [{G_TMP:#x}]
    fcomip st(0), st(1)
    fstp st(0)
    jb reset_both
    jmp do_interp
same_tick:
    push edi                            ; position unchanged since this tick's first draw?
    lea esi, [ebp + {POS}]
    lea edi, [edi + 24]
    mov ecx, 4
    repe cmpsd dword ptr [esi], dword ptr es:[edi]
    pop edi
    je do_interp
reset_both:
    lea esi, [ebp + {POS}]
    push edi
    lea edi, [edi + 8]
    mov ecx, 4
    rep movsd dword ptr es:[edi], dword ptr [esi]
    pop edi
    lea esi, [ebp + {POS}]
    push edi
    lea edi, [edi + 24]
    mov ecx, 4
    rep movsd dword ptr es:[edi], dword ptr [esi]
    pop edi
    popal
    ret
do_interp:
    call calc_alpha
    xor ecx, ecx
lerp_loop:
    fld dword ptr [edi + ecx*4 + 24]
    fsub dword ptr [edi + ecx*4 + 8]
    fmul dword ptr [{G_ALPHA:#x}]
    fadd dword ptr [edi + ecx*4 + 8]
    fstp dword ptr [ebp + ecx*4 + {POS}]
    inc ecx
    cmp ecx, 4
    jb lerp_loop
    popal
    ret

; ---------------- wrapper of the unit draw method 0x5187f0 (thiscall, ret 4) ----------------
unit_draw:
    mov eax, dword ptr [esp + 4]
    push dword ptr [eax + {POS + 12}]
    push dword ptr [eax + {POS + 8}]
    push dword ptr [eax + {POS + 4}]
    push dword ptr [eax + {POS}]
    push eax
    call interp_unit
    push dword ptr [esp + 0x18]
    call unit_draw_orig
    pop ecx
    pop dword ptr [ecx + {POS}]
    pop dword ptr [ecx + {POS + 4}]
    pop dword ptr [ecx + {POS + 8}]
    pop dword ptr [ecx + {POS + 12}]
    ret 4
unit_draw_orig:
    sub esp, 0xd8
    jmp 0x5187f6

; ---------------- smooth_wait(ms): stdcall replacement for Sleep at 0x46e2d5 ----------------
smooth_wait:
    cmp byte ptr [0x8be3c4], 0          ; scrolling this tick
    jne plain_sleep
    cmp dword ptr [0x9c2b04], 0         ; menu screens
    jne plain_sleep
    cmp byte ptr [0x998ee1], 0          ; alternate render path
    jne plain_sleep
wait_loop:
    call elapsed_ms
    fistp dword ptr [{G_TMP:#x}]
    movzx eax, byte ptr [0x998ed0]
    movzx eax, byte ptr [eax + 0x998db0]
    sub eax, dword ptr [{G_TMP:#x}]     ; ms left in this tick
    cmp eax, 17
    jl finish
    call {RENDER:#x}
    jmp wait_loop
finish:
    test eax, eax
    jle done_wait
    push eax
    call dword ptr [{Sleep:#x}]
done_wait:
    ret 4
plain_sleep:
    jmp dword ptr [{Sleep:#x}]
'''

# keystone treats ';' as a statement separator: strip comments first
src_asm = '\n'.join(l.split(';')[0] for l in asm.splitlines())
ks = Ks(KS_ARCH_X86, KS_MODE_32)
code = bytes(ks.asm(src_asm, CODE)[0])
assert CODE + len(code) <= CODE_END, f'code too large: {len(code)} bytes'
assert not any(data[off(CODE):off(CODE) + len(code)]), 'reloc tail not empty'
data[off(CODE):off(CODE) + len(code)] = code

def label(name):
    head = src_asm.split('\n' + name + ':')[0]
    return CODE + len(bytes(ks.asm(head, CODE)[0])) if head.strip() else CODE

def patch_branch(op, at, to, pad=0):
    data[off(at):off(at) + 5 + pad] = op + struct.pack('<i', to - (at + 5)) + b'\x90' * pad

patch_branch(b'\xe9', 0x535530, label('tick_start'), 7)
patch_branch(b'\xe8', 0x46e2d5, label('smooth_wait'), 1)
patch_branch(b'\xe9', 0x5187f0, label('unit_draw'), 1)

# .reloc: grow the virtual size for our data and make the section RWX, non-discardable
hdr = reloc.get_file_offset()
vsize = (reloc.SizeOfRawData + DATA_SIZE + 0xfff) & ~0xfff
struct.pack_into('<I', data, hdr + 8, vsize)
struct.pack_into('<I', data, hdr + 36, (reloc.Characteristics | 0xE0000020) & ~0x02000000)
size_of_image = (reloc.VirtualAddress + vsize + 0xfff) & ~0xfff
struct.pack_into('<I', data, pe.OPTIONAL_HEADER.get_file_offset() + 56, size_of_image)

open(dst, 'wb').write(data)
print(f'code {len(code)} bytes at {CODE:#x}, data {DATA_SIZE:#x} bytes at {DATA:#x}, SizeOfImage {size_of_image:#x}')
