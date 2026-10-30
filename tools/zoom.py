"""Optional improvement for The Entente: smooth mouse-wheel zoom of the map.

Applied on top of fps_counter.py output. usage: python zoom.py IN.exe OUT.exe

The frame renderer 0x42b1d0 draws the whole map view into the back buffer first and the interface
(text queue at 0x42b4dc, minimap, top bar, panels) on top of it afterwards. The zoom works on that
finished map picture, so it does not matter how the game composes it (Direct3D sprites, depth
written by the CPU, the terrain kept between frames):
- The mouse thread (0x4224b0) reads buffered DirectInput events and ignored the wheel (offset 8).
  It now adds the wheel delta to a counter.
- 0x42b24a / 0x42b250 load the cursor position used to compute the map position under the cursor
  ([0x998ecc], [0x998ec8]: clicks, selection, the tile under the cursor). There the counter is turned
  into a target zoom (15 % per notch, 1x to 2.5x), the zoom moves a fifth of the way to the target
  each frame, and the cursor is mapped into the zoomed picture: centre + (cursor - centre) / zoom.
  The cursor itself, edge scrolling and the interface keep the real screen position.
- 0x42b4d7 (just before the interface is drawn) cuts the centre 1/zoom of the back buffer, stretches
  it into an offscreen surface of the screen size and copies that back.
- Things drawn with the map at the cursor position (the drag-selection rectangle 0x42b3f0, an
  effect at the cursor 0x466a20) read the mapped cursor, and the minimap frame of the visible area
  (0x43f04a) uses the zoomed tile counts.
Code lives in the padding after .rdata's virtual size, data in the zero-filled .reloc extension.
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

expect(0x422e68, '0003030300030303030303030102')  # mouse event offset -> case (offset 8 = wheel -> 3: ignored)
expect(0x42253f, 'ff2495582e4200')                # jmp [edx*4 + 0x422e58]
expect(0x42b24a, '8b15a0e25a00')                  # mov edx, [cursor x]
expect(0x42b250, '8b3d9ce25a00')                  # mov edi, [cursor y]
expect(0x42b4d7, 'b9985e9a00')                    # mov ecx, 0x9a5e98 (text queue, first interface call)
expect(0x9e3e50, '60')                            # fps_counter.py applied (pushal at its start)

rdata = next(s for s in pe.sections if s.Name.startswith(b'.rdata'))
CODE = (B + rdata.VirtualAddress + rdata.Misc_VirtualSize + 15) & ~15
CODE_END = B + rdata.VirtualAddress + rdata.SizeOfRawData
D = 0xa0cb00                                     # between smooth60.py's data (ends 0xa0ca14) and fps_counter.py's (0xa0cc00)
G_WHEEL, G_ZOOM, G_TARGET, G_SURF, G_SW, G_SH, G_SDD, G_TMP, G_C, G_VX, G_VY = (D + 4 * i for i in range(11))
G_MCX, G_MCY, G_MCOLS, G_MROWS = D + 0x2c, D + 0x2e, D + 0x30, D + 0x32    # minimap view frame (words)
SRC = D + 0x40                                   # RECT
DESC = D + 0x60                                  # DDSURFACEDESC2 (0x7c bytes), up to 0xa0cbdc
assert DESC + 0x7c <= 0xa0cc00
CUR_X, CUR_Y, W, H, BACK, DDRAW = 0x5ae2a0, 0x5ae29c, 0x5ae24e, 0x5ae24c, 0x5ae258, 0x5ae250
COLS, ROWS, CAM_X, CAM_Y = 0x8be38e, 0x8be38c, 0x599954, 0x599956
ONE, STEP, ZMAX, EASE, SNAP = 0x3f800000, 0x3f933333, 0x40200000, 0x3e4ccccd, 0x3b03126f   # 1, 1.15, 2.5, 0.2, 0.002

asm = f'''
wheel_case:
    mov eax, dword ptr [esp + 0x50]
    lock add dword ptr [{G_WHEEL:#x}], eax
    jmp 0x4224f5

cases:
    .long 0x422546, 0x4226af, 0x4228a6, 0x4224f5, wheel_case
k_step:
    .long {STEP:#x}
k_zmax:
    .long {ZMAX:#x}
k_ease:
    .long {EASE:#x}
k_snap:
    .long {SNAP:#x}

map_axis:
    shr edx, 1
    mov dword ptr [{G_C:#x}], edx
    mov eax, dword ptr [esp + 4]
    cmp dword ptr [{G_ZOOM:#x}], {ONE:#x}
    jbe ma_done
    mov dword ptr [{G_TMP:#x}], eax
    fild dword ptr [{G_TMP:#x}]
    fisub dword ptr [{G_C:#x}]
    fdiv dword ptr [{G_ZOOM:#x}]
    fiadd dword ptr [{G_C:#x}]
    fistp dword ptr [{G_TMP:#x}]
    mov eax, dword ptr [{G_TMP:#x}]
ma_done:
    ret 4

view_axis:                              ; [edi] = [esi] / zoom, [ebp] = [ebx] + ([esi] - [edi]) / 2 (words)
    movzx eax, word ptr [esi]
    mov dword ptr [{G_TMP:#x}], eax
    fild dword ptr [{G_TMP:#x}]
    fdiv dword ptr [{G_ZOOM:#x}]
    fistp dword ptr [{G_TMP:#x}]
    mov ecx, dword ptr [{G_TMP:#x}]
    mov word ptr [edi], cx
    sub eax, ecx
    sar eax, 1
    movzx ecx, word ptr [ebx]
    add eax, ecx
    mov word ptr [ebp], ax
    ret

zoom_update:
    cmp dword ptr [{G_TARGET:#x}], 0
    jne zu_init_done
    mov dword ptr [{G_TARGET:#x}], {ONE:#x}
    mov dword ptr [{G_ZOOM:#x}], {ONE:#x}
zu_init_done:
    xor eax, eax
    xchg dword ptr [{G_WHEEL:#x}], eax
    fld dword ptr [{G_TARGET:#x}]
zu_in:
    cmp eax, 60
    jl zu_out
    fmul dword ptr [k_step]
    sub eax, 120
    jmp zu_in
zu_out:
    cmp eax, -60
    jg zu_clamp
    fdiv dword ptr [k_step]
    add eax, 120
    jmp zu_out
zu_clamp:
    fld1
    fcomip st(0), st(1)
    jbe zu_not_low
    fstp st(0)
    fld1
zu_not_low:
    fld dword ptr [k_zmax]
    fcomip st(0), st(1)
    jae zu_not_high
    fstp st(0)
    fld dword ptr [k_zmax]
zu_not_high:
    fst dword ptr [{G_TARGET:#x}]
    fsub dword ptr [{G_ZOOM:#x}]
    fld st(0)
    fabs
    fld dword ptr [k_snap]
    fcomip st(0), st(1)
    fstp st(0)
    jb zu_ease
    fstp st(0)
    mov eax, dword ptr [{G_TARGET:#x}]
    mov dword ptr [{G_ZOOM:#x}], eax
    ret
zu_ease:
    fmul dword ptr [k_ease]
    fadd dword ptr [{G_ZOOM:#x}]
    fstp dword ptr [{G_ZOOM:#x}]
    ret

src_axis:
    mov dword ptr [{G_TMP:#x}], edx
    fild dword ptr [{G_TMP:#x}]
    fdiv dword ptr [{G_ZOOM:#x}]
    fistp dword ptr [{G_TMP:#x}]
    mov eax, edx
    sub eax, dword ptr [{G_TMP:#x}]
    sar eax, 1
    mov dword ptr [ebx], eax
    add eax, dword ptr [{G_TMP:#x}]
    mov dword ptr [ebx + 8], eax
    ret

ensure_surf:
    mov eax, dword ptr [{G_SURF:#x}]
    test eax, eax
    je es_create
    mov ecx, dword ptr [{DDRAW:#x}]
    cmp ecx, dword ptr [{G_SDD:#x}]
    jne es_forget
    movzx ecx, word ptr [{W:#x}]
    cmp ecx, dword ptr [{G_SW:#x}]
    jne es_release
    movzx ecx, word ptr [{H:#x}]
    cmp ecx, dword ptr [{G_SH:#x}]
    jne es_release
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x60]
    test eax, eax
    je es_ok
    mov eax, dword ptr [{G_SURF:#x}]
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x6c]
es_ok:
    mov eax, dword ptr [{G_SURF:#x}]
    ret
es_release:
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 8]
es_forget:
    mov dword ptr [{G_SURF:#x}], 0
es_create:
    mov edi, {DESC:#x}
    xor eax, eax
    mov ecx, 0x1f
    rep stosd dword ptr es:[edi], eax
    mov dword ptr [{DESC:#x}], 0x7c
    mov dword ptr [{DESC + 4:#x}], 7
    movzx eax, word ptr [{H:#x}]
    mov dword ptr [{DESC + 8:#x}], eax
    mov dword ptr [{G_SH:#x}], eax
    movzx eax, word ptr [{W:#x}]
    mov dword ptr [{DESC + 0xc:#x}], eax
    mov dword ptr [{G_SW:#x}], eax
    mov dword ptr [{DESC + 0x68:#x}], 0x4040
    mov eax, dword ptr [{DDRAW:#x}]
    mov dword ptr [{G_SDD:#x}], eax
    push 0
    push {G_SURF:#x}
    push {DESC:#x}
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x18]
    test eax, eax
    je es_ok
    mov dword ptr [{G_SURF:#x}], 0
    xor eax, eax
    ret

zoom_mx:
    pushal
    call zoom_update
    mov esi, {COLS:#x}
    mov edi, {G_MCOLS:#x}
    mov ebx, {CAM_X:#x}
    mov ebp, {G_MCX:#x}
    call view_axis
    mov esi, {ROWS:#x}
    mov edi, {G_MROWS:#x}
    mov ebx, {CAM_Y:#x}
    mov ebp, {G_MCY:#x}
    call view_axis
    popal
    movzx edx, word ptr [{W:#x}]
    push dword ptr [{CUR_X:#x}]
    call map_axis
    mov dword ptr [{G_VX:#x}], eax
    mov edx, eax
    ret

zoom_my:
    push eax
    push edx
    movzx edx, word ptr [{H:#x}]
    push dword ptr [{CUR_Y:#x}]
    call map_axis
    mov dword ptr [{G_VY:#x}], eax
    mov edi, eax
    pop edx
    pop eax
    ret

zoom_blit:
    pushal
    cmp dword ptr [{G_ZOOM:#x}], {ONE:#x}
    jbe zb_done
    cmp dword ptr [0x9c2b04], 0
    jne zb_done
    cmp byte ptr [0x998ee1], 0
    jne zb_done
    call ensure_surf
    test eax, eax
    je zb_done
    movzx edx, word ptr [{W:#x}]
    mov ebx, {SRC:#x}
    call src_axis
    movzx edx, word ptr [{H:#x}]
    add ebx, 4
    call src_axis
    push 0
    push 0x01000000
    push {SRC:#x}
    push dword ptr [{BACK:#x}]
    push 0
    mov eax, dword ptr [{G_SURF:#x}]
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x14]
    push 0x10
    push 0
    push dword ptr [{G_SURF:#x}]
    push 0
    push 0
    mov eax, dword ptr [{BACK:#x}]
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x1c]
zb_done:
    popal
    mov ecx, 0x9a5e98
    ret
'''

ks = Ks(KS_ARCH_X86, KS_MODE_32)
src_asm = '\n'.join(l.split(';')[0] for l in asm.splitlines())
code = bytes(ks.asm(src_asm, CODE)[0])
assert CODE + len(code) <= CODE_END, f'code too large: {len(code)} bytes'
assert not any(data[off(CODE):off(CODE) + len(code)]), '.rdata padding not empty'
data[off(CODE):off(CODE) + len(code)] = code

def label(name):
    head = src_asm.split('\n' + name + ':')[0]
    return CODE + len(bytes(ks.asm(head, CODE)[0])) if head.strip() else CODE

def call_at(at, name, pad=0):
    data[off(at):off(at) + 5 + pad] = b'\xe8' + struct.pack('<i', label(name) - (at + 5)) + b'\x90' * pad

data[off(0x422e70)] = 4                                      # offset 8 (wheel) -> case 4
data[off(0x42253f) + 3:off(0x42253f) + 7] = struct.pack('<I', label('cases'))
call_at(0x42b24a, 'zoom_mx', 1)
call_at(0x42b250, 'zoom_my', 1)
call_at(0x42b4d7, 'zoom_blit')
# the drag-selection rectangle is drawn with the map (0x42b3f0): end it at the mapped cursor
# and so is an effect drawn at the cursor (0x466a20, called from the map drawing at 0x42b368)
for at, var, op in ((0x42b404, G_VX, 'a1'), (0x42b41a, G_VY, '8b15'), (0x42b420, G_VX, 'a1'), (0x42b439, G_VY, '8b15'),
                    (0x466d57, G_VY, '8b15'), (0x466d6c, G_VX, '8b0d')):
    expect(at, op + ('a0e25a00' if var == G_VX else '9ce25a00'))
    data[off(at) + len(op) // 2:off(at) + len(op) // 2 + 4] = struct.pack('<I', var)

# the minimap frame of the visible area (0x43f04a-0x43f19b): camera tile and visible tile counts
for at, prefix, old, new in ((0x43f050, '66a1', CAM_X, G_MCX), (0x43f084, '668b15', CAM_Y, G_MCY),
                            (0x43f0e2, '668b15', COLS, G_MCOLS), (0x43f149, '668b15', COLS, G_MCOLS),
                            (0x43f11e, '668b0d', ROWS, G_MROWS), (0x43f177, '668b0d', ROWS, G_MROWS)):
    expect(at, prefix + struct.pack('<I', old).hex())
    data[off(at) + len(prefix) // 2:off(at) + len(prefix) // 2 + 4] = struct.pack('<I', new)

# .rdata: cover the code with the virtual size and make the section executable
hdr = rdata.get_file_offset()
struct.pack_into('<I', data, hdr + 8, rdata.SizeOfRawData)
struct.pack_into('<I', data, hdr + 36, rdata.Characteristics | 0x20000020)

open(dst, 'wb').write(data)
print(f'code {len(code)} bytes at {CODE:#x}, data at {D:#x}')
