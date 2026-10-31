"""The Entente: even frame pacing at 60 Hz, and the building depth written without locking the z-buffer.

Applied last, in both variants (after prefetch.py). usage: python pacer.py IN.exe OUT.exe

Based on a prototype by ChatGPT (entente-render60), measured on the Steam install (market save over
the town, 1920x1200 zoomed out): the longest frame of each second 34-35 -> 27-28 ms (median), the
worst while scrolling 58 -> 36 ms, the logic pace unchanged (19.6 ticks/s).

Pacing. smooth60.py fills the wait for the next logic tick with extra frames, each started right
after the previous one, so the frames came in bursts: 26 ms (the tick's own frame) and two of
~13 ms. Now:
- 0x535530 (tick start, after smooth60.py's tick_start): the due time of the next tick is kept as
  the previous due time plus the tick length (51 ms), so late ticks do not shift the schedule; it
  starts again after a pause, a menu or a lag of more than 250 ms.
- 0x46e2d5 (the wait for the tick, smooth60.py's smooth_wait): in the plain map view an extra frame
  is drawn only while the next 60 Hz frame slot comes before the tick, otherwise the wait sleeps
  until the tick. Edge scrolling, menus and the alternate render path keep smooth60.py's wait.
- 0x42b8ce (end of every frame, before the Flip): the frame waits for its slot of a 60 Hz grid
  (QueryPerformanceCounter, 64-bit, so the comparison holds across the counter's low-dword wrap;
  a 32-bit version of the prototype hung after ~7 minutes). A frame that is late is shown at once;
  the grid starts again after a lag of more than 250 ms.

Depth. Each terrain redraw writes the depth of the buildings with the CPU into the locked z-buffer,
and dgVoodoo handles a page fault for the first write into every 4 KB page of a locked surface,
system memory or not. A system-memory z-buffer whose memory the game supplies (DDSD_LPSURFACE) is
not watched: the redraw writes there without a Lock (0x437ea4), filled with far depth first, and
one Blt puts it into the real z-buffer instead of the Unlock (0x438bd2). The surface is made again
when the z-buffer or the screen size changes; if anything fails, the game's own Lock is used.
The memory (4.6 MB, enough for 1920x1200) is a zero-filled extension of .reloc's virtual size, so
the file does not grow. The code is in the old relocation table, between prefetch.py's buffer and
mode_redraw.py's building layer.
"""
import struct, sys
import pefile
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

src, dst = sys.argv[1:]
data = bytearray(open(src, 'rb').read())
pe = pefile.PE(data=bytes(data))
B = pe.OPTIONAL_HEADER.ImageBase
off = lambda va: pe.get_offset_from_rva(va - B)
rel32 = lambda at: at + 5 + struct.unpack('<i', data[off(at) + 1:off(at) + 5])[0]

def expect(va, hexbytes):
    got = bytes(data[off(va):off(va) + len(bytes.fromhex(hexbytes))])
    if got != bytes.fromhex(hexbytes):
        sys.exit(f'unexpected bytes at {va:#x}: {got.hex()}')

TICK_AT, WAIT_AT, FRAME_AT = 0x535530, 0x46e2d5, 0x42b8ce
assert data[off(TICK_AT)] == 0xe9, 'smooth60.py first'          # jmp tick_start
assert data[off(WAIT_AT)] == 0xe8 and data[off(FRAME_AT)] == 0xe8   # call smooth_wait / the frame hooks
TICK_TO, WAIT_TO, FRAME_TO = rel32(TICK_AT), rel32(WAIT_AT), rel32(FRAME_AT)
ZLOCK_AT, ZUNLOCK_AT = 0x437ea4, 0x438bd2
expect(ZLOCK_AT, 'ff52648b94248c010000')        # call [edx+0x64] (Lock of the z-buffer); mov edx, [esp+0x18c]
expect(ZUNLOCK_AT, 'a1e8e15a00')                 # mov eax, [z-buffer]: its Unlock follows

GetTickCount, Sleep, QPC, QPF = 0x9c88e4, 0x9c8848, 0x9c87e8, 0x9c87f8
RENDER = 0x42b1d0
DDRAW, ZBUFFER, MODE = 0x5ae250, 0x5ae1e8, 0x5ae24c
G_EXTRA, G_SKIP, G_NOLOGIC = 0x9e4038, 0x9e4048, 0x9e4060     # smooth60.py's flags
RELOC_VA, RELOC_SIZE = 0x9cb000, 0x12bc0
CODE, CODE_END = RELOC_VA + 0xa000, RELOC_VA + 0xb000   # visibility.py follows
reloc = next(s for s in pe.sections if s.Name.startswith(b'.reloc'))
assert B + reloc.VirtualAddress == RELOC_VA and pe.sections[-1] is reloc
V = (RELOC_VA + reloc.Misc_VirtualSize + 0xfff) & ~0xfff        # zero-filled data
V_TICK, V_NOW, V_FREQ, V_DUE, V_REM = V, V + 8, V + 16, V + 24, V + 32
Z_SURF, Z_FOR, Z_MODE, Z_BYTES, Z_USED = V + 0x40, V + 0x44, V + 0x48, V + 0x4c, V + 0x50
DESC = V + 0x80                                  # DDSURFACEDESC2, 0x7c bytes
ZBUF, ZMAX = V + 0x1000, 1920 * 1200 * 2
V_END = (ZBUF + ZMAX + 0xfff) & ~0xfff

asm = f'''
p_tick:                                   ; instead of jmp tick_start at 0x535530
    call {TICK_TO:#x}
    pushfd
    pushal
    cmp dword ptr [0x9c2b04], 0           ; menu screens
    jne pt_reset
    cmp byte ptr [0x998ee1], 0            ; the alternate render path
    jne pt_reset
    cmp dword ptr [{G_NOLOGIC:#x}], 0     ; a camera-only iteration: no tick
    jne pt_done
    mov ebx, dword ptr [0x9c549c]         ; GetTickCount of this tick
    movzx ecx, byte ptr [0x998ed0]
    movzx ecx, byte ptr [ecx + 0x998db0]  ; the tick length (ms)
    cmp dword ptr [{V_TICK:#x}], 0
    je pt_first
    mov eax, ebx
    sub eax, dword ptr [{V_TICK:#x}]      ; how late this tick came
    cmp eax, 250
    jg pt_first
    cmp eax, -250
    jl pt_first
    add dword ptr [{V_TICK:#x}], ecx      ; the next one: a tick length after this one was due
    jmp pt_done
pt_first:
    add ebx, ecx
    mov dword ptr [{V_TICK:#x}], ebx
    jmp pt_done
pt_reset:
    mov dword ptr [{V_TICK:#x}], 0
pt_done:
    popal
    popfd
    ret

p_wait:                                   ; instead of call smooth_wait(ms) at 0x46e2d5 (stdcall)
    cmp dword ptr [0x9c2b04], 0
    jne pw_old
    cmp byte ptr [0x998ee1], 0
    jne pw_old
    mov al, byte ptr [0x8be3c4]           ; edge scrolling: smooth60.py's scroll_wait
    cmp al, 1
    je pw_old
    cmp al, 2
    je pw_old
    cmp dword ptr [{V_TICK:#x}], 0
    je pw_old
    cmp dword ptr [{V_FREQ:#x}], 0
    je pw_old
    mov dword ptr [{G_SKIP:#x}], 0
    mov dword ptr [{G_EXTRA:#x}], 0
    pushal
pw_loop:
    call dword ptr [{GetTickCount:#x}]
    mov ebx, dword ptr [{V_TICK:#x}]
    sub ebx, eax                          ; ms until the tick is due
    test ebx, ebx
    jle pw_done
    push {V_NOW:#x}
    call dword ptr [{QPC:#x}]
    mov eax, dword ptr [{V_DUE:#x}]
    mov edx, dword ptr [{V_DUE + 4:#x}]
    sub eax, dword ptr [{V_NOW:#x}]
    sbb edx, dword ptr [{V_NOW + 4:#x}]   ; until the next frame slot
    js pw_frame
    jne pw_sleep
    mov ecx, 1000
    mul ecx
    div dword ptr [{V_FREQ:#x}]
    cmp eax, ebx
    jg pw_sleep                           ; the tick comes first
pw_frame:
    mov dword ptr [{G_EXTRA:#x}], 1
    call {RENDER:#x}
    mov dword ptr [{G_EXTRA:#x}], 0
    jmp pw_loop
pw_sleep:
    cmp ebx, 1
    jle pw_spin
    dec ebx
    push ebx
    call dword ptr [{Sleep:#x}]
pw_spin:
    call dword ptr [{GetTickCount:#x}]
    sub eax, dword ptr [{V_TICK:#x}]
    js pw_spin
pw_done:
    popal
    ret 4
pw_old:
    jmp {WAIT_TO:#x}

p_frame:                                  ; instead of call (the frame hooks) at 0x42b8ce, before the Flip
    call {FRAME_TO:#x}
    pushfd
    pushal
    cmp dword ptr [{V_FREQ:#x}], 0
    jne pf_now
    push {V_FREQ:#x}
    call dword ptr [{QPF:#x}]
pf_now:
    push {V_NOW:#x}
    call dword ptr [{QPC:#x}]
    mov eax, dword ptr [{V_DUE:#x}]
    or eax, dword ptr [{V_DUE + 4:#x}]
    je pf_reset
pf_check:
    mov eax, dword ptr [{V_DUE:#x}]
    mov edx, dword ptr [{V_DUE + 4:#x}]
    sub eax, dword ptr [{V_NOW:#x}]
    sbb edx, dword ptr [{V_NOW + 4:#x}]   ; until the slot
    js pf_late
    jne pf_reset                          ; far ahead: start again
    test eax, eax
    jz pf_advance
    mov ecx, dword ptr [{V_FREQ:#x}]
    shr ecx, 2
    cmp eax, ecx
    ja pf_reset
    mov ecx, 1000
    mul ecx
    div dword ptr [{V_FREQ:#x}]
    cmp eax, 2
    jl pf_spin
    push 1
    call dword ptr [{Sleep:#x}]
pf_spin:
    push {V_NOW:#x}
    call dword ptr [{QPC:#x}]
    jmp pf_check
pf_late:                                  ; the slot has passed: show the frame now
    neg eax
    adc edx, 0
    neg edx
    jne pf_reset
    mov ecx, dword ptr [{V_FREQ:#x}]
    shr ecx, 2
    cmp eax, ecx
    jbe pf_advance                        ; less than 250 ms late: keep the grid
pf_reset:
    mov eax, dword ptr [{V_NOW:#x}]
    mov dword ptr [{V_DUE:#x}], eax
    mov eax, dword ptr [{V_NOW + 4:#x}]
    mov dword ptr [{V_DUE + 4:#x}], eax
pf_advance:                               ; the next slot: 1/60 s later, the remainder carried
    mov eax, dword ptr [{V_FREQ:#x}]
    xor edx, edx
    mov ecx, 60
    div ecx
    add dword ptr [{V_DUE:#x}], eax
    adc dword ptr [{V_DUE + 4:#x}], 0
    add dword ptr [{V_REM:#x}], edx
    cmp dword ptr [{V_REM:#x}], 60
    jb pf_done
    sub dword ptr [{V_REM:#x}], 60
    add dword ptr [{V_DUE:#x}], 1
    adc dword ptr [{V_DUE + 4:#x}], 0
pf_done:
    popal
    popfd
    ret

z_lock:                                   ; instead of the Lock of the z-buffer at 0x437ea4 (jmp)
    pushfd
    pushal
    mov eax, dword ptr [{ZBUFFER:#x}]
    mov ecx, dword ptr [{MODE:#x}]
    cmp eax, dword ptr [{Z_FOR:#x}]
    jne zl_new
    cmp ecx, dword ptr [{Z_MODE:#x}]
    je zl_have
zl_new:                                   ; a new z-buffer or screen size: a new surface
    mov dword ptr [{Z_FOR:#x}], eax
    mov dword ptr [{Z_MODE:#x}], ecx
    mov eax, dword ptr [{Z_SURF:#x}]
    test eax, eax
    je zl_desc
    mov dword ptr [{Z_SURF:#x}], 0
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 8]              ; Release
zl_desc:
    mov edi, {DESC:#x}
    xor eax, eax
    mov ecx, 31
    rep stosd
    mov dword ptr [{DESC:#x}], 0x7c
    push {DESC:#x}
    mov eax, dword ptr [{ZBUFFER:#x}]
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x58]           ; GetSurfaceDesc: size and depth format
    test eax, eax
    jne zl_orig
    cmp dword ptr [{DESC + 0x54:#x}], 16  ; 16-bit depth
    jne zl_orig
    mov eax, dword ptr [{DESC + 12:#x}]   ; width
    add eax, eax
    mov dword ptr [{DESC + 16:#x}], eax   ; pitch
    imul eax, dword ptr [{DESC + 8:#x}]   ; height
    cmp eax, {ZMAX:#x}
    ja zl_orig
    mov dword ptr [{Z_BYTES:#x}], eax
    mov dword ptr [{DESC + 4:#x}], 0x180f ; caps, height, width, pitch, lpSurface, pixel format
    mov dword ptr [{DESC + 0x24:#x}], {ZBUF:#x}
    mov dword ptr [{DESC + 0x68:#x}], 0x20800   ; DDSCAPS_ZBUFFER | DDSCAPS_SYSTEMMEMORY
    mov dword ptr [{DESC + 0x6c:#x}], 0
    push 0
    push {Z_SURF:#x}
    push {DESC:#x}
    mov eax, dword ptr [{DDRAW:#x}]
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x18]           ; CreateSurface
    test eax, eax
    je zl_have
    mov dword ptr [{Z_SURF:#x}], 0
zl_have:
    cmp dword ptr [{Z_SURF:#x}], 0
    je zl_orig
    mov edi, {ZBUF:#x}                    ; far depth everywhere
    mov ecx, dword ptr [{Z_BYTES:#x}]
    shr ecx, 2
    or eax, -1
    rep stosd
    mov edi, dword ptr [esp + 44]         ; the game's DDSURFACEDESC2 (the Lock's 3rd argument)
    mov esi, {DESC:#x}
    mov ecx, 31
    rep movsd dword ptr es:[edi], dword ptr [esi]
    mov byte ptr [{Z_USED:#x}], 1
    popal
    popfd
    add esp, 20                           ; the Lock's arguments
    xor eax, eax
    mov edx, dword ptr [esp + 0x18c]
    jmp 0x437eae
zl_orig:
    popal
    popfd
    call dword ptr [edx + 0x64]
    mov edx, dword ptr [esp + 0x18c]
    jmp 0x437eae

z_unlock:                                 ; instead of mov eax, [z-buffer] before its Unlock (jmp)
    cmp byte ptr [{Z_USED:#x}], 0
    je zu_orig
    mov byte ptr [{Z_USED:#x}], 0
    pushfd
    pushal
    push 0
    push 0x1000000                        ; DDBLT_WAIT
    push 0
    push dword ptr [{Z_SURF:#x}]
    push 0
    mov eax, dword ptr [{ZBUFFER:#x}]
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x14]           ; Blt into the z-buffer
    test eax, eax
    je zu_done
    mov dword ptr [{Z_FOR:#x}], 0         ; failed: a new surface next time
zu_done:
    popal
    popfd
    jmp 0x438be2                          ; the z-buffer was not locked: no Unlock
zu_orig:
    mov eax, dword ptr [{ZBUFFER:#x}]
    jmp 0x438bd7
labels:
    .long p_tick, p_wait, p_frame, z_lock, z_unlock
'''
code = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm('\n'.join(l.split(';')[0] for l in asm.splitlines()), CODE)[0])
p_tick, p_wait, p_frame, z_lock, z_unlock = struct.unpack('<5I', code[-20:])
code = code[:-20]
assert CODE + len(code) <= CODE_END, f'code too large: {len(code)} bytes'
data[off(CODE):off(CODE) + len(code)] = code
for at, op, to, length in ((TICK_AT, 0xe9, p_tick, 5), (WAIT_AT, 0xe8, p_wait, 5), (FRAME_AT, 0xe8, p_frame, 5),
                           (ZLOCK_AT, 0xe9, z_lock, 10), (ZUNLOCK_AT, 0xe9, z_unlock, 5)):
    data[off(at):off(at) + length] = bytes([op]) + struct.pack('<i', to - (at + 5)) + b'\x90' * (length - 5)
h = reloc.get_file_offset()
struct.pack_into('<I', data, h + 8, V_END - RELOC_VA)                     # VirtualSize
struct.pack_into('<I', data, pe.OPTIONAL_HEADER.get_file_offset() + 56, V_END - B)   # SizeOfImage
open(dst, 'wb').write(data)
print(f'code {len(code)} bytes at {CODE:#x}, data {V:#x}, depth buffer {ZBUF:#x}-{V_END:#x}')
