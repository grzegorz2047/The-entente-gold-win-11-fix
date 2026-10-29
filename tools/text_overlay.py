"""Text overlay for The Entente: GDI text no longer forces a GPU read-back of the back buffer.

Applied on top of smooth60.py output. usage: python text_overlay.py IN.exe OUT.exe

The game draws its HUD text (resources, messages, selection panel) with GDI through GetDC on the
back buffer, several times per frame. Under a DirectDraw wrapper every such GetDC waits for the GPU
and copies the frame back to system memory.

- The GetDC / ReleaseDC entries of the surface vtable are hooked (once, on the first map frame).
  For the back buffer [0x5ae258] in the plain map view, at the call sites used in every frame of
  normal play, which draw light text on dark ground or only measure text (resource bar, minimap,
  text queue, selection panel), the DC of a system-memory surface
  of the same size ("overlay", cleared to colour key 0x0001) is handed out instead, with GDI bounds
  accumulation switched on. Other call sites, surfaces and screens pass straight through: with a
  colour key, anti-aliased edges of dark text (e.g. the tips window) blend into a dark rim.
- On ReleaseDC the area GDI touched (GetBoundsRect) is added to a dirty rectangle.
- Right before the map frame is presented (0x42b8ce) only the dirty rectangle of the overlay is
  blitted onto the back buffer with the source colour key (an upload, no read-back) and cleared.
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

expect(0x42b8ce, '803d60e25a0001')                 # cmp byte ptr [0x5ae260], 1  (before Flip / Blt)
expect(0x9e3580, 'ff15e4889c00')                   # smooth60.py must already be applied

reloc = next(s for s in pe.sections if s.Name.startswith(b'.reloc'))
raw_lo = B + reloc.VirtualAddress
raw_hi = raw_lo + reloc.SizeOfRawData
used = max(i for i in range(off(raw_lo), off(raw_hi)) if data[i]) - off(raw_lo) + raw_lo
CODE = (used + 32) & ~15
DATA = raw_hi + 0x29000                            # after smooth60.py's data
(G_OVL, G_OVL_W, G_OVL_H, G_OVL_DD, G_HOOKED, G_GETDC, G_RELDC, G_DC_OUT, G_DIRTY, G_OLDPROT,
 G_SETBOUNDS, G_GETBOUNDS, G_HDC) = (DATA + 4 * i for i in range(13))
DR = DATA + 0x40                                   # dirty RECT (left, top, right, bottom)
TR = DATA + 0x50                                   # RECT returned by GetBoundsRect
DESC = DATA + 0x60                                 # DDSURFACEDESC2 (0x7c)
FX = DATA + 0xe0                                   # DDBLTFX (0x64)
DATA_END = DATA + 0x150
KEY = 0x0001                                       # near-black: AA fringes blend into a dark edge

GetModuleHandleA, GetProcAddress = 0x9c88b8, 0x9c8924
BB, DDRAW, W, H = 0x5ae258, 0x5ae250, 0x5ae24e, 0x5ae24c
STRINGS = [b'KERNEL32.dll', b'VirtualProtect', b'GDI32.dll', b'SetBoundsRect', b'GetBoundsRect']

def build(s):
    return f'''
composite:
    pushal
    call ensure_hooks
    cmp dword ptr [{G_DIRTY:#x}], 0
    je comp_done
    cmp dword ptr [{G_DC_OUT:#x}], 0
    jne comp_done
    mov eax, dword ptr [{G_OVL:#x}]
    test eax, eax
    je comp_done
    xor eax, eax                          ; clamp the dirty rectangle to the overlay
    cmp dword ptr [{DR:#x}], eax
    jge c1
    mov dword ptr [{DR:#x}], eax
c1:
    cmp dword ptr [{DR + 4:#x}], eax
    jge c2
    mov dword ptr [{DR + 4:#x}], eax
c2:
    mov eax, dword ptr [{G_OVL_W:#x}]
    cmp dword ptr [{DR + 8:#x}], eax
    jle c3
    mov dword ptr [{DR + 8:#x}], eax
c3:
    mov eax, dword ptr [{G_OVL_H:#x}]
    cmp dword ptr [{DR + 12:#x}], eax
    jle c4
    mov dword ptr [{DR + 12:#x}], eax
c4:
    mov eax, dword ptr [{DR + 8:#x}]
    cmp eax, dword ptr [{DR:#x}]
    jle comp_reset
    mov eax, dword ptr [{DR + 12:#x}]
    cmp eax, dword ptr [{DR + 4:#x}]
    jle comp_reset
    push 0
    push 0x1008000
    push {DR:#x}
    push dword ptr [{G_OVL:#x}]
    push {DR:#x}
    mov eax, dword ptr [{BB:#x}]
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x14]
    push {DR:#x}
    call clear_overlay
comp_reset:
    mov dword ptr [{G_DIRTY:#x}], 0
comp_done:
    popal
    cmp byte ptr [0x5ae260], 1
    ret

ensure_hooks:
    cmp dword ptr [{G_HOOKED:#x}], 0
    jne eh_ret
    mov eax, dword ptr [{BB:#x}]
    test eax, eax
    je eh_ret
    mov esi, dword ptr [eax]
    push {s[2]:#x}
    call dword ptr [{GetModuleHandleA:#x}]
    test eax, eax
    je eh_ret
    mov ebx, eax
    push {s[3]:#x}
    push ebx
    call dword ptr [{GetProcAddress:#x}]
    mov dword ptr [{G_SETBOUNDS:#x}], eax
    push {s[4]:#x}
    push ebx
    call dword ptr [{GetProcAddress:#x}]
    mov dword ptr [{G_GETBOUNDS:#x}], eax
    test eax, eax
    je eh_ret
    cmp dword ptr [{G_SETBOUNDS:#x}], 0
    je eh_ret
    push {s[0]:#x}
    call dword ptr [{GetModuleHandleA:#x}]
    test eax, eax
    je eh_ret
    push {s[1]:#x}
    push eax
    call dword ptr [{GetProcAddress:#x}]
    test eax, eax
    je eh_ret
    push {G_OLDPROT:#x}
    push 0x40
    push 0x2c
    lea ecx, [esi + 0x44]
    push ecx
    call eax
    test eax, eax
    je eh_ret
    mov eax, dword ptr [esi + 0x44]
    mov dword ptr [{G_GETDC:#x}], eax
    mov eax, dword ptr [esi + 0x68]
    mov dword ptr [{G_RELDC:#x}], eax
    mov dword ptr [esi + 0x44], hook_getdc
    mov dword ptr [esi + 0x68], hook_releasedc
    mov dword ptr [{G_HOOKED:#x}], esi
eh_ret:
    ret

hook_getdc:
    mov eax, dword ptr [esp]              ; call site
    cmp eax, 0x444e39                     ; resource bar
    je gd_site
    cmp eax, 0x43f027                     ; minimap
    je gd_site
    cmp eax, 0x4fe2a6                     ; text queue (messages, tooltips)
    je gd_site
    cmp eax, 0x4fdd57                     ; text measuring when a text is queued
    je gd_site
    cmp eax, 0x4f85f9                     ; selection panel
    je gd_site
    cmp eax, 0x4fc07e                     ; selection panel
    jne gd_pass
gd_site:
    mov eax, dword ptr [esp + 4]
    cmp eax, dword ptr [{BB:#x}]
    jne gd_pass
    cmp dword ptr [0x9c2b04], 0
    jne gd_pass
    cmp byte ptr [0x998ee1], 0
    jne gd_pass
    cmp dword ptr [{G_DC_OUT:#x}], 0
    jne gd_pass
    call ensure_overlay
    test eax, eax
    je gd_pass
    push dword ptr [esp + 8]
    push eax
    call dword ptr [{G_GETDC:#x}]
    test eax, eax
    jne gd_ret
    mov dword ptr [{G_DC_OUT:#x}], 1
    mov eax, dword ptr [esp + 8]
    mov eax, dword ptr [eax]
    mov dword ptr [{G_HDC:#x}], eax
    push 5                                ; DCB_RESET | DCB_ENABLE
    push 0
    push eax
    call dword ptr [{G_SETBOUNDS:#x}]
    xor eax, eax
gd_ret:
    ret 8
gd_pass:
    jmp dword ptr [{G_GETDC:#x}]

hook_releasedc:
    mov eax, dword ptr [esp + 4]
    cmp eax, dword ptr [{BB:#x}]
    jne rd_pass
    cmp dword ptr [{G_DC_OUT:#x}], 0
    je rd_pass
    mov dword ptr [{G_DC_OUT:#x}], 0
    push 0
    push {TR:#x}
    push dword ptr [{G_HDC:#x}]
    call dword ptr [{G_GETBOUNDS:#x}]
    test eax, 2                           ; DCB_SET: something was drawn
    je rd_release
    mov eax, dword ptr [{TR + 8:#x}]
    cmp eax, dword ptr [{TR:#x}]
    jle rd_release
    cmp dword ptr [{G_DIRTY:#x}], 0
    jne rd_union
    mov eax, dword ptr [{TR:#x}]
    mov dword ptr [{DR:#x}], eax
    mov eax, dword ptr [{TR + 4:#x}]
    mov dword ptr [{DR + 4:#x}], eax
    mov eax, dword ptr [{TR + 8:#x}]
    mov dword ptr [{DR + 8:#x}], eax
    mov eax, dword ptr [{TR + 12:#x}]
    mov dword ptr [{DR + 12:#x}], eax
    mov dword ptr [{G_DIRTY:#x}], 1
    jmp rd_release
rd_union:
    mov eax, dword ptr [{TR:#x}]
    cmp eax, dword ptr [{DR:#x}]
    jge u1
    mov dword ptr [{DR:#x}], eax
u1:
    mov eax, dword ptr [{TR + 4:#x}]
    cmp eax, dword ptr [{DR + 4:#x}]
    jge u2
    mov dword ptr [{DR + 4:#x}], eax
u2:
    mov eax, dword ptr [{TR + 8:#x}]
    cmp eax, dword ptr [{DR + 8:#x}]
    jle u3
    mov dword ptr [{DR + 8:#x}], eax
u3:
    mov eax, dword ptr [{TR + 12:#x}]
    cmp eax, dword ptr [{DR + 12:#x}]
    jle rd_release
    mov dword ptr [{DR + 12:#x}], eax
rd_release:
    push dword ptr [esp + 8]
    push dword ptr [{G_OVL:#x}]
    call dword ptr [{G_RELDC:#x}]
    ret 8
rd_pass:
    jmp dword ptr [{G_RELDC:#x}]

ensure_overlay:
    pushal
    mov eax, dword ptr [{G_OVL:#x}]
    test eax, eax
    je eo_create
    mov ecx, dword ptr [{DDRAW:#x}]
    cmp ecx, dword ptr [{G_OVL_DD:#x}]
    jne eo_forget
    movzx ecx, word ptr [{W:#x}]
    cmp ecx, dword ptr [{G_OVL_W:#x}]
    jne eo_release
    movzx ecx, word ptr [{H:#x}]
    cmp ecx, dword ptr [{G_OVL_H:#x}]
    je eo_done
eo_release:
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 8]
eo_forget:
    mov dword ptr [{G_OVL:#x}], 0
    mov dword ptr [{G_DIRTY:#x}], 0
eo_create:
    mov edi, {DESC:#x}
    xor eax, eax
    mov ecx, 0x1f
    rep stosd dword ptr es:[edi], eax
    mov dword ptr [{DESC:#x}], 0x7c
    mov dword ptr [{DESC + 4:#x}], 0x10007
    movzx eax, word ptr [{H:#x}]
    mov dword ptr [{DESC + 8:#x}], eax
    mov dword ptr [{G_OVL_H:#x}], eax
    movzx eax, word ptr [{W:#x}]
    mov dword ptr [{DESC + 0xc:#x}], eax
    mov dword ptr [{G_OVL_W:#x}], eax
    mov dword ptr [{DESC + 0x40:#x}], {KEY}
    mov dword ptr [{DESC + 0x44:#x}], {KEY}
    mov dword ptr [{DESC + 0x68:#x}], 0x840
    mov eax, dword ptr [{DDRAW:#x}]
    mov dword ptr [{G_OVL_DD:#x}], eax
    test eax, eax
    je eo_done
    push 0
    push {G_OVL:#x}
    push {DESC:#x}
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x18]
    test eax, eax
    je eo_clear
    mov dword ptr [{G_OVL:#x}], 0
    jmp eo_done
eo_clear:
    push 0
    call clear_overlay
eo_done:
    popal
    mov eax, dword ptr [{G_OVL:#x}]
    ret

clear_overlay:                            ; stdcall(RECT* or 0 for the whole surface)
    mov edi, {FX:#x}
    xor eax, eax
    mov ecx, 0x19
    rep stosd dword ptr es:[edi], eax
    mov dword ptr [{FX:#x}], 0x64
    mov dword ptr [{FX + 0x50:#x}], {KEY}
    mov eax, dword ptr [{G_OVL:#x}]
    push {FX:#x}
    push 0x1000400
    push 0
    push 0
    push dword ptr [esp + 0x14]
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x14]
    ret 4
'''

ks = Ks(KS_ARCH_X86, KS_MODE_32)
asm_text = lambda s: '\n'.join(l.split(';')[0] for l in build(s).splitlines())
blob = b''.join(x + b'\0' for x in STRINGS)
strings_at = CODE + 0x1000                         # any 32-bit value, so pushes get their final size
while True:
    s, a = [], strings_at
    for x in STRINGS:
        s.append(a); a += len(x) + 1
    code = bytes(ks.asm(asm_text(s), CODE)[0])
    if CODE + len(code) == strings_at:
        break
    strings_at = CODE + len(code)
code += blob
assert CODE + len(code) <= raw_hi, f'code too large: {len(code)} bytes'
assert not any(data[off(CODE):off(CODE) + len(code)])
data[off(CODE):off(CODE) + len(code)] = code

# composite is the first label: call it instead of the 7-byte cmp (it ends with the same cmp)
data[off(0x42b8ce):off(0x42b8ce) + 7] = b'\xe8' + struct.pack('<i', CODE - (0x42b8ce + 5)) + b'\x90\x90'

hdr = reloc.get_file_offset()
vsize = max((DATA_END - raw_lo + 0xfff) & ~0xfff, reloc.Misc_VirtualSize)
struct.pack_into('<I', data, hdr + 8, vsize)
size_of_image = (reloc.VirtualAddress + vsize + 0xfff) & ~0xfff
struct.pack_into('<I', data, pe.OPTIONAL_HEADER.get_file_offset() + 56, size_of_image)
open(dst, 'wb').write(data)
print(f'code {len(code)} bytes at {CODE:#x}, data at {DATA:#x}, SizeOfImage {size_of_image:#x}')
