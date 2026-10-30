"""Text overlay for The Entente: GDI text no longer forces a GPU read-back of the back buffer.

Applied on top of smooth60.py output. usage: python text_overlay.py IN.exe OUT.exe

The game draws its HUD text (resources, messages, selection panel, tips window) with GDI through
GetDC on the back buffer, several times per frame. Under a DirectDraw wrapper every such GetDC waits
for the GPU and copies the frame back to system memory; even a GetDC on a system-memory surface
copies and converts the whole surface (4.6 MB in 1920x1200), twice per GetDC/ReleaseDC.

- The GetDC / ReleaseDC entries of the surface vtable are hooked (once, on the first map frame).
  For the back buffer [0x5ae258] in the plain map view, at the call sites used in every frame of
  normal play, the game gets the memory DC of an "overlay" instead: a 16-bit 565 DIB section of the
  screen size, filled with the overlay's colour key, saved with SaveDC and bounds accumulation on.
  No DirectDraw call is made. Other call sites, surfaces and screens pass straight through.
- On ReleaseDC the area GDI touched (GetBoundsRect) is added to the overlay's dirty rectangle and
  the DC is restored (RestoreDC), so the game always gets it in its default state.
- Right before the map frame is presented (0x42b8ce) only the dirty rectangle is copied from the DIB
  into a system-memory DirectDraw surface (Lock of that rectangle), blitted onto the back buffer with
  the source colour key (an upload, no read-back) and reset to the key in the DIB. Two DirectDraw
  surfaces are used in turn, so a Lock never waits for the blit of the frame before.
- Anti-aliased text edges blend with the overlay's key colour, so there are two overlays: key 0x0001
  (near black) for light text on dark ground (resource bar, minimap, text queue, selection panel),
  and key 0xFF99 (the parchment colour) for the dark text of the tips window (0x4fd120), which with
  the dark key got a dark rim and looked bold.
Code lives in the padding after .rsrc's virtual size (the .reloc tail is used by smooth60.py and
fps_counter.py), data in the zero-filled .reloc extension.
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

rsrc = next(s for s in pe.sections if s.Name.startswith(b'.rsrc'))
CODE = (B + rsrc.VirtualAddress + rsrc.Misc_VirtualSize + 15) & ~15
CODE_END = B + rsrc.VirtualAddress + rsrc.SizeOfRawData
reloc = next(s for s in pe.sections if s.Name.startswith(b'.reloc'))
raw_lo = B + reloc.VirtualAddress
DATA = raw_lo + reloc.SizeOfRawData + 0x29000      # after smooth60.py's data
(G_HOOKED, G_GETDC, G_RELDC, G_OUT, G_OLDPROT, G_ROWS, G_I) = (DATA + 4 * i for i in range(7))
GDI_PROCS = [b'SetBoundsRect', b'GetBoundsRect', b'CreateCompatibleDC', b'CreateDIBSection', b'SaveDC',
             b'RestoreDC', b'GdiFlush', b'DeleteDC']
N_PROCS = len(GDI_PROCS)
G_PROCS = DATA + 0x20
(G_SETBOUNDS, G_GETBOUNDS, G_CREATEDC, G_CREATEDIB, G_SAVEDC, G_RESTOREDC, G_GDIFLUSH, G_DELETEDC) = (
    G_PROCS + 4 * i for i in range(N_PROCS))
TR = DATA + 0x40                                   # RECT returned by GetBoundsRect
DESC = DATA + 0x50                                 # DDSURFACEDESC2 (0x7c)
BMI = DATA + 0xd0                                  # BITMAPINFOHEADER + 3 colour masks (0x34)
# overlay: +0 colour key, +4 width (0: not created), +8 height, +0xc DirectDraw it was made with,
#          +0x10 0/4: which of the two DirectDraw surfaces at +0x14/+0x18 was used last,
#          +0x1c memory DC, +0x20 DIB bits, +0x24 number of dirty rectangles, +0x38 DIB handle,
#          +0x40 dirty RECTs (MAXR, one per GetDC)
MAXR = 32
OV_SIZE = 0x40 + 16 * MAXR
OV_LIGHT = DATA + 0x110
OV_DARK = OV_LIGHT + OV_SIZE
DATA_END = OV_DARK + OV_SIZE
assert DATA >= 0xa0cd00 and DATA_END <= 0xa0e000, 'overlaps zoom.py / fps_counter.py data (0xa0cb00-0xa0cd00)'
KEY_LIGHT = 0x0001                                 # near black: under light text on dark ground
KEY_DARK = 0xff99                                  # parchment: under the dark text of the tips window
LIGHT_SITES = [(0x444e39, 'resource bar'), (0x43f027, 'minimap'), (0x4fe2a6, 'text queue (messages, tooltips)'),
               (0x4fdd57, 'text measuring when a text is queued'), (0x4f85f9, 'selection panel'),
               (0x4fc07e, 'selection panel'), (0x4fbb48, 'label of a panel control (one GetDC per label, e.g. market)'),
               (0x500487, 'panel control text'), (0x4c6db0, 'panel control text')]
DARK_SITES = [(0x4fd120, 'tips window text')]

GetModuleHandleA, GetProcAddress = 0x9c88b8, 0x9c8924
BB, DDRAW, W, H = 0x5ae258, 0x5ae250, 0x5ae24e, 0x5ae24c
STRINGS = [b'KERNEL32.dll', b'VirtualProtect', b'GDI32.dll'] + GDI_PROCS

def site_checks():
    out = []
    for sites, ov in ((LIGHT_SITES, OV_LIGHT), (DARK_SITES, OV_DARK)):
        for va, name in sites:
            out.append(f'    mov ecx, {ov:#x}\n    cmp eax, {va:#x}                     ; {name}\n    je gd_site')
    return '\n'.join(out)

def build(s):
    return f'''
composite:
    pushal
    call ensure_hooks
    cmp dword ptr [{G_OUT:#x}], 0
    jne comp_done
    mov ebx, {OV_LIGHT:#x}
    call composite_one
    mov ebx, {OV_DARK:#x}
    call composite_one
comp_done:
    popal
    cmp byte ptr [0x5ae260], 1
    ret

composite_one:                            ; ebx = overlay
    cmp dword ptr [ebx + 4], 0
    je co_ret
    cmp dword ptr [ebx + 0x24], 0
    je co_ret
    lea edi, [ebx + 0x40]                 ; clamp the rectangles to the overlay (empty: right = left)
    mov ecx, dword ptr [ebx + 0x24]
co_clamp:
    xor eax, eax
    cmp dword ptr [edi], eax
    jge c1
    mov dword ptr [edi], eax
c1:
    cmp dword ptr [edi + 4], eax
    jge c2
    mov dword ptr [edi + 4], eax
c2:
    mov eax, dword ptr [ebx + 4]
    cmp dword ptr [edi + 8], eax
    jle c3
    mov dword ptr [edi + 8], eax
c3:
    mov eax, dword ptr [ebx + 8]
    cmp dword ptr [edi + 12], eax
    jle c4
    mov dword ptr [edi + 12], eax
c4:
    mov eax, dword ptr [edi + 12]
    cmp eax, dword ptr [edi + 4]
    jle c_empty
    mov eax, dword ptr [edi + 8]
    cmp eax, dword ptr [edi]
    jg c_next
c_empty:
    mov eax, dword ptr [edi]
    mov dword ptr [edi + 8], eax
    mov eax, dword ptr [edi + 4]
    mov dword ptr [edi + 12], eax
c_next:
    add edi, 16
    dec ecx
    jnz co_clamp
    call dword ptr [{G_GDIFLUSH:#x}]
    xor dword ptr [ebx + 0x10], 4         ; the other DirectDraw surface than last frame
    mov eax, dword ptr [ebx + 0x10]
    mov ebp, dword ptr [ebx + eax + 0x14]
    mov edi, {DESC:#x}                    ; copy the rectangles of the DIB into it
    xor eax, eax
    mov ecx, 0x1f
    rep stosd dword ptr es:[edi], eax
    mov dword ptr [{DESC:#x}], 0x7c
    push 0
    push 0x21                             ; DDLOCK_WAIT | DDLOCK_WRITEONLY
    push {DESC:#x}
    push 0
    push ebp
    mov ecx, dword ptr [ebp]
    call dword ptr [ecx + 0x64]
    test eax, eax
    jne co_clear
    mov dword ptr [{G_I:#x}], 0
co_rect:
    mov ecx, dword ptr [{G_I:#x}]
    shl ecx, 4
    lea ecx, [ebx + ecx + 0x40]
    mov eax, dword ptr [ecx + 12]
    sub eax, dword ptr [ecx + 4]
    jle co_rect_next
    mov dword ptr [{G_ROWS:#x}], eax
    mov edx, dword ptr [ebx + 4]
    add edx, edx                          ; DIB pitch
    mov eax, dword ptr [ecx + 4]
    imul eax, edx
    mov esi, dword ptr [ecx]
    lea esi, [eax + esi*2]
    add esi, dword ptr [ebx + 0x20]
    mov eax, dword ptr [ecx + 4]
    imul eax, dword ptr [{DESC + 0x10:#x}]
    mov edi, dword ptr [ecx]
    lea edi, [eax + edi*2]
    add edi, dword ptr [{DESC + 0x24:#x}]
    mov eax, dword ptr [ecx + 8]
    sub eax, dword ptr [ecx]
co_row:
    push esi
    push edi
    mov ecx, eax
    rep movsw word ptr es:[edi], word ptr [esi]
    pop edi
    pop esi
    add esi, edx
    add edi, dword ptr [{DESC + 0x10:#x}]
    dec dword ptr [{G_ROWS:#x}]
    jnz co_row
co_rect_next:
    inc dword ptr [{G_I:#x}]
    mov eax, dword ptr [{G_I:#x}]
    cmp eax, dword ptr [ebx + 0x24]
    jb co_rect
    push 0
    push ebp
    mov ecx, dword ptr [ebp]
    call dword ptr [ecx + 0x80]
    mov dword ptr [{G_I:#x}], 0
co_blt:
    mov edi, dword ptr [{G_I:#x}]
    shl edi, 4
    lea edi, [ebx + edi + 0x40]
    mov eax, dword ptr [edi + 8]
    cmp eax, dword ptr [edi]
    jle co_blt_next
    push 0
    push 0x1008000                        ; DDBLT_KEYSRC | DDBLT_WAIT
    push edi
    push ebp
    push edi
    mov eax, dword ptr [{BB:#x}]
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x14]
co_blt_next:
    inc dword ptr [{G_I:#x}]
    mov eax, dword ptr [{G_I:#x}]
    cmp eax, dword ptr [ebx + 0x24]
    jb co_blt
co_clear:                                 ; reset the rectangles of the DIB to the key colour
    mov dword ptr [{G_I:#x}], 0
cl_rect:
    mov ecx, dword ptr [{G_I:#x}]
    shl ecx, 4
    lea ecx, [ebx + ecx + 0x40]
    mov eax, dword ptr [ecx + 12]
    sub eax, dword ptr [ecx + 4]
    jle cl_rect_next
    mov dword ptr [{G_ROWS:#x}], eax
    mov edx, dword ptr [ebx + 4]
    add edx, edx
    mov eax, dword ptr [ecx + 4]
    imul eax, edx
    mov edi, dword ptr [ecx]
    lea edi, [eax + edi*2]
    add edi, dword ptr [ebx + 0x20]
    mov esi, dword ptr [ecx + 8]
    sub esi, dword ptr [ecx]
    mov eax, dword ptr [ebx]
cl_row:
    push edi
    mov ecx, esi
    rep stosw word ptr es:[edi], ax
    pop edi
    add edi, edx
    dec dword ptr [{G_ROWS:#x}]
    jnz cl_row
cl_rect_next:
    inc dword ptr [{G_I:#x}]
    mov eax, dword ptr [{G_I:#x}]
    cmp eax, dword ptr [ebx + 0x24]
    jb cl_rect
    mov dword ptr [ebx + 0x24], 0
co_ret:
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
    mov edi, {G_PROCS:#x}                 ; GDI32 functions, in the order of the names
    mov ebp, {s[3]:#x}
eh_proc:
    push ebp
    push ebx
    call dword ptr [{GetProcAddress:#x}]
    test eax, eax
    je eh_ret
    stosd dword ptr es:[edi], eax
eh_skip:
    inc ebp
    cmp byte ptr [ebp - 1], 0
    jne eh_skip
    cmp ebp, {s[3 + N_PROCS]:#x}
    jb eh_proc
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
    mov dword ptr [{OV_LIGHT:#x}], {KEY_LIGHT:#x}
    mov dword ptr [{OV_DARK:#x}], {KEY_DARK:#x}
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
{site_checks()}
    jmp gd_pass
gd_site:                                  ; ecx = overlay for this call site
    mov eax, dword ptr [esp + 4]
    cmp eax, dword ptr [{BB:#x}]
    jne gd_pass
    cmp dword ptr [0x9c2b04], 0
    jne gd_pass
    cmp byte ptr [0x998ee1], 0
    jne gd_pass
    cmp dword ptr [{G_OUT:#x}], 0
    jne gd_pass
    call ensure_overlay
    test eax, eax
    je gd_pass
    mov dword ptr [{G_OUT:#x}], ecx
    push ecx
    push dword ptr [ecx + 0x1c]
    call dword ptr [{G_SAVEDC:#x}]        ; the game gets a DC in its default state every time
    pop ecx
    push ecx
    push 5                                ; DCB_RESET | DCB_ENABLE
    push 0
    push dword ptr [ecx + 0x1c]
    call dword ptr [{G_SETBOUNDS:#x}]
    pop ecx
    mov eax, dword ptr [esp + 8]
    mov ecx, dword ptr [ecx + 0x1c]
    mov dword ptr [eax], ecx
    xor eax, eax
    ret 8
gd_pass:
    jmp dword ptr [{G_GETDC:#x}]

hook_releasedc:
    mov eax, dword ptr [esp + 4]
    cmp eax, dword ptr [{BB:#x}]
    jne rd_pass
    mov ecx, dword ptr [{G_OUT:#x}]
    test ecx, ecx
    je rd_pass
    mov dword ptr [{G_OUT:#x}], 0
    push ebx
    mov ebx, ecx
    push 0
    push {TR:#x}
    push dword ptr [ebx + 0x1c]
    call dword ptr [{G_GETBOUNDS:#x}]
    test eax, 2                           ; DCB_SET: something was drawn
    je rd_restore
    mov eax, dword ptr [{TR + 8:#x}]
    cmp eax, dword ptr [{TR:#x}]
    jle rd_restore
    mov ecx, dword ptr [ebx + 0x24]       ; one rectangle per GetDC; when full, grow the last one
    cmp ecx, {MAXR}
    jae rd_union
    inc dword ptr [ebx + 0x24]
    shl ecx, 4
    lea ecx, [ebx + ecx + 0x40]
    mov eax, dword ptr [{TR:#x}]
    mov dword ptr [ecx], eax
    mov eax, dword ptr [{TR + 4:#x}]
    mov dword ptr [ecx + 4], eax
    mov eax, dword ptr [{TR + 8:#x}]
    mov dword ptr [ecx + 8], eax
    mov eax, dword ptr [{TR + 12:#x}]
    mov dword ptr [ecx + 12], eax
    jmp rd_restore
rd_union:
    lea ecx, [ebx + {0x40 + 16 * (MAXR - 1):#x}]
    mov eax, dword ptr [{TR:#x}]
    cmp eax, dword ptr [ecx]
    jge u1
    mov dword ptr [ecx], eax
u1:
    mov eax, dword ptr [{TR + 4:#x}]
    cmp eax, dword ptr [ecx + 4]
    jge u2
    mov dword ptr [ecx + 4], eax
u2:
    mov eax, dword ptr [{TR + 8:#x}]
    cmp eax, dword ptr [ecx + 8]
    jle u3
    mov dword ptr [ecx + 8], eax
u3:
    mov eax, dword ptr [{TR + 12:#x}]
    cmp eax, dword ptr [ecx + 12]
    jle rd_restore
    mov dword ptr [ecx + 12], eax
rd_restore:
    push -1
    push dword ptr [ebx + 0x1c]
    call dword ptr [{G_RESTOREDC:#x}]
    pop ebx
    xor eax, eax
    ret 8
rd_pass:
    jmp dword ptr [{G_RELDC:#x}]

ensure_overlay:                           ; ecx = overlay (kept); eax = 0 if it has no surfaces
    pushal
    mov ebx, ecx
    cmp dword ptr [ebx + 4], 0
    je eo_create
    mov eax, dword ptr [{DDRAW:#x}]
    cmp eax, dword ptr [ebx + 0xc]
    jne eo_forget
    movzx eax, word ptr [{W:#x}]
    cmp eax, dword ptr [ebx + 4]
    jne eo_release
    movzx eax, word ptr [{H:#x}]
    cmp eax, dword ptr [ebx + 8]
    je eo_done
eo_release:
    lea esi, [ebx + 0x14]
    call release_surface
    lea esi, [ebx + 0x18]
    call release_surface
eo_forget:
    mov dword ptr [ebx + 0x14], 0
    mov dword ptr [ebx + 0x18], 0
    call release_dib
eo_create:
    mov dword ptr [ebx + 4], 0
    mov dword ptr [ebx + 0x24], 0
    movzx eax, word ptr [{H:#x}]
    mov dword ptr [ebx + 8], eax
    movzx eax, word ptr [{W:#x}]
    mov dword ptr [ebx + 4], eax
    mov eax, dword ptr [{DDRAW:#x}]
    mov dword ptr [ebx + 0xc], eax
    lea esi, [ebx + 0x14]
    call create_surface
    lea esi, [ebx + 0x18]
    call create_surface
    call create_dib
    cmp dword ptr [ebx + 0x14], 0
    je eo_fail
    cmp dword ptr [ebx + 0x18], 0
    je eo_fail
    cmp dword ptr [ebx + 0x20], 0
    jne eo_done
eo_fail:
    lea esi, [ebx + 0x14]
    call release_surface
    lea esi, [ebx + 0x18]
    call release_surface
    call release_dib
    mov dword ptr [ebx + 4], 0
eo_done:
    popal
    mov eax, dword ptr [ecx + 4]
    ret

release_surface:                          ; esi = pointer to the surface field
    mov eax, dword ptr [esi]
    test eax, eax
    je rs_ret
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 8]
    mov dword ptr [esi], 0
rs_ret:
    ret

create_surface:                           ; ebx = overlay, esi = pointer to the surface field
    mov dword ptr [esi], 0
    mov edi, {DESC:#x}
    xor eax, eax
    mov ecx, 0x1f
    rep stosd dword ptr es:[edi], eax
    mov dword ptr [{DESC:#x}], 0x7c
    mov dword ptr [{DESC + 4:#x}], 0x10007
    mov eax, dword ptr [ebx + 8]
    mov dword ptr [{DESC + 8:#x}], eax
    mov eax, dword ptr [ebx + 4]
    mov dword ptr [{DESC + 0xc:#x}], eax
    mov eax, dword ptr [ebx]
    mov dword ptr [{DESC + 0x40:#x}], eax
    mov dword ptr [{DESC + 0x44:#x}], eax
    mov dword ptr [{DESC + 0x68:#x}], 0x840
    mov eax, dword ptr [ebx + 0xc]
    test eax, eax
    je cs_ret
    push 0
    push esi
    push {DESC:#x}
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x18]
    test eax, eax
    je cs_ret
    mov dword ptr [esi], 0
cs_ret:
    ret

release_dib:                              ; ebx = overlay
    mov eax, dword ptr [ebx + 0x1c]
    test eax, eax
    je rdib_bmp
    push eax
    call dword ptr [{G_DELETEDC:#x}]
rdib_bmp:
    mov eax, dword ptr [ebx + 0x38]
    test eax, eax
    je rdib_ret
    push eax
    call dword ptr [0x9c8764]             ; DeleteObject
rdib_ret:
    mov dword ptr [ebx + 0x1c], 0
    mov dword ptr [ebx + 0x20], 0
    mov dword ptr [ebx + 0x38], 0
    ret

create_dib:                               ; ebx = overlay: memory DC with a 16-bit 565 DIB section, filled with the key
    mov dword ptr [ebx + 0x20], 0
    push 0
    call dword ptr [{G_CREATEDC:#x}]
    mov dword ptr [ebx + 0x1c], eax
    test eax, eax
    je cd_ret
    mov edi, {BMI:#x}
    xor eax, eax
    mov ecx, 13
    rep stosd dword ptr es:[edi], eax
    mov dword ptr [{BMI:#x}], 40
    mov eax, dword ptr [ebx + 4]
    mov dword ptr [{BMI + 4:#x}], eax
    mov eax, dword ptr [ebx + 8]
    neg eax
    mov dword ptr [{BMI + 8:#x}], eax     ; top-down
    mov dword ptr [{BMI + 12:#x}], 0x100001
    mov dword ptr [{BMI + 16:#x}], 3      ; BI_BITFIELDS
    mov dword ptr [{BMI + 40:#x}], 0xf800
    mov dword ptr [{BMI + 44:#x}], 0x7e0
    mov dword ptr [{BMI + 48:#x}], 0x1f
    push 0
    push 0
    lea eax, [ebx + 0x20]
    push eax
    push 0
    push {BMI:#x}
    push dword ptr [ebx + 0x1c]
    call dword ptr [{G_CREATEDIB:#x}]
    mov dword ptr [ebx + 0x38], eax
    test eax, eax
    je cd_fail
    push eax
    push dword ptr [ebx + 0x1c]
    call dword ptr [0x9c8768]             ; SelectObject
    mov edi, dword ptr [ebx + 0x20]
    mov ecx, dword ptr [ebx + 4]
    imul ecx, dword ptr [ebx + 8]
    mov eax, dword ptr [ebx]
    rep stosw word ptr es:[edi], ax
cd_ret:
    ret
cd_fail:
    mov dword ptr [ebx + 0x20], 0
    ret
'''

ks = Ks(KS_ARCH_X86, KS_MODE_32)
asm_text = lambda s: '\n'.join(l.split(';')[0] for l in build(s).splitlines())
blob = b''.join(x + b'\0' for x in STRINGS)
strings_at = CODE + 0x1000                         # any 32-bit value, so pushes get their final size
while True:
    s, a = [], strings_at
    for x in STRINGS:
        s.append(a); a += len(x) + 1
    s.append(a)                                    # end of the names
    code = bytes(ks.asm(asm_text(s), CODE)[0])
    if CODE + len(code) == strings_at:
        break
    strings_at = CODE + len(code)
code += blob
assert CODE + len(code) <= CODE_END, f'code too large: {len(code)} bytes'
assert not any(data[off(CODE):off(CODE) + len(code)])
data[off(CODE):off(CODE) + len(code)] = code

# composite is the first label: call it instead of the 7-byte cmp (it ends with the same cmp)
data[off(0x42b8ce):off(0x42b8ce) + 7] = b'\xe8' + struct.pack('<i', CODE - (0x42b8ce + 5)) + b'\x90\x90'

# .rsrc: cover the code with the virtual size and make it executable
hdr = rsrc.get_file_offset()
struct.pack_into('<I', data, hdr + 8, rsrc.SizeOfRawData)
struct.pack_into('<I', data, hdr + 36, rsrc.Characteristics | 0x20000020)
# .reloc: the data must be inside the virtual size
hdr = reloc.get_file_offset()
vsize = max((DATA_END - raw_lo + 0xfff) & ~0xfff, reloc.Misc_VirtualSize)
struct.pack_into('<I', data, hdr + 8, vsize)
size_of_image = (reloc.VirtualAddress + vsize + 0xfff) & ~0xfff
struct.pack_into('<I', data, pe.OPTIONAL_HEADER.get_file_offset() + 56, size_of_image)
open(dst, 'wb').write(data)
print(f'code {len(code)} bytes at {CODE:#x}, data at {DATA:#x}, SizeOfImage {size_of_image:#x}')
