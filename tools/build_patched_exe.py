"""Builds the fixed Antanta.exe (The Entente Gold, Steam build) from the original.

- Replaces the four selectable screen modes (1024x768, 1152x864, 1280x960, 1280x1024) with
  custom ones and makes the visible-tile-count functions compute their values from the
  screen size instead of a hard-coded per-width switch. For the original modes the formulas
  reproduce the original constants exactly.
- Scales the top-bar HUD with the real screen width.
- Replaces the z-buffer self-copy used while scrolling (units vanished) with a depth clear.
- Loading a mission keeps the menu's screen size until the mode switch (1440x900 crashed on load).

usage: python build_patched_exe.py ORIGINAL.exe OUTPUT.exe WxH WxH WxH WxH
release build: ... 1024x768 1152x720 1280x800 1440x900   (requires: pip install pefile)
"""
import struct, sys, hashlib
import pefile

src, dst, *modes = sys.argv[1:]
modes = [tuple(int(v) for v in m.lower().split('x')) for m in modes]
assert len(modes) == 4

data = bytearray(open(src, 'rb').read())
pe = pefile.PE(data=bytes(data))
BASE = pe.OPTIONAL_HEADER.ImageBase
text = next(s for s in pe.sections if s.Name.startswith(b'.text'))

def off(va):
    return pe.get_offset_from_rva(va - BASE)

def read(va, n):
    o = off(va); return bytes(data[o:o + n])

def write(va, b):
    o = off(va); data[o:o + len(b)] = b

def expect(va, hexbytes):
    got = read(va, len(bytes.fromhex(hexbytes)))
    if got != bytes.fromhex(hexbytes):
        sys.exit(f'unexpected bytes at {va:#x}: {got.hex()} (wrong game version?)')

W_ADDR, H_ADDR = 0x5ae24e, 0x5ae24c
d32 = lambda v: struct.pack('<I', v & 0xffffffff)
w16 = lambda v: struct.pack('<H', v)

# Sanity checks against the known original code.
expect(0x4204ec, '29024200380242004702420052024200')   # setter A jump table
expect(0x42199c, 'd9184200e8184200f718420002194200')   # setter B jump table
expect(0x4f3bd4, 'f13a4f00053b4f00193b4f00243b4f00')   # setter C jump table
expect(0x431be0, '33c066a14ee25a003d00040000')          # tile-count fn 1
expect(0x4668dc, '3d00040000')                          # tile-count fn 2 (cmp eax, 0x400)

cave_start = BASE + text.VirtualAddress + text.Misc_VirtualSize
cave_end = BASE + text.VirtualAddress + text.SizeOfRawData
assert not any(read(cave_start, cave_end - cave_start)), 'cave not empty (already patched?)'
cave = bytearray()

def here():
    return cave_start + len(cave)

def jmp_from(at, target):
    return b'\xe9' + d32(target - (at + 5))

def emit(b):
    cave.extend(b)

# Setters A and B: "mov ax, W; mov word [H], h; jmp cont" (cont stores ax as width).
def stub_ax(w, h, cont):
    start = here()
    emit(b'\x66\xb8' + w16(w))
    emit(b'\x66\xc7\x05' + d32(H_ADDR) + w16(h))
    emit(jmp_from(here(), cont))
    return start

# Setter C: writes both globals directly.
def stub_direct(w, h, cont):
    start = here()
    emit(b'\x66\xc7\x05' + d32(W_ADDR) + w16(w))
    emit(b'\x66\xc7\x05' + d32(H_ADDR) + w16(h))
    emit(jmp_from(here(), cont))
    return start

for table, cont, mk in ((0x4204ec, 0x42025f, stub_ax), (0x42199c, 0x42190f, stub_ax)):
    entries = [mk(w, h, cont) for (w, h) in modes]
    write(table, b''.join(d32(e) for e in entries))

# Setter C runs when a mission is loaded: it set the mission's screen size, then the map is loaded and
# drawn (0x427650), and only then the mode switch (0x42bb20 at 0x4f3b81) sets the size again and
# recreates the surfaces. In between the map was drawn with the mission's size into the menu-sized
# (1024x768) back buffer and z-buffer: a crash at 0x42d5b5 / 0x42efeb in modes wider than 1280.
# Leave the size to the mode switch (it also recomputes the tile counts).
write(0x4f3bd4, b''.join(d32(0x4f3b36) for _ in modes))

# Tile-count fn 1 (0x431be0): [0x8be38e] = ceil(W/96), [0x8be38c] = floor(H/24) + 2.
f1 = here()
emit(b'\x51\x52')                                   # push ecx; push edx
emit(b'\x0f\xb7\x05' + d32(W_ADDR))                 # movzx eax, word [W]
emit(b'\x83\xc0\x5f')                               # add eax, 95
emit(b'\x31\xd2\xb9' + d32(96) + b'\xf7\xf1')       # xor edx,edx; mov ecx,96; div ecx
emit(b'\x66\xa3' + d32(0x8be38e))                   # mov [0x8be38e], ax
emit(b'\x0f\xb7\x05' + d32(H_ADDR))                 # movzx eax, word [H]
emit(b'\x31\xd2\xb9' + d32(24) + b'\xf7\xf1')       # xor edx,edx; mov ecx,24; div ecx
emit(b'\x83\xc0\x02')                               # add eax, 2
emit(b'\x66\xa3' + d32(0x8be38c))                   # mov [0x8be38c], ax
emit(b'\x5a\x59\xc3')                               # pop edx; pop ecx; ret
write(0x431be0, jmp_from(0x431be0, f1))

# Tile-count fn 2 (entered at 0x4668dc with eax = W, esi = this):
# [esi+0x14] = ceil(W/48), [esi+0x15] = ceil(H/24), then continue at 0x46691e.
f2 = here()
emit(b'\x52')                                       # push edx
emit(b'\x83\xc0\x2f')                               # add eax, 47
emit(b'\x31\xd2\xb9' + d32(48) + b'\xf7\xf1')       # xor edx,edx; mov ecx,48; div ecx
emit(b'\x88\x46\x14')                               # mov [esi+0x14], al
emit(b'\x0f\xb7\x05' + d32(H_ADDR))                 # movzx eax, word [H]
emit(b'\x83\xc0\x17')                               # add eax, 23
emit(b'\x31\xd2\xb9' + d32(24) + b'\xf7\xf1')       # xor edx,edx; mov ecx,24; div ecx
emit(b'\x88\x46\x15')                               # mov [esi+0x15], al
emit(b'\x5a')                                       # pop edx
emit(jmp_from(here(), 0x46691e))
write(0x4668dc, jmp_from(0x4668dc, f2))

# Scrolling shifts the z-buffer with a BltFast from the z-buffer onto itself (0x437ce7). Modern
# DirectDraw wrappers do not perform that overlapping depth copy, so the stale depth hides the units
# while the map scrolls. Replace the shift with a full DDBLT_DEPTHFILL to far depth; the game then
# redraws the exposed strips as before. Entered with eax = z-buffer surface.
expect(0x437ce7, '8b306a100fbfc90fbfd25750515250ff561c')
zfill = here()
emit(bytes.fromhex(
    '57'                    # push edi
    '83ec64'                # sub esp, 100            ; DDBLTFX on the stack
    '89e7'                  # mov edi, esp
    '50'                    # push eax                ; keep the surface
    '31c0'                  # xor eax, eax
    'b919000000'            # mov ecx, 25
    'f3ab'                  # rep stosd               ; zero the DDBLTFX
    '58'                    # pop eax
    'c7042464000000'        # mov dword [esp], 100    ; dwSize
    'c7442450ffffffff'      # mov dword [esp+0x50], -1 ; dwFillDepth = far
    '89e1'                  # mov ecx, esp
    '51'                    # push ecx                ; lpDDBltFx
    '6800000003'            # push DDBLT_DEPTHFILL | DDBLT_WAIT
    '6a006a006a00'          # src rect, src surface, dest rect = whole surface
    '50'                    # push eax                ; this
    '8b08'                  # mov ecx, [eax]
    'ff5114'                # call [ecx+0x14]         ; IDirectDrawSurface7::Blt
    '83c464'                # add esp, 100
    '5f'                    # pop edi
    'c3'))                  # ret
write(0x437ce7, b'\xe8' + d32(zfill - (0x437ce7 + 5)) + b'\x90' * 13)

# Per-mode HUD scale (W/1024) used to place the resource counters in the top bar.
expect(0x595e14, '0000803f0000903f0000a03f0000a03f')
write(0x595e14, b''.join(struct.pack('<f', w / 1024) for w, _ in modes))

assert here() <= cave_end, 'cave overflow'
write(cave_start, bytes(cave))

# Cover the cave with the section's virtual size so it is part of the mapped code.
vs_off = text.get_file_offset() + 8
struct.pack_into('<I', data, vs_off, text.SizeOfRawData)

open(dst, 'wb').write(data)
print(f'patched {len(cave)} cave bytes at {cave_start:#x}; modes: ' + ', '.join(f'{w}x{h}' for w, h in modes))
print('sha256', hashlib.sha256(data).hexdigest())
