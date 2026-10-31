"""The Entente: compute the fog-of-war visibility map with the CPU instead of round-tripping it through dgVoodoo.

Applied after pacer.py, in both variants. usage: python visibility.py IN.exe OUT.exe

Every 30 frames, and about 4 times a second while the camera scrolls, the fog update 0x45e940
stamps the sight circles of the player's units onto a small system-memory surface ([0x982c6c],
(tiles across + 10) x (tiles down + 20) pixels): a colour fill (0x420d70) and a few hundred clipped
BltFasts with the source colour key (0x420860) from the circle sprites ([0x982c5c]). Then it locks
the surface read-only and reads it back pixel by pixel (0x45f2c9-0x45f351). dgVoodoo performs those
blits on the GPU, so the first read waits for the GPU and copies the surface back: 12 ms each time
(5-14 ms while scrolling), which made a 27-28 ms frame about once a second even with the camera
standing still.
For that surface only, the fill and the blits are now done by the CPU into a buffer in the image,
and the read-only Lock returns that buffer (its Unlock is skipped). Each circle sprite is read
(Lock, read-only) once and kept with its colour key; the sprites are read again after the
visibility surface or the back buffer changes (a mode switch). The clipping is the one of 0x420860.
If a sprite cannot be read, its circle is left out of that update and the game's own blits are
used from the next update on.
Code in the old relocation table after pacer.py's, data in a zero-filled extension of .reloc.
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

BLIT, FILL = 0x420860, 0x420d70
expect(BLIT, '8b44240481ec94000000')       # mov eax, [esp+4]; sub esp, 0x94
expect(FILL, '8b54240483ec64')             # mov edx, [esp+4]; sub esp, 0x64
LOCK_AT, UNLOCK_AT = 0x45f2c5, 0x45f351
expect(LOCK_AT, '896c2428ff5164')          # mov [esp+0x28], ebp; call [ecx+0x64] (Lock, read-only)
expect(UNLOCK_AT, 'a16c2c9800')            # mov eax, [visibility surface]; its Unlock follows
VIS, VIS_W, VIS_H, BACK = 0x982c6c, 0x982644, 0x982642, 0x5ae258
RELOC_VA = 0x9cb000
CODE, CODE_END = RELOC_VA + 0xb000, RELOC_VA + 0x12bc0 - 0xbc0   # up to mode_redraw.py's building layer
reloc = next(s for s in pe.sections if s.Name.startswith(b'.reloc'))
assert B + reloc.VirtualAddress == RELOC_VA and pe.sections[-1] is reloc
V = (RELOC_VA + reloc.Misc_VirtualSize + 0xfff) & ~0xfff
V_ON, V_OFF, V_FOR, V_BACK, V_W, V_H, V_N, V_USED = (V + 4 * i for i in range(8))
V_L, V_T, V_R, V_BOT, V_X, V_Y, V_CK = (V + 0x20 + 4 * i for i in range(7))
DESC = V + 0x80                                   # DDSURFACEDESC2 (0x7c), then the colour key (8 bytes)
CKEY = V + 0x100
SPR, NSPR = V + 0x200, 64                         # sprites: surface, width, height, pixels, key, has key
BUF, BUFMAX = V + 0x1000, 0x10000                 # the visibility map, 16-bit
STORE, STOREMAX = BUF + BUFMAX, 0x100000          # the sprites' pixels
V_END = STORE + STOREMAX

asm = f'''
v_fill:                                   ; 0x420d70(surface, colour): a colour fill
    mov edx, dword ptr [esp + 4]
    test edx, edx
    je vf_orig
    cmp edx, dword ptr [{VIS:#x}]
    jne vf_orig
    mov byte ptr [{V_ON:#x}], 0
    cmp byte ptr [{V_OFF:#x}], 0
    jne vf_orig
    pushal
    mov eax, dword ptr [{BACK:#x}]
    cmp edx, dword ptr [{V_FOR:#x}]       ; a new visibility surface or back buffer: read the sprites again
    jne vf_new
    cmp eax, dword ptr [{V_BACK:#x}]
    je vf_size
vf_new:
    mov dword ptr [{V_FOR:#x}], edx
    mov dword ptr [{V_BACK:#x}], eax
    mov dword ptr [{V_N:#x}], 0
    mov dword ptr [{V_USED:#x}], 0
vf_size:
    movzx eax, word ptr [{VIS_W:#x}]
    movzx ecx, word ptr [{VIS_H:#x}]
    mov dword ptr [{V_W:#x}], eax
    mov dword ptr [{V_H:#x}], ecx
    imul ecx, eax
    cmp ecx, {BUFMAX // 2}
    ja vf_big
    mov eax, dword ptr [esp + 40]         ; the colour (16-bit)
    mov edi, {BUF:#x}
    rep stosw
    mov byte ptr [{V_ON:#x}], 1
    popal
    ret
vf_big:
    popal
vf_orig:
    sub esp, 0x64
    jmp {FILL + 7:#x}

v_blit:                                   ; 0x420860(dest, src, w, h, src rect, x, y, colour key): clipped BltFast
    mov eax, dword ptr [esp + 4]
    test eax, eax
    je vb_orig
    cmp eax, dword ptr [{VIS:#x}]
    jne vb_orig
    cmp byte ptr [{V_ON:#x}], 0
    je vb_orig
    cmp dword ptr [esp + 8], 0
    je vb_orig
    pushal                                ; arguments from [esp + 36]
    mov esi, dword ptr [esp + 40]
    call v_sprite
    test ebx, ebx
    je vb_done
    mov eax, dword ptr [esp + 52]         ; source rect, or the whole sprite
    test eax, eax
    je vb_whole
    mov ecx, dword ptr [eax]
    mov edx, dword ptr [eax + 4]
    mov esi, dword ptr [eax + 8]
    mov edi, dword ptr [eax + 12]
    jmp vb_rect
vb_whole:
    xor ecx, ecx
    xor edx, edx
    mov esi, dword ptr [ebx + 4]
    mov edi, dword ptr [ebx + 8]
vb_rect:
    mov dword ptr [{V_L:#x}], ecx
    mov dword ptr [{V_T:#x}], edx
    mov dword ptr [{V_R:#x}], esi
    mov dword ptr [{V_BOT:#x}], edi
    mov eax, dword ptr [esp + 56]         ; x
    mov ecx, dword ptr [esp + 44]
    and ecx, 0xffff                       ; w
    cmp eax, ecx
    jge vb_done
    mov eax, dword ptr [esp + 60]         ; y
    mov ecx, dword ptr [esp + 48]
    and ecx, 0xffff                       ; h
    cmp eax, ecx
    jge vb_done
    mov eax, dword ptr [{V_R:#x}]         ; as 0x420860 clips
    sub eax, dword ptr [{V_L:#x}]
    and eax, 0xffff
    add eax, dword ptr [esp + 56]
    test eax, eax
    jle vb_done
    mov ecx, dword ptr [esp + 44]
    and ecx, 0xffff
    cmp eax, ecx
    jl vb_xin
    sub ecx, dword ptr [esp + 56]
    add ecx, dword ptr [{V_L:#x}]
    mov dword ptr [{V_R:#x}], ecx
vb_xin:
    mov eax, dword ptr [{V_BOT:#x}]
    sub eax, dword ptr [{V_T:#x}]
    and eax, 0xffff
    add eax, dword ptr [esp + 60]
    test eax, eax
    jle vb_done
    mov ecx, dword ptr [esp + 48]
    and ecx, 0xffff
    cmp eax, ecx
    jl vb_yin
    sub ecx, dword ptr [esp + 60]
    add ecx, dword ptr [{V_T:#x}]
    mov dword ptr [{V_BOT:#x}], ecx
vb_yin:
    mov eax, dword ptr [esp + 56]
    mov dword ptr [{V_X:#x}], eax
    test eax, eax
    jge vb_x0
    sub dword ptr [{V_L:#x}], eax
    mov dword ptr [{V_X:#x}], 0
vb_x0:
    mov eax, dword ptr [esp + 60]
    mov dword ptr [{V_Y:#x}], eax
    test eax, eax
    jge vb_y0
    sub dword ptr [{V_T:#x}], eax
    mov dword ptr [{V_Y:#x}], 0
vb_y0:
    mov dword ptr [{V_CK:#x}], 0x10000    ; no key: a value no pixel has
    cmp byte ptr [esp + 64], 0
    je vb_nokey
    cmp dword ptr [ebx + 20], 0
    je vb_nokey
    mov eax, dword ptr [ebx + 16]
    mov dword ptr [{V_CK:#x}], eax
vb_nokey:
    mov ebp, dword ptr [{V_BOT:#x}]
    sub ebp, dword ptr [{V_T:#x}]         ; rows
    jle vb_done
    mov eax, dword ptr [{V_T:#x}]         ; source: pixels + (top * width + left) * 2
    imul eax, dword ptr [ebx + 4]
    add eax, dword ptr [{V_L:#x}]
    add eax, eax
    add eax, dword ptr [ebx + 12]
    mov esi, eax
    mov eax, dword ptr [{V_Y:#x}]         ; destination: buffer + (y * W + x) * 2
    imul eax, dword ptr [{V_W:#x}]
    add eax, dword ptr [{V_X:#x}]
    add eax, eax
    add eax, {BUF:#x}
    mov edi, eax
vb_row:
    mov ecx, dword ptr [{V_R:#x}]
    sub ecx, dword ptr [{V_L:#x}]         ; columns
    jle vb_done
    xor edx, edx
vb_px:
    movzx eax, word ptr [esi + edx*2]
    cmp eax, dword ptr [{V_CK:#x}]
    je vb_skip
    mov word ptr [edi + edx*2], ax
vb_skip:
    inc edx
    cmp edx, ecx
    jl vb_px
    mov eax, dword ptr [ebx + 4]
    lea esi, [esi + eax*2]
    mov eax, dword ptr [{V_W:#x}]
    lea edi, [edi + eax*2]
    dec ebp
    jnz vb_row
vb_done:
    popal
    mov al, 1
    ret
vb_orig:
    mov eax, dword ptr [esp + 4]
    sub esp, 0x94
    jmp {BLIT + 10:#x}

v_sprite:                                 ; esi = source surface -> ebx = its entry, or 0
    mov ebx, {SPR:#x}
    mov ecx, dword ptr [{V_N:#x}]
vs_find:
    test ecx, ecx
    je vs_new
    cmp dword ptr [ebx], esi
    je vs_ret
    add ebx, 32
    dec ecx
    jmp vs_find
vs_new:
    cmp dword ptr [{V_N:#x}], {NSPR}
    jae vs_fail
    mov edi, {DESC:#x}
    xor eax, eax
    mov ecx, 31
    rep stosd
    mov dword ptr [{DESC:#x}], 0x7c
    push 0
    push 0x11                             ; DDLOCK_READONLY | DDLOCK_WAIT
    push {DESC:#x}
    push 0
    push esi
    mov eax, dword ptr [esi]
    call dword ptr [eax + 0x64]           ; Lock
    test eax, eax
    jne vs_fail
    cmp dword ptr [{DESC + 0x54:#x}], 16  ; 16-bit pixels
    jne vs_unlock_fail
    mov eax, dword ptr [{DESC + 12:#x}]
    imul eax, dword ptr [{DESC + 8:#x}]
    add eax, eax
    mov edx, dword ptr [{V_USED:#x}]
    add eax, edx
    cmp eax, {STOREMAX:#x}
    ja vs_unlock_fail
    mov dword ptr [{V_USED:#x}], eax
    mov dword ptr [ebx], esi              ; the new entry (ebx = SPR + 32 * V_N)
    mov eax, dword ptr [{DESC + 12:#x}]
    mov dword ptr [ebx + 4], eax
    mov eax, dword ptr [{DESC + 8:#x}]
    mov dword ptr [ebx + 8], eax
    add edx, {STORE:#x}
    mov dword ptr [ebx + 12], edx
    mov dword ptr [ebx + 20], 0
    push esi
    mov edi, edx                          ; copy the rows
    mov esi, dword ptr [{DESC + 0x24:#x}]
    mov edx, dword ptr [ebx + 8]
vs_row:
    test edx, edx
    je vs_copied
    push esi
    mov ecx, dword ptr [ebx + 4]
    rep movsw word ptr es:[edi], word ptr [esi]
    pop esi
    add esi, dword ptr [{DESC + 16:#x}]
    dec edx
    jmp vs_row
vs_copied:
    pop esi
    push 0
    push esi
    mov eax, dword ptr [esi]
    call dword ptr [eax + 0x80]           ; Unlock
    push {CKEY:#x}
    push 8                                ; DDCKEY_SRCBLT
    push esi
    mov eax, dword ptr [esi]
    call dword ptr [eax + 0x40]           ; GetColorKey
    test eax, eax
    jne vs_added
    movzx eax, word ptr [{CKEY:#x}]
    mov dword ptr [ebx + 16], eax
    mov dword ptr [ebx + 20], 1
vs_added:
    inc dword ptr [{V_N:#x}]
vs_ret:
    ret
vs_unlock_fail:
    push 0
    push esi
    mov eax, dword ptr [esi]
    call dword ptr [eax + 0x80]
vs_fail:
    mov byte ptr [{V_OFF:#x}], 1          ; the game's own blits from the next update on
    xor ebx, ebx
    ret

v_lock:                                   ; instead of mov [esp+0x28], ebp; call [ecx+0x64] at 0x45f2c5
    mov dword ptr [esp + 0x28], ebp
    cmp eax, dword ptr [{VIS:#x}]
    jne vl_orig
    cmp byte ptr [{V_ON:#x}], 0
    je vl_orig
    pushal
    mov edi, dword ptr [esp + 40]         ; the DDSURFACEDESC2 of the Lock
    mov eax, dword ptr [{V_H:#x}]
    mov dword ptr [edi + 8], eax
    mov eax, dword ptr [{V_W:#x}]
    mov dword ptr [edi + 12], eax
    add eax, eax
    mov dword ptr [edi + 16], eax         ; pitch
    mov dword ptr [edi + 0x24], {BUF:#x}
    popal
    add esp, 20                           ; the Lock's arguments
    xor eax, eax
    jmp {LOCK_AT + 7:#x}
vl_orig:
    call dword ptr [ecx + 0x64]
    jmp {LOCK_AT + 7:#x}

v_unlock:                                 ; instead of mov eax, [visibility surface] before its Unlock
    cmp byte ptr [{V_ON:#x}], 0
    je vu_orig
    mov byte ptr [{V_ON:#x}], 0
    jmp {UNLOCK_AT + 16:#x}               ; past the Unlock
vu_orig:
    mov eax, dword ptr [{VIS:#x}]
    jmp {UNLOCK_AT + 5:#x}
labels:
    .long v_fill, v_blit, v_lock, v_unlock
'''
expect(UNLOCK_AT + 5, '6a00508b08ff9180000000')   # push 0; push eax; mov ecx, [eax]; call [ecx+0x80]
code = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm('\n'.join(l.split(';')[0] for l in asm.splitlines()), CODE)[0])
v_fill, v_blit, v_lock, v_unlock = struct.unpack('<4I', code[-16:])
code = code[:-16]
assert CODE + len(code) <= CODE_END, f'code too large: {len(code)} bytes'
data[off(CODE):off(CODE) + len(code)] = code
for at, to, length in ((FILL, v_fill, 7), (BLIT, v_blit, 10), (LOCK_AT, v_lock, 7), (UNLOCK_AT, v_unlock, 5)):
    data[off(at):off(at) + length] = b'\xe9' + struct.pack('<i', to - (at + 5)) + b'\x90' * (length - 5)
h = reloc.get_file_offset()
struct.pack_into('<I', data, h + 8, V_END - RELOC_VA)                     # VirtualSize
struct.pack_into('<I', data, pe.OPTIONAL_HEADER.get_file_offset() + 56, V_END - B)   # SizeOfImage
open(dst, 'wb').write(data)
print(f'code {len(code)} bytes at {CODE:#x}, data {V:#x}-{V_END:#x}')
