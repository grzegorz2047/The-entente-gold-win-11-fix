"""Scrolling The Entente: redraw only the terrain tiles that the scroll uncovers.

Applied after fps_counter.py (or after zoom.py for the improvements). usage: python terrain_strip.py IN.exe OUT.exe

When the camera moves by a tile, the terrain redraw 0x4379c0 rebuilds the list of all tiles on the
screen, draws every one of them (a base quad per tile in the loop at 0x438c58 and up to 9 blended
layers per tile in 0x439e80, each with its own SetTexture/DrawPrimitive: ~5000 calls in 1280x800,
~9500 in 1920x1200) and then copies the previous terrain picture, shifted by the camera step, over
everything except the uncovered strip (0x4395e1). Everything drawn inside the shifted area is
overwritten, so those tiles are skipped: a tile whose base quad lies completely inside the shifted
area is not drawn. In the stack frame of 0x4379c0, [esp+0x2c] is non-zero for such a shifted redraw,
the area is the source RECT at [esp+0x40] blitted to x = [esp+0x3c], y = [esp+0x38].
The skipped layer tiles still advance the layer-vertex counter (edi in 0x439e80) as the game would.
The tile list addresses are read from the instructions that use them, so the tile list moved by
zoom.py is followed. Code lives in the padding after .rsrc's virtual size, after text_overlay.py.
"""
import struct, sys
import pefile
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

src, dst = sys.argv[1:]
data = bytearray(open(src, 'rb').read())
pe = pefile.PE(data=bytes(data))
B = pe.OPTIONAL_HEADER.ImageBase
off = lambda va: pe.get_offset_from_rva(va - B)
u32 = lambda va: struct.unpack('<I', data[off(va):off(va) + 4])[0]

def expect(va, hexbytes):
    got = bytes(data[off(va):off(va) + len(bytes.fromhex(hexbytes))])
    if got != bytes.fromhex(hexbytes):
        sys.exit(f'unexpected bytes at {va:#x}: {got.hex()}')

expect(0x438c63, '8d0cb6a1f0e15a00')              # base loop: lea ecx, [esi+esi*4]; mov eax, [device]
expect(0x438cae, 'a1')                            # base loop: next tile (mov eax, [count])
expect(0x439eb1, '8d0c808d044803c0')              # layers: lea ecx, [eax+eax*4]; lea eax, [eax+ecx*2]; add eax, eax
expect(0x439f2c, '8b442414')                      # layers: next tile (mov eax, [esp+0x14])
expect(0x4395d9, '8a44242c84c0')                  # mov al, [esp+0x2c]; test al, al (shifted copy follows)
NQ = u32(0x438c9a + 2)                            # base quad vertices, 0x80 per tile (add esi, NQ)
REC9 = u32(0x439eb9 + 2)                          # byte [22 i + REC9] & 0x80: tile has layers
RECL = u32(0x439ec4 + 2)                          # 9 words at 22 i + RECL: layer textures

rsrc = next(s for s in pe.sections if s.Name.startswith(b'.rsrc'))
lo, hi = B + rsrc.VirtualAddress, B + rsrc.VirtualAddress + rsrc.SizeOfRawData
used = max(va for va in range(lo, hi) if data[off(va)])
CODE = (used + 17) & ~15                           # past the NUL ending text_overlay.py's strings

asm = f'''
tile_in_shift:                          ; eax = tile, edx = stack frame of 0x4379c0; eax = 1: skip it
    cmp byte ptr [edx + 0x2c], 0
    je tis_no
    push ebx
    push esi
    push edi
    push ebp
    movsx ebx, word ptr [edx + 0x3c]    ; left
    movsx ecx, word ptr [edx + 0x38]    ; top
    mov esi, dword ptr [edx + 0x48]
    sub esi, dword ptr [edx + 0x40]
    add esi, ebx                        ; right
    mov edi, dword ptr [edx + 0x4c]
    sub edi, dword ptr [edx + 0x44]
    add edi, ecx                        ; bottom
    shl eax, 7
    add eax, {NQ:#x}
    mov ebp, 4
tis_vertex:
    cvttss2si edx, dword ptr [eax]
    cmp edx, ebx
    jl tis_out
    cmp edx, esi
    jg tis_out
    cvttss2si edx, dword ptr [eax + 4]
    cmp edx, ecx
    jl tis_out
    cmp edx, edi
    jg tis_out
    add eax, 0x20
    dec ebp
    jnz tis_vertex
    mov eax, 1
    jmp tis_ret
tis_out:
    xor eax, eax
tis_ret:
    pop ebp
    pop edi
    pop esi
    pop ebx
    ret
tis_no:
    xor eax, eax
    ret

base_tile:                              ; at 0x438c63, esi = tile
    lea edx, [esp + 4]
    mov eax, esi
    call tile_in_shift
    test eax, eax
    jne bt_skip
    lea ecx, [esi + esi*4]
    mov eax, dword ptr [0x5ae1f0]
    ret
bt_skip:
    add esp, 4
    jmp 0x438cae

layer_tile:                             ; at 0x439eb1, eax = tile, edi = layer-vertex counter
    push eax
    lea edx, [esp + 0x24]               ; ret, eax, 0x439e80's 8 bytes of locals and 4 pushes, its ret
    call tile_in_shift
    test eax, eax
    pop eax
    lea ecx, [eax + eax*4]
    lea eax, [eax + ecx*2]
    lea eax, [eax + eax]
    jne lt_skip
    ret
lt_skip:
    test byte ptr [eax + {REC9:#x}], 0x80
    je lt_next
    lea ecx, [eax + {RECL:#x}]
    mov edx, 9
lt_count:
    cmp word ptr [ecx], 0
    je lt_empty
    add edi, 8
lt_empty:
    add ecx, 2
    dec edx
    jnz lt_count
lt_next:
    add esp, 4
    jmp 0x439f2c
'''

ks = Ks(KS_ARCH_X86, KS_MODE_32)
src_asm = '\n'.join(l.split(';')[0] for l in asm.splitlines())
code = bytes(ks.asm(src_asm, CODE)[0])
assert CODE + len(code) <= hi, f'code too large: {len(code)} bytes'
assert not any(data[off(CODE):off(CODE) + len(code)])
data[off(CODE):off(CODE) + len(code)] = code

def label(name):
    head = src_asm.split('\n' + name + ':')[0]
    return CODE + len(bytes(ks.asm(head, CODE)[0])) if head.strip() else CODE

call = lambda at, to: b'\xe8' + struct.pack('<i', to - (at + 5))
data[off(0x438c63):off(0x438c63) + 8] = call(0x438c63, label('base_tile')) + b'\x90' * 3
data[off(0x439eb1):off(0x439eb1) + 8] = call(0x439eb1, label('layer_tile')) + b'\x90' * 3

hdr = rsrc.get_file_offset()                      # .rsrc: cover the code, executable
struct.pack_into('<I', data, hdr + 8, rsrc.SizeOfRawData)
struct.pack_into('<I', data, hdr + 36, rsrc.Characteristics | 0x20000020)
open(dst, 'wb').write(data)
print(f'code {len(code)} bytes at {CODE:#x}; base quads {NQ:#x}, records {REC9 - 9:#x}')
