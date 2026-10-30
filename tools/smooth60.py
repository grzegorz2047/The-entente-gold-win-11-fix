"""Smooth rendering for The Entente: extra frames between game ticks with interpolated unit positions.

Applied on top of build_patched_exe.py output. usage: python smooth60.py IN.exe OUT.exe

The game runs logic and rendering in one loop and sleeps until the tick (game-speed value, 51 ms by
default) is over, so it shows ~20 fps. This keeps the logic untouched and only fills the sleep:
- 0x535530 (end of every main-loop iteration, stores GetTickCount as the tick start) also stores a
  QueryPerformanceCounter timestamp and bumps our tick counter.
- 0x46e2d5 (Sleep until the next tick) becomes smooth_wait: while more than one frame of the tick
  remains it renders another frame (0x42b1d0, which ends with Flip) instead of sleeping. Only in the
  map view: not in menus or in the alternate render path. While edge-scrolling the iterations between
  the ticks only move the camera and draw (logic skipped), so the game keeps its pace (see scroll_wait). An extra frame is
  also skipped when less time is left than the last extra frame took, so a slow one (the camera
  being dragged on the minimap redraws the whole terrain) does not stretch the tick.
- 0x46e289: the loop skipped the wait altogether when the camera was moved by other means than
  edge scrolling (scroll flag 0x8be3c4 = 3 while the mouse button is held on the minimap, 10 for a
  camera jump), so the logic ran once per rendered frame. Harmless at the original ~12 fps, but with
  fast rendering the game ran up to 3x faster while the button was held. These cases now wait for
  the end of the tick like the plain map view.
- 0x5187f0 draws one unit (thiscall, arg = unit; position floats at +0x1c x, +0x20 y, +0x24, +0x28).
  It is wrapped: the unit's position is replaced by prev + (cur - prev) * alpha for the duration of
  the draw and restored right after, so game logic never sees it. prev/cur are the positions seen
  at the last two ticks; alpha = time since tick start / tick length. Jumps over 64 px snap.
- Animated building parts (0x4326f7) advance their frame only in the tick's own frame.
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
G_LAST = DATA + 64                                             # duration of the last extra frame (ms)
G_SKIP, G_STEP, G_MINSTEP = DATA + 72, DATA + 80, DATA + 88    # camera-only iteration next; QPC of the last scroll step
G_NOLOGIC = DATA + 96                                          # set by tick_start for the iteration it starts
G_CAMONLY, G_ITER = DATA + 100, DATA + 104                     # last iteration moved only the camera; its duration (ms)
GetModuleHandleA, GetProcAddress = 0x9c88b8, 0x9c8924
TABLE = DATA + 0x100
R_TICK = TABLE + N * ENTRY                                     # tooltip replay: tick, count, entries
R_N = R_TICK + 4
R_ENT = R_TICK + 16
R_MAX, R_CHARS = 8, 128
R_ESZ = 24 + 2 * R_CHARS                                       # call site, x, y, arg3, colour, arg5, text
ES_N = R_ENT + R_MAX * R_ESZ                                   # call sites seen in extra frames
ES = ES_N + 4
ES_MAX = 16
DATA_SIZE = ES + 4 * ES_MAX - DATA
assert DATA + DATA_SIZE <= 0xa0cc00, 'overlaps fps_counter.py data at 0xa0cc00'

GetTickCount, Sleep, QPC, QPF = 0x9c88e4, 0x9c8848, 0x9c87e8, 0x9c87f8
RENDER = 0x42b1d0
STEP, ITER = 33, 15                                            # ms between camera steps (30 tiles/s), minimum expected step iteration
POS = 0x1c                                                     # unit position block: 4 floats

asm = f'''
; ---------------- tick start: replaces 0x535530 ----------------
tick_start:
    cmp dword ptr [{G_SKIP:#x}], 0        ; next iteration only moves the camera: the tick goes on
    je ts_tick
    mov dword ptr [{G_SKIP:#x}], 0
    mov dword ptr [{G_NOLOGIC:#x}], 1
    jmp dword ptr [{GetTickCount:#x}]
ts_tick:
    mov dword ptr [{G_NOLOGIC:#x}], 0
    call dword ptr [{GetTickCount:#x}]
    mov dword ptr [0x9c549c], eax
    push eax
    push {G_TS:#x}
    call dword ptr [{QPC:#x}]
    inc dword ptr [{G_TICK:#x}]
    mov eax, dword ptr [{G_LAST:#x}]    ; forget a slow extra frame gradually (1/8 per tick)
    shr eax, 3
    sub dword ptr [{G_LAST:#x}], eax
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
    mov dword ptr [{G_EXTRA:#x}], 0
    mov al, byte ptr [0x8be3c4]         ; edge scrolling: camera steps between the ticks
    cmp al, 1
    je scroll_wait
    cmp al, 2
    je scroll_wait
    mov dword ptr [{G_SKIP:#x}], 0
    cmp dword ptr [0x9c2b04], 0         ; menu screens
    jne plain_sleep
    cmp byte ptr [0x998ee1], 0          ; alternate render path
    jne plain_sleep
wait_loop:
    call ms_left
    cmp eax, 17
    jl finish
    cmp eax, dword ptr [{G_LAST:#x}]    ; an extra frame as slow as the last one would overrun the tick
    jl finish
    push eax
    mov dword ptr [{G_EXTRA:#x}], 1
    call {RENDER:#x}
    mov dword ptr [{G_EXTRA:#x}], 0
    call ms_left
    pop edx
    sub edx, eax
    mov dword ptr [{G_LAST:#x}], edx
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

; ---------------- edge scrolling: camera steps more often than logic ticks ----------------
; The game moves the camera one tile per main-loop iteration and, while edge scrolling, sleeps only
; its own scroll delay (100, 40, 20 ... 0 ms as the scroll accelerates), so the logic ran once per
; camera step: 36-43 ticks/s instead of 19.6, the whole game ran twice as fast while scrolling.
; Now an iteration whose tick is not due yet only moves the camera and draws (logic 0x4b3770 skipped,
; the frame counts as an extra frame, the tick start is kept). Steps are at least STEP ms apart (or the
; game's longer delay), extra frames fill the time in between; a step that would end too close to the
; tick end is left out, so the logic iteration starts on time.
scroll_wait:
    mov dword ptr [{G_SKIP:#x}], 0
    cmp dword ptr [0x9c2b04], 0
    jne plain_sleep
    cmp byte ptr [0x998ee1], 0
    jne plain_sleep
    mov eax, dword ptr [esp + 4]        ; the game's scroll delay
    cmp eax, {STEP}
    jge sw_min
    mov eax, {STEP}
sw_min:
    mov dword ptr [{G_MINSTEP:#x}], eax
    cmp dword ptr [{G_ITER:#x}], 0        ; learn how long a camera-only iteration takes: the longest
    jle sw_decayed                      ; recent one, forgotten by 1 ms per scroll iteration
    dec dword ptr [{G_ITER:#x}]
sw_decayed:
    cmp dword ptr [{G_CAMONLY:#x}], 0
    je sw_learned
    mov dword ptr [{G_CAMONLY:#x}], 0
    call ms_since_step
    cmp eax, 100
    jae sw_learned
    cmp eax, dword ptr [{G_ITER:#x}]
    jle sw_learned
    mov dword ptr [{G_ITER:#x}], eax
sw_learned:
    call ms_to_step                     ; S: ms until the next camera step
    mov edx, eax
    call ms_left                        ; L: ms until the tick is due
    mov ecx, dword ptr [{G_ITER:#x}]
    cmp ecx, {ITER}
    jge sw_iter
    mov ecx, {ITER}
sw_iter:
    lea ecx, [edx + ecx + 2]
    cmp eax, ecx
    jle sw_wait                         ; the tick comes first: wait for it
    mov dword ptr [{G_SKIP:#x}], 1      ; camera-only iteration next
sw_wait:                                ; fill the wait with extra frames, like smooth_wait
    call sw_remaining
    cmp eax, 14
    jl sw_sleep
    cmp eax, dword ptr [{G_LAST:#x}]
    jl sw_sleep
    push eax
    mov dword ptr [{G_EXTRA:#x}], 1
    call {RENDER:#x}
    mov dword ptr [{G_EXTRA:#x}], 0
    call sw_remaining
    pop edx
    sub edx, eax
    mov dword ptr [{G_LAST:#x}], edx
    jmp sw_wait
sw_sleep:
    test eax, eax
    jle sw_go
    push eax
    call dword ptr [{Sleep:#x}]
sw_go:
    push {G_STEP:#x}
    call dword ptr [{QPC:#x}]
    ret 4

sw_remaining:                           ; eax = ms until the next iteration should start
    cmp dword ptr [{G_SKIP:#x}], 0
    je ms_left
    call ms_to_step
    push eax
    call ms_left                        ; never past the tick
    pop edx
    cmp eax, edx
    jle sr_ret
    mov eax, edx
sr_ret:
    ret

ms_to_step:                             ; eax = G_MINSTEP - ms since the last camera step (>= 0)
    call ms_since_step
    test eax, eax
    js ts_now
    mov ecx, eax
    mov eax, dword ptr [{G_MINSTEP:#x}]
    sub eax, ecx
    jns tsr
ts_now:
    xor eax, eax
tsr:
    ret

ms_since_step:                          ; eax = ms since the last camera step (negative: none yet)
    push {G_NOW:#x}
    call dword ptr [{QPC:#x}]
    cmp dword ptr [{G_QPF:#x}], 0
    je ss_none
    mov eax, dword ptr [{G_NOW:#x}]
    mov edx, dword ptr [{G_NOW + 4:#x}]
    sub eax, dword ptr [{G_STEP:#x}]
    sbb edx, dword ptr [{G_STEP + 4:#x}]
    mov dword ptr [{G_TMP:#x}], eax
    mov dword ptr [{G_TMP + 4:#x}], edx
    fild qword ptr [{G_TMP:#x}]
    mov dword ptr [{G_TMP:#x}], 1000
    fimul dword ptr [{G_TMP:#x}]
    fild qword ptr [{G_QPF:#x}]
    fdivp st(1), st(0)
    fistp dword ptr [{G_TMP:#x}]
    mov eax, dword ptr [{G_TMP:#x}]        ; overflow (no step yet) reads as 0x80000000
    ret
ss_none:
    mov eax, -1
    ret
ms_left:                                ; eax = ms left in this tick
    call elapsed_ms
    fistp dword ptr [{G_TMP:#x}]
    movzx eax, byte ptr [0x998ed0]
    movzx eax, byte ptr [eax + 0x998db0]
    sub eax, dword ptr [{G_TMP:#x}]
    ret

logic_gate:                             ; replaces the call of the logic update 0x4b3770 at 0x46e1ca
    cmp dword ptr [{G_NOLOGIC:#x}], 0
    je lg_run
    mov dword ptr [{G_NOLOGIC:#x}], 0
    mov dword ptr [{G_CAMONLY:#x}], 1
    mov dword ptr [{G_EXTRA:#x}], 1     ; camera-only iteration: draw it as an extra frame
    ret
lg_run:
    jmp 0x4038c3

; ---------------- texts drawn once per tick: replay in the extra frames ----------------
; Texts are queued with the method 0x4fdc90 (thiscall on the text object 0x9a5e98, 6 args, ret 0x18;
; every call goes through the thunk 0x40171c) and drawn by 0x4fe270 (called at 0x42b4dc). Most texts
; are queued every frame, but button tooltips only when the hover message arrives, once per game
; tick, so the extra frames lacked them. Every one-frame text (arg 4 = lifetime in frames = 1; the queue
; 0x4fe270 drops an entry when its lifetime runs out) queued in the tick's own frame is recorded; call
; sites also seen in extra frames are remembered as "every frame" and are not replayed, the rest is
; queued again in the extra frames of the same tick, before the queue is drawn.
text_hook:
    pushal
    cmp dword ptr [esp + 24], 0x9a5e98  ; this (ecx)
    jne th_done
    mov edx, dword ptr [esp + 32]       ; call site
    cmp dword ptr [{G_EXTRA:#x}], 0
    je th_main
    xor ecx, ecx                        ; extra frame: remember the call site
th_find:
    cmp ecx, dword ptr [{ES_N:#x}]
    jae th_add
    cmp dword ptr [ecx*4 + {ES:#x}], edx
    je th_done
    inc ecx
    jmp th_find
th_add:
    cmp ecx, {ES_MAX}
    jae th_done
    mov dword ptr [ecx*4 + {ES:#x}], edx
    inc dword ptr [{ES_N:#x}]
    jmp th_done
th_main:
    cmp dword ptr [esp + 48], 1         ; lifetime in frames: only one-frame texts need a replay
    jne th_done
    mov eax, dword ptr [{G_TICK:#x}]
    cmp eax, dword ptr [{R_TICK:#x}]
    je th_same
    mov dword ptr [{R_TICK:#x}], eax
    mov dword ptr [{R_N:#x}], 0
th_same:
    mov ebx, dword ptr [{R_N:#x}]
    cmp ebx, {R_MAX}
    jae th_done
    imul edi, ebx, {R_ESZ}
    add edi, {R_ENT:#x}
    mov dword ptr [edi], edx
    mov eax, dword ptr [esp + 36]
    mov dword ptr [edi + 4], eax
    mov eax, dword ptr [esp + 40]
    mov dword ptr [edi + 8], eax
    mov eax, dword ptr [esp + 48]
    mov dword ptr [edi + 12], eax
    mov eax, dword ptr [esp + 52]
    mov dword ptr [edi + 16], eax
    mov eax, dword ptr [esp + 56]
    mov dword ptr [edi + 20], eax
    mov esi, dword ptr [esp + 44]
    add edi, 24
    mov ecx, {R_CHARS - 1}
th_copy:
    mov ax, word ptr [esi]
    mov word ptr [edi], ax
    add esi, 2
    add edi, 2
    test ax, ax
    je th_copied
    dec ecx
    jnz th_copy
    mov word ptr [edi], 0
th_copied:
    inc dword ptr [{R_N:#x}]
th_done:
    popal
    jmp 0x4fdc90

text_replay:
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
    mov edx, dword ptr [esi]
    xor ecx, ecx
rp_find:
    cmp ecx, dword ptr [{ES_N:#x}]
    jae rp_draw
    cmp dword ptr [ecx*4 + {ES:#x}], edx
    je rp_next
    inc ecx
    jmp rp_find
rp_draw:
    push dword ptr [esi + 20]
    push dword ptr [esi + 16]
    push dword ptr [esi + 12]
    lea eax, [esi + 24]
    push eax
    push dword ptr [esi + 8]
    push dword ptr [esi + 4]
    mov ecx, 0x9a5e98
    call 0x4fdc90
rp_next:
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
expect(0x46e287, '3c027550')                      # cmp al, 2 / jne 0x46e2db (no wait at all)
data[off(0x46e28a)] = 0x46e2c7 - 0x46e28b         # -> jne 0x46e2c7: wait for the end of the tick
expect(0x46e2c0, '85c07e17')                      # test eax, eax / jle 0x46e2db: no wait at full scroll speed
data[off(0x46e2c2):off(0x46e2c2) + 2] = b'\x90\x90'  # smooth_wait paces every scroll step
expect(0x46e1ca, 'e8f456f9ff')                    # call 0x4038c3 (logic update 0x4b3770)
patch_branch(b'\xe8', 0x46e1ca, label('logic_gate'))
patch_branch(b'\xe9', 0x5187f0, label('unit_draw'), 1)
expect(0x42b242, 'e81660fdff')                   # call 0x40125d (-> 0x4cd870)
patch_branch(b'\xe8', 0x42b242, label('periodic_job'))
expect(0x42b4dc, 'e8c07dfdff')                   # call 0x4032a1 (draws the queued texts)
expect(0x40171c, 'e96fc50f00')                   # thunk: jmp 0x4fdc90 (queue a text)
patch_branch(b'\xe8', 0x42b4dc, label('text_replay'))
patch_branch(b'\xe9', 0x40171c, label('text_hook'))

# Animated building parts (saw of the sawmill, horses of the stable...; list [0x8be3b0], drawn at
# 0x4326c5) advance their frame by their speed each time they are drawn, i.e. once per tick in the
# original: with the extra frames they ran ~3x too fast. Advance only in the tick's own frame.
# The .reloc tail is full: the 16 bytes go to the end of build_patched_exe.py's cave in .text.
expect(0x4326f7, 'd9476cd84604')                 # fld [edi+0x6c] (speed); fadd [esi+4] (frame)
text = next(s for s in pe.sections if s.Name.startswith(b'.text'))
t_lo, t_hi = B + text.VirtualAddress, B + text.VirtualAddress + text.SizeOfRawData
ANIM = (max(va for va in range(t_hi - 0x400, t_hi) if data[off(va)]) + 16) & ~15
anim = bytes(ks.asm(f'''
    fld dword ptr [esi + 4]
    cmp dword ptr [{G_EXTRA:#x}], 0
    jne anim_keep
    fadd dword ptr [edi + 0x6c]
anim_keep:
    ret''', ANIM)[0])
assert ANIM + len(anim) <= t_hi and not any(data[off(ANIM):off(ANIM) + len(anim)]), '.text cave full'
data[off(ANIM):off(ANIM) + len(anim)] = anim
patch_branch(b'\xe8', 0x4326f7, ANIM, 1)

# .reloc: grow the virtual size for our data and make the section RWX, non-discardable
hdr = reloc.get_file_offset()
vsize = (reloc.SizeOfRawData + DATA_SIZE + 0xfff) & ~0xfff
struct.pack_into('<I', data, hdr + 8, vsize)
struct.pack_into('<I', data, hdr + 36, (reloc.Characteristics | 0xE0000020) & ~0x02000000)
size_of_image = (reloc.VirtualAddress + vsize + 0xfff) & ~0xfff
struct.pack_into('<I', data, pe.OPTIONAL_HEADER.get_file_offset() + 56, size_of_image)

open(dst, 'wb').write(data)
print(f'code {len(code)} bytes at {CODE:#x}, data {DATA_SIZE:#x} bytes at {DATA:#x}, SizeOfImage {size_of_image:#x}')
