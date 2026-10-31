"""The Entente: redraw the map after a screen mode switch (black buildings after saving or loading).

Applied after fps_counter.py, in both variants. usage: python mode_redraw.py IN.exe OUT.exe

The save and load dialogs run in the menu mode (1024x768). With the original settings the mission
ran in that mode too; with a wide mission mode the game switches the screen mode there and back.
The terrain with the buildings is kept in a cache surface that is redrawn only when the camera
moves, and the redraw made while switching back draws the buildings black: they stayed black until
the camera moved.
The render call of the main loop (0x46e1df) now notices a new back buffer (a mode switch creates
one) and redraws the map 5, 60 and 180 map frames later the way the game does for a camera jump
(scroll flag 10, 0x431c70(0, 0)): right after the switch the buildings still come out black.
That did not cover every case: in about one save in four the buildings stayed black, or showed
pieces of an old picture, even after those redraws. The redraw copies the building pixels with the
CPU into the locked back buffer (0x42ed90 and others, between the Lock at 0x437e76 and the Unlock at
0x438bec) and then draws the terrain around them with Direct3D. After such a mode switch, what was
written into the locked back buffer did not reach the picture, while the depth written into the
locked z-buffer did (the terrain left the building shapes out). The buildings are now written into
a system-memory surface of the screen size instead, which is put onto the back buffer with BltFast
after the Unlock, before the terrain is drawn: the same way the minimap reaches the screen.
The game is loaded at its preferred base (no ASLR flag), so its base relocations are never applied:
the code lives at the end of the relocation table (modern_hud.py uses its start, prefetch.py the
part before the last 0xbc0 bytes and the 0x800 bytes before the redraw code), and the table is
dropped.
"""
import struct, sys
import pefile
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

src, dst = sys.argv[1:]
data = bytearray(open(src, 'rb').read())
pe = pefile.PE(data=bytes(data))
B = pe.OPTIONAL_HEADER.ImageBase
off = lambda va: pe.get_offset_from_rva(va - B)
call = lambda at, to: b'\xe8' + struct.pack('<i', to - (at + 5))

def expect(va, hexbytes):
    got = bytes(data[off(va):off(va) + len(bytes.fromhex(hexbytes))])
    if got != bytes.fromhex(hexbytes):
        sys.exit(f'unexpected bytes at {va:#x}: {got.hex()}')

RENDER, SCROLL_TO = 0x404633, 0x402b35            # thunks of 0x42b1d0 (frame) and 0x431c70 (camera move)
expect(0x46e1df, call(0x46e1df, RENDER).hex())     # main loop: render the frame
expect(0x46e627, '6a006a00c605c4e38b000ae8' + struct.pack('<i', SCROLL_TO - 0x46e637).hex())   # a camera jump
RELOC_VA, RELOC_SIZE = 0x9cb000, 0x12bc0          # the relocation table of the Steam exe
assert pe.OPTIONAL_HEADER.DllCharacteristics & 0x40 == 0, 'relocations needed'
CODE = RELOC_VA + RELOC_SIZE - 0x100              # modern_hud.py: from RELOC_VA, up to RELOC_VA + 0x1600
G_BACK, G_WAIT = CODE + 0xe0, CODE + 0xe4
FRAMES = (5, 60, 180)                             # map frames after the switch with a redraw

asm = f'''
redraw_frame:                             ; instead of call 0x42b1d0 (render) at 0x46e1df
    mov eax, dword ptr [0x5ae258]         ; back buffer
    cmp eax, dword ptr [{G_BACK:#x}]
    je rf_wait
    mov dword ptr [{G_BACK:#x}], eax      ; a new one: the screen mode was switched
    mov dword ptr [{G_WAIT:#x}], 1
rf_wait:
    mov eax, dword ptr [{G_WAIT:#x}]
    test eax, eax
    je rf_render
    cmp dword ptr [0x9c2b04], 0           ; count only frames of the map view (0x431c70 does nothing else)
    jne rf_render
    inc eax
    cmp eax, {FRAMES[-1]}
    jbe rf_count
    xor eax, eax                          ; done
rf_count:
    mov dword ptr [{G_WAIT:#x}], eax
{"".join(f"""    cmp eax, {n}
    je rf_redraw
""" for n in FRAMES)}    jmp rf_render
rf_redraw:
    push 0                                ; as the game jumps the camera (0x46e627)
    push 0
    mov byte ptr [0x8be3c4], 0xa
    call {SCROLL_TO:#x}
    add esp, 8
rf_render:
    jmp {RENDER:#x}
'''
code = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm('\n'.join(l.split(';')[0] for l in asm.splitlines()), CODE)[0])
assert CODE + len(code) <= G_BACK
data[off(CODE):off(CODE) + 0x100] = code + bytes(0x100 - len(code))
data[off(0x46e1df):off(0x46e1df) + 5] = call(0x46e1df, CODE)

BACK, DEVICE = 0x5ae258, 0x5ae1f0
LOCK_AT, UNLOCK_AT, SCENE_AT = 0x437e53, 0x438be2, 0x438bf4
expect(LOCK_AT, 'a158e25a00')                      # mov eax, [back]: Lock(back, NULL, [esp+0x1e4], WAIT) follows
expect(UNLOCK_AT, 'a158e25a006a0050')               # mov eax, [back]; push 0; push eax: its Unlock
expect(SCENE_AT, 'a1f0e15a00')                     # mov eax, [device]: BeginScene follows
LAYER = RELOC_VA + RELOC_SIZE - 0xbc0              # up to prefetch.py's code
G_SURF, G_FOR, G_USED = LAYER + 0x2b0, LAYER + 0x2b4, LAYER + 0x2b8
CREATE = 0x401668                                 # (w, h, colour key, system memory): a surface, as for the minimap
asm = f'''
bl_lock:                                  ; instead of mov eax, [back] before the Lock: the surface to write into
    mov eax, dword ptr [{BACK:#x}]
    cmp eax, dword ptr [{G_FOR:#x}]
    je bl_have
    pushal                                ; a new back buffer (start, mode switch): a new surface of its size
    mov dword ptr [{G_FOR:#x}], eax
    mov eax, dword ptr [{G_SURF:#x}]
    test eax, eax
    je bl_new
    mov dword ptr [{G_SURF:#x}], 0
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 8]              ; Release
bl_new:
    push 1
    push 0
    movzx eax, word ptr [0x5ae24c]        ; height
    push eax
    movzx eax, word ptr [0x5ae24e]        ; width
    push eax
    call {CREATE:#x}
    add esp, 16
    mov dword ptr [{G_SURF:#x}], eax
    popal
bl_have:
    mov eax, dword ptr [{G_SURF:#x}]
    test eax, eax
    jne bl_used
    mov eax, dword ptr [{BACK:#x}]        ; no surface: the back buffer, as before
    ret
bl_used:
    mov byte ptr [{G_USED:#x}], 1
    ret

bl_unlock:                                ; instead of mov eax, [back] before the Unlock
    mov eax, dword ptr [{BACK:#x}]
    cmp byte ptr [{G_USED:#x}], 0
    je bu_ret
    mov eax, dword ptr [{G_SURF:#x}]
bu_ret:
    ret

bl_show:                                  ; instead of mov eax, [device] before BeginScene: the buildings onto
    cmp byte ptr [{G_USED:#x}], 0         ; the back buffer, the terrain is drawn around them
    je bs_done
    mov byte ptr [{G_USED:#x}], 0
    pushal
    push 0x10                             ; DDBLTFAST_WAIT
    push 0                                ; the whole surface
    push dword ptr [{G_SURF:#x}]
    push 0
    push 0
    mov eax, dword ptr [{BACK:#x}]
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x1c]           ; BltFast
    popal
bs_done:
    mov eax, dword ptr [{DEVICE:#x}]
    ret
labels:
    .long bl_lock, bl_unlock, bl_show
'''
code = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm('\n'.join(l.split(';')[0] for l in asm.splitlines()), LAYER)[0])
entries = struct.unpack('<3I', code[-12:])
code = code[:-12]
assert LAYER + len(code) <= G_SURF
data[off(LAYER):off(LAYER) + 0x2c0] = code + bytes(0x2c0 - len(code))
for at, to in zip((LOCK_AT, UNLOCK_AT, SCENE_AT), entries):
    data[off(at):off(at) + 5] = call(at, to)
dd =pe.OPTIONAL_HEADER.get_file_offset() + 96 + 8 * 5   # the base relocation directory: none
struct.pack_into('<2I', data, dd, 0, 0)
open(dst, 'wb').write(data)
print(f'code at {CODE:#x}, building layer {len(code)} bytes at {LAYER:#x}')
