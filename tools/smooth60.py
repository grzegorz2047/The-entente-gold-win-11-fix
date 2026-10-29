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
G_TICK, G_TS, G_QPF, G_NOW, G_TMP, G_ALPHA, G_TIMERRES, G_EXTRA = (DATA + o for o in (0, 8, 16, 24, 32, 40, 48, 56))
GetModuleHandleA, GetProcAddress = 0x9c88b8, 0x9c8924
TABLE = DATA + 0x100
R_TICK = TABLE + N * ENTRY                                     # tooltip replay: tick, count, entries
R_N = R_TICK + 4
R_ENT = R_TICK + 16
R_MAX, R_CHARS = 4, 256
R_ESZ = 20 + 2 * R_CHARS                                       # x, y, arg3, colour, arg5, text
DATA_SIZE = R_ENT + R_MAX * R_ESZ - DATA

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
    cmp dword ptr [{G_TIMERRES:#x}], 0  ; once: 1 ms timer resolution, otherwise Sleep(5) can take 15.6 ms
    jne timer_ok
    mov dword ptr [{G_TIMERRES:#x}], 1
    pushal
    push STR_WINMM
    call dword ptr [{GetModuleHandleA:#x}]
    test eax, eax
    je timer_skip
    push STR_TBP
    push eax
    call dword ptr [{GetProcAddress:#x}]
    test eax, eax
    je timer_skip
    push 1
    call eax
timer_skip:
    popal
timer_ok:
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
    mov dword ptr [{G_EXTRA:#x}], 1
    call {RENDER:#x}
    mov dword ptr [{G_EXTRA:#x}], 0
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

; ---------------- button tooltip: replay in the extra frames ----------------
; A button draws its tooltip (0x4f8aac / 0x4f8ad5, text method 0x4fdc90 on the text object 0x9a5e98,
; thiscall, 6 args, ret 0x18) only when the hover message arrives, i.e. once per game tick. Record those
; calls with a copy of the text and issue them again in the extra frames of the same tick, before the
; queued texts are drawn (0x42b4dc).
tip_record:
    pushal
    mov eax, dword ptr [{G_TICK:#x}]
    cmp eax, dword ptr [{R_TICK:#x}]
    je tr_same
    mov dword ptr [{R_TICK:#x}], eax
    mov dword ptr [{R_N:#x}], 0
tr_same:
    cmp dword ptr [{G_EXTRA:#x}], 0
    jne tr_skip
    mov ebx, dword ptr [{R_N:#x}]
    cmp ebx, {R_MAX}
    jae tr_skip
    imul edi, ebx, {R_ESZ}
    add edi, {R_ENT:#x}
    mov eax, dword ptr [esp + 36]
    mov dword ptr [edi], eax
    mov eax, dword ptr [esp + 40]
    mov dword ptr [edi + 4], eax
    mov eax, dword ptr [esp + 48]
    mov dword ptr [edi + 8], eax
    mov eax, dword ptr [esp + 52]
    mov dword ptr [edi + 12], eax
    mov eax, dword ptr [esp + 56]
    mov dword ptr [edi + 16], eax
    mov esi, dword ptr [esp + 44]
    add edi, 20
    mov ecx, {R_CHARS - 1}
tr_copy:
    mov ax, word ptr [esi]
    mov word ptr [edi], ax
    add esi, 2
    add edi, 2
    test ax, ax
    je tr_done
    dec ecx
    jnz tr_copy
    mov word ptr [edi], 0
tr_done:
    inc dword ptr [{R_N:#x}]
tr_skip:
    popal
    jmp 0x40171c

tip_replay:
    cmp dword ptr [{G_EXTRA:#x}], 0
    je rp_ret
    mov eax, dword ptr [{G_TICK:#x}]
    cmp eax, dword ptr [{R_TICK:#x}]
    jne rp_ret
    pushal
    xor ebx, ebx
rp_loop:
    cmp ebx, dword ptr [{R_N:#x}]
    jae rp_end
    imul esi, ebx, {R_ESZ}
    add esi, {R_ENT:#x}
    push dword ptr [esi + 16]
    push dword ptr [esi + 12]
    push dword ptr [esi + 8]
    lea eax, [esi + 20]
    push eax
    push dword ptr [esi + 4]
    push dword ptr [esi]
    mov ecx, 0x9a5e98
    call 0x40171c
    inc ebx
    jmp rp_loop
rp_end:
    popal
rp_ret:
    jmp 0x4032a1                        ; original call: draw the queued texts (0x4fe270)

; ---------------- 0x42b242: periodic job of the renderer (every 20th logic tick, 7-45 ms) ----------------
; The renderer tests the logic tick counter, so in the original it ran once per 20 ticks; the extra frames
; would repeat it in the same tick. Run it only in the tick's own frame.
periodic_job:
    cmp dword ptr [{G_EXTRA:#x}], 0
    jne pj_skip
    jmp 0x4cd870
pj_skip:
    ret
'''

# keystone treats ';' as a statement separator: strip comments first
asm_template = '\n'.join(l.split(';')[0] for l in asm.splitlines())
ks = Ks(KS_ARCH_X86, KS_MODE_32)
STRINGS = [b'WINMM.dll', b'timeBeginPeriod']
strings_at = CODE + 0x1000                         # any 32-bit value, so pushes get their final size
while True:
    s_winmm, s_tbp = strings_at, strings_at + len(STRINGS[0]) + 1
    src_asm = asm_template.replace('STR_WINMM', hex(s_winmm)).replace('STR_TBP', hex(s_tbp))
    code = bytes(ks.asm(src_asm, CODE)[0])
    if CODE + len(code) == strings_at:
        break
    strings_at = CODE + len(code)
code += b''.join(x + b'\0' for x in STRINGS)
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
expect(0x42b242, 'e81660fdff')                   # call 0x40125d (-> 0x4cd870)
patch_branch(b'\xe8', 0x42b242, label('periodic_job'))
expect(0x42b4dc, 'e8c07dfdff')                   # call 0x4032a1 (draws the queued texts)
expect(0x4f8aac, 'e86b8cf0ff')                   # call 0x40171c (tooltip line 1)
expect(0x4f8ad5, 'e8428cf0ff')                   # call 0x40171c (tooltip line 2)
patch_branch(b'\xe8', 0x42b4dc, label('tip_replay'))
patch_branch(b'\xe8', 0x4f8aac, label('tip_record'))
patch_branch(b'\xe8', 0x4f8ad5, label('tip_record'))

# .reloc: grow the virtual size for our data and make the section RWX, non-discardable
hdr = reloc.get_file_offset()
vsize = (reloc.SizeOfRawData + DATA_SIZE + 0xfff) & ~0xfff
struct.pack_into('<I', data, hdr + 8, vsize)
struct.pack_into('<I', data, hdr + 36, (reloc.Characteristics | 0xE0000020) & ~0x02000000)
size_of_image = (reloc.VirtualAddress + vsize + 0xfff) & ~0xfff
struct.pack_into('<I', data, pe.OPTIONAL_HEADER.get_file_offset() + 56, size_of_image)

open(dst, 'wb').write(data)
print(f'code {len(code)} bytes at {CODE:#x}, data {DATA_SIZE:#x} bytes at {DATA:#x}, SizeOfImage {size_of_image:#x}')
