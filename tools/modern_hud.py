"""Modern HUD for The Entente (improvements): no screen frame, a semi-transparent top bar.

Applied last in the improvements chain (after terrain_strip.py). usage: python modern_hud.py IN.exe OUT.exe

- The four map bevels (MapBevelUp/Down/Left/Right.bmp, blitted by 0x4e11c0 every frame) are no longer
  drawn, so the map fills the whole screen. The thermometer (the electricity balance on the right edge)
  is not drawn either; the balance moves into the top bar.
- Right before 0x4e11c0 (call at 0x42b4ee) a dark, semi-transparent band with a thin light edge is
  drawn over the top of the screen with Direct3D (its own BeginScene/EndScene; texture, render states
  and texture stage states used are saved and restored), together with a horizontal electricity gauge:
  the game's balance 2 * (production * efficiency - demand / supply factor), clamped to +-78, filled
  from the left and coloured from red (deficit) through yellow to green (surplus) as the thermometer.
- The resource bar 0x444e10 draws, with the DC it already has (the text overlay's), the game's own
  resource icons (IconsGold/Food/Wood/Iron/Oil.bmp from the market buttons, IconsCountUnits.bmp)
  scaled with GDI halftone, each followed by its value in Segoe UI with a shadow; the population is
  shown with the housing limit ("721/800", red when the limit is reached). The icons are read from
  Interface.les once, while the game loads the HUD bitmaps (0x4e0640, the archive is open then).
- The FPS counter of fps_counter.py moves into the band (transparent background).
- Sizes follow the screen height: font max(14, H * 22 / 1200) px (22 in 1920x1200), icons 4/3 of it,
  the band 8 px taller than the icons. The game's "build more houses" message at the top left moves
  below the band.
The game is loaded at its preferred base (no ASLR flag), so its base relocations are never applied;
the code and data live where the relocation table was (0x9cb000), and the table is dropped.
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
jmp = lambda at, to: b'\xe9' + struct.pack('<i', to - (at + 5))

def expect(va, hexbytes):
    got = bytes(data[off(va):off(va) + len(bytes.fromhex(hexbytes))])
    if got != bytes.fromhex(hexbytes):
        sys.exit(f'unexpected bytes at {va:#x}: {got.hex()}')

if data[off(0x44506d)] != 0xe8:                   # fps_counter.py applied (its call at 0x44506d)
    sys.exit('apply fps_counter.py first')
expect(0x42b4ee, call(0x42b4ee, 0x4018e3).hex())   # call 0x4e11c0 (map bevels, thermometer, buttons)
expect(0x444e41, 'a1c08e9900')                    # resource bar after GetDC: mov eax, [0x998ec0] (font)
expect(0x4e0640, call(0x4e0640, 0x4042dc).hex())   # free the Econom+.bmp data (Interface.les is open)
expect(0x4450c7, '6a166a1e')                      # "build more houses" queued at y 0x16, x 0x1e
BEVEL_BLTS = [(0x4e1201, 'ff5114'), (0x4e1237, 'ff5114'), (0x4e1276, 'ff5214'), (0x4e12bd, 'ff5214')]
THERMOMETER = [(0x4e13a4, 'ff521c'), (0x4e13c4, 'ff5214')]   # BltFast of the scale, colour fill of the level
for va, hexbytes in BEVEL_BLTS + THERMOMETER:
    expect(va, hexbytes)

relocs = pe.OPTIONAL_HEADER.DATA_DIRECTORY[5]
CODE = B + relocs.VirtualAddress
CODE_END = CODE + relocs.Size
assert relocs.Size and pe.OPTIONAL_HEADER.DllCharacteristics & 0x40 == 0, 'relocations needed'
DATA = CODE + 0x1000                              # code before it, the old table's bytes after it stay unused
G = lambda i: DATA + 4 * i
(G_INIT, G_FONT, G_FONTSYM, G_FH, P_STRETCHDIB, P_SETSTRETCH, G_ICONS_DONE, G_TMP) = (G(i) for i in range(8))
ICONS = DATA + 0x20                               # BMP file data of the 6 icons
SIZE = DATA + 0x38                                # SIZE (cx, cy) of GetTextExtentPoint32W
(G_FHN, G_BAR, G_ICON, G_X, G_GAUGE_X, G_V, G_VP, G_SCENE, G_TEX, G_COLOR, G_TEXTY, G_MINW, G_LEN,
 G_GREF, G_NV) = (DATA + 0x40 + 4 * i for i in range(15))
SAVED_RS = DATA + 0x80
SAVED_TSS = DATA + 0xc0
RS_TABLE = DATA + 0xe0
TSS_TABLE = DATA + 0x140
VAL_OFF = DATA + 0x180
ICON_NAMES = DATA + 0x1a0
STR = DATA + 0x1c0
TXT = DATA + 0x240
VB = DATA + 0x300                                 # up to 24 vertices of 20 bytes
DATA_END = DATA + 0x500
assert DATA_END <= CODE_END

# render states (state, value) and texture stage states (stage, type, value) of the band
RS = [(7, 0), (14, 0), (15, 0), (52, 0), (27, 1), (19, 5), (20, 6), (22, 1), (28, 0), (29, 0), (41, 0),
      (8, 3), (9, 2)]                             # z, z write, alpha test, stencil, blend src alpha, cull, fog...
TSS = [(0, 1, 2), (0, 2, 0), (0, 4, 2), (0, 5, 0), (1, 1, 1), (1, 4, 1)]   # stage 0: diffuse only; stage 1 off
VALUES = [0x200b8, 0x200f8, 0x200c8, 0x200d8, 0x200e8]   # gold, food, wood, iron, oil (doubles in the player)
NAMES = [0x5a1434, 0x5a148c, 0x5a13f0, 0x5a13ac, 0x5a136c, 0x59eb54]   # IconsGold ... IconsCountUnits.bmp
STRINGS = [b'GDI32.dll', b'StretchDIBits', b'SetStretchBltMode', b'Segoe UI', b'Segoe UI Symbol']
s_at, a = [], STR
for x in STRINGS:
    s_at.append(a); a += len(x) + 1
W_ZEROS = a + 1 & ~1                              # "00000": the narrowest a value field gets
W_BOLT = W_ZEROS + 12                             # U+26A1 high voltage sign
assert W_BOLT + 4 <= TXT

GetModuleHandleA, GetProcAddress = 0x9c88b8, 0x9c8924
DeleteObject, SelectObject, TextOutW, SetTextColor, SetBkMode, CreateFontA, GetTextExtentPoint32W = (
    0x9c8764, 0x9c8768, 0x9c8770, 0x9c8778, 0x9c8780, 0x9c8790, 0x9c8798)
W, H, DEVICE, PLAYER, PLAYERS = 0x5ae24e, 0x5ae24c, 0x5ae1f0, 0x5ceb02, 0x9a5994
FTOL = 0x55be00
FONT_PER_1200, FONT_MIN = 22, 14                   # font height: px per 1200 px of screen height, minimum
VALUE_RGB, LIMIT_RGB = 0xf0f0f0, 0x5050ff          # COLORREF (0x00bbggrr)
BAND_TOP, BAND_BOTTOM, EDGE = 0xb40c1016, 0x8c0c1016, 0x50d0b070   # ARGB

asm = f'''
hud_frame:                                ; instead of call 0x4e11c0 at 0x42b4ee
    pushal
    call draw_band
    popal
    jmp 0x4018e3

hud_res:                                  ; at 0x444e41, [esp] = DC of the resource bar
    pushal
    mov ebp, dword ptr [esp + 0x20]
    call layout
    call ensure_init
    call ensure_fonts
    mov eax, dword ptr [{G_FONT:#x}]
    test eax, eax
    jne hr_font
    mov eax, dword ptr [0x998ec0]         ; the game's font if Segoe UI could not be made
hr_font:
    push eax
    push ebp
    call dword ptr [{SelectObject:#x}]
    push 1                                ; TRANSPARENT
    push ebp
    call dword ptr [{SetBkMode:#x}]
    mov eax, dword ptr [{P_SETSTRETCH:#x}]
    test eax, eax
    je hr_mode
    push 4                                ; HALFTONE
    push ebp
    call eax
hr_mode:
    push {SIZE:#x}
    push 5
    push {W_ZEROS:#x}
    push ebp
    call dword ptr [{GetTextExtentPoint32W:#x}]
    mov eax, dword ptr [{SIZE:#x}]
    mov dword ptr [{G_MINW:#x}], eax
    mov eax, dword ptr [{G_BAR:#x}]
    sub eax, dword ptr [{SIZE + 4:#x}]
    sar eax, 1
    mov dword ptr [{G_TEXTY:#x}], eax
    mov eax, dword ptr [{G_FHN:#x}]
    shr eax, 1
    mov dword ptr [{G_X:#x}], eax
    movzx eax, byte ptr [{PLAYER:#x}]
    mov ebx, dword ptr [eax*4 + {PLAYERS:#x}]
    xor esi, esi
hr_item:
    mov eax, dword ptr [esi*4 + {ICONS:#x}]
    test eax, eax
    je hr_noicon
    call draw_icon
hr_noicon:
    mov eax, dword ptr [{G_FHN:#x}]
    shr eax, 2
    add eax, dword ptr [{G_ICON:#x}]
    add dword ptr [{G_X:#x}], eax
    mov edi, {TXT:#x}
    cmp esi, 5
    je hr_pop
    mov eax, dword ptr [esi*4 + {VAL_OFF:#x}]
    fld qword ptr [ebx + eax]
    call {FTOL:#x}
    test eax, eax
    jge hr_num
    xor eax, eax
hr_num:
    call put_wnum
    mov ecx, {VALUE_RGB:#x}
    jmp hr_text
hr_pop:
    mov ecx, {VALUE_RGB:#x}
    mov eax, dword ptr [ebx + 0x20098]
    call put_wnum
    mov word ptr [edi], 0x2f
    add edi, 2
    movzx edx, word ptr [ebx + 0x2cc88]
    cmp dword ptr [ebx + 0x20098], edx
    jl hr_limit
    mov ecx, {LIMIT_RGB:#x}
hr_limit:
    mov eax, edx
    call put_wnum
hr_text:
    sub edi, {TXT:#x}
    shr edi, 1
    mov dword ptr [{G_LEN:#x}], edi
    call draw_text
    push {SIZE:#x}
    push dword ptr [{G_LEN:#x}]
    push {TXT:#x}
    push ebp
    call dword ptr [{GetTextExtentPoint32W:#x}]
    mov eax, dword ptr [{SIZE:#x}]
    cmp eax, dword ptr [{G_MINW:#x}]
    jge hr_wide
    mov eax, dword ptr [{G_MINW:#x}]
hr_wide:
    add eax, dword ptr [{G_FHN:#x}]
    add dword ptr [{G_X:#x}], eax
    inc esi
    cmp esi, 6
    jb hr_item
    mov eax, dword ptr [{G_FONTSYM:#x}]   ; the electricity sign, in the colour of the gauge
    test eax, eax
    je hr_nobolt
    push eax
    push ebp
    call dword ptr [{SelectObject:#x}]
    mov ax, word ptr [{W_BOLT:#x}]
    mov word ptr [{TXT:#x}], ax
    mov dword ptr [{G_LEN:#x}], 1
    mov ecx, dword ptr [{G_GREF:#x}]
    call draw_text
    push {SIZE:#x}
    push 1
    push {TXT:#x}
    push ebp
    call dword ptr [{GetTextExtentPoint32W:#x}]
    mov eax, dword ptr [{SIZE:#x}]
    add dword ptr [{G_X:#x}], eax
hr_nobolt:
    mov eax, dword ptr [{G_X:#x}]
    add eax, 4
    mov dword ptr [{G_GAUGE_X:#x}], eax
    mov eax, dword ptr [{G_FONT:#x}]      ; the FPS counter draws next with this DC
    test eax, eax
    je hr_done
    push eax
    push ebp
    call dword ptr [{SelectObject:#x}]
hr_done:
    popal
    sub esp, 0x40                         ; as at 0x44506d: the arguments of the last text call
    jmp 0x44506d

hud_icons:                                ; instead of call 0x4042dc at 0x4e0640
    pushal
    cmp dword ptr [{G_ICONS_DONE:#x}], 0
    jne hi_done
    mov dword ptr [{G_ICONS_DONE:#x}], 1
    xor esi, esi
hi_load:
    push {G_TMP:#x}
    push 0
    push dword ptr [esi*4 + {ICON_NAMES:#x}]
    push 0x131                            ; Interface.les
    call 0x45d800
    add esp, 16
    test eax, eax
    je hi_next
    cmp word ptr [eax], 0x4d42            ; "BM", 24 bits per pixel
    jne hi_next
    cmp word ptr [eax + 28], 24
    jne hi_next
    mov dword ptr [esi*4 + {ICONS:#x}], eax
    call unkey_icon
hi_next:
    inc esi
    cmp esi, 6
    jb hi_load
hi_done:
    popal
    jmp 0x4042dc

unkey_icon:                               ; eax = BMP: the game's transparent magenta -> the overlay key (0, 0, 8)
    pushal
    mov ebx, dword ptr [eax + 18]
    lea ebx, [ebx + ebx*2]                ; bytes of pixels per row
    lea ebp, [ebx + 3]
    and ebp, -4                           ; row pitch
    mov edx, dword ptr [eax + 22]         ; rows
    mov edi, dword ptr [eax + 10]
    add edi, eax
uk_row:
    xor ecx, ecx
uk_px:
    cmp word ptr [edi + ecx], 0xff        ; blue ff, green 0
    jne uk_next
    cmp byte ptr [edi + ecx + 2], 0xff    ; red ff
    jne uk_next
    mov word ptr [edi + ecx], 8
    mov byte ptr [edi + ecx + 2], 0
uk_next:
    add ecx, 3
    cmp ecx, ebx
    jb uk_px
    add edi, ebp
    dec edx
    jg uk_row
    popal
    ret

layout:                                   ; font height, icon size and band height from the screen height
    movzx eax, word ptr [{H:#x}]
    imul eax, eax, {FONT_PER_1200}
    xor edx, edx
    mov ecx, 1200
    div ecx
    cmp eax, {FONT_MIN}
    jge ly_min
    mov eax, {FONT_MIN}
ly_min:
    mov dword ptr [{G_FHN:#x}], eax
    shl eax, 2
    xor edx, edx
    mov ecx, 3
    div ecx
    mov dword ptr [{G_ICON:#x}], eax      ; 4/3 of the font height
    add eax, 8
    mov dword ptr [{G_BAR:#x}], eax
    ret

ensure_init:
    cmp dword ptr [{G_INIT:#x}], 0
    jne ei_ret
    mov dword ptr [{G_INIT:#x}], 1
    push {s_at[0]:#x}
    call dword ptr [{GetModuleHandleA:#x}]
    test eax, eax
    je ei_ret
    mov ebx, eax
    push {s_at[1]:#x}
    push ebx
    call dword ptr [{GetProcAddress:#x}]
    mov dword ptr [{P_STRETCHDIB:#x}], eax
    push {s_at[2]:#x}
    push ebx
    call dword ptr [{GetProcAddress:#x}]
    mov dword ptr [{P_SETSTRETCH:#x}], eax
ei_ret:
    ret

ensure_fonts:                             ; (re)make the fonts when the height changed
    mov eax, dword ptr [{G_FHN:#x}]
    cmp eax, dword ptr [{G_FH:#x}]
    je ef_ret
    mov dword ptr [{G_FH:#x}], eax
    mov eax, dword ptr [{G_FONT:#x}]
    test eax, eax
    je ef_sym
    push eax
    call dword ptr [{DeleteObject:#x}]
ef_sym:
    mov eax, dword ptr [{G_FONTSYM:#x}]
    test eax, eax
    je ef_make
    push eax
    call dword ptr [{DeleteObject:#x}]
ef_make:
    mov esi, {s_at[3]:#x}
    mov edi, 600
    mov ebx, 4                            ; ANTIALIASED_QUALITY
    call create_font
    mov dword ptr [{G_FONT:#x}], eax
    mov esi, {s_at[4]:#x}                 ; the sign is thin: anti-aliasing against the overlay key darkens it
    mov edi, 700
    mov ebx, 3                            ; NONANTIALIASED_QUALITY
    call create_font
    mov dword ptr [{G_FONTSYM:#x}], eax
ef_ret:
    ret

create_font:                              ; esi = face, edi = weight, ebx = quality
    push esi
    push 0                                ; DEFAULT_PITCH
    push ebx
    push 0
    push 0
    push 1                                ; DEFAULT_CHARSET
    push 0
    push 0
    push 0
    push edi
    push 0
    push 0
    push 0
    mov eax, dword ptr [{G_FH:#x}]
    neg eax                               ; character height
    push eax
    call dword ptr [{CreateFontA:#x}]
    ret

put_wnum:                                 ; append the decimal digits of eax as UTF-16 at edi
    push ebx
    push ecx
    push edx
    mov ebx, 10
    xor ecx, ecx
pw_div:
    xor edx, edx
    div ebx
    add edx, 0x30
    push edx
    inc ecx
    test eax, eax
    jne pw_div
pw_out:
    pop eax
    mov word ptr [edi], ax
    add edi, 2
    dec ecx
    jne pw_out
    pop edx
    pop ecx
    pop ebx
    ret

draw_text:                                ; TXT (G_LEN chars) at (G_X, G_TEXTY) in colour ecx, with a shadow
    push ecx
    push 0
    push ebp
    call dword ptr [{SetTextColor:#x}]
    push dword ptr [{G_LEN:#x}]
    push {TXT:#x}
    mov eax, dword ptr [{G_TEXTY:#x}]
    inc eax
    push eax
    mov eax, dword ptr [{G_X:#x}]
    inc eax
    push eax
    push ebp
    call dword ptr [{TextOutW:#x}]
    pop ecx
    push ecx
    push ebp
    call dword ptr [{SetTextColor:#x}]
    push dword ptr [{G_LEN:#x}]
    push {TXT:#x}
    push dword ptr [{G_TEXTY:#x}]
    push dword ptr [{G_X:#x}]
    push ebp
    call dword ptr [{TextOutW:#x}]
    ret

draw_icon:                                ; eax = BMP file data: frame 0 scaled to G_ICON at G_X
    cmp dword ptr [{P_STRETCHDIB:#x}], 0
    je di_ret
    push esi
    mov esi, eax
    mov ecx, dword ptr [esi + 18]
    mov edx, dword ptr [esi + 22]
    lea eax, [edx + edx]
    cmp ecx, eax
    jle di_one
    mov eax, ecx                          ; a button strip: normal, highlighted, pressed
    xor edx, edx
    mov ecx, 3
    div ecx
    mov ecx, eax
    mov edx, dword ptr [esi + 22]
di_one:
    push 0xcc0020                         ; SRCCOPY
    push 0                                ; DIB_RGB_COLORS
    lea eax, [esi + 14]
    push eax
    mov eax, dword ptr [esi + 10]
    add eax, esi
    push eax
    push edx
    push ecx
    push 0
    push 0
    mov eax, dword ptr [{G_ICON:#x}]
    push eax
    push eax
    mov ecx, dword ptr [{G_BAR:#x}]
    sub ecx, eax
    sar ecx, 1
    push ecx
    push dword ptr [{G_X:#x}]
    push ebp
    call dword ptr [{P_STRETCHDIB:#x}]
    pop esi
di_ret:
    ret

gauge_value:                              ; G_V = balance (-78..78), G_COLOR (ARGB), G_GREF (COLORREF)
    movzx eax, byte ptr [{PLAYER:#x}]
    fld dword ptr [eax*4 + 0x954034]
    fmul dword ptr [eax*4 + 0x954054]
    fld dword ptr [eax*4 + 0x953ff4]
    fdiv dword ptr [eax*4 + 0x954014]
    fsubp st(1), st(0)
    fadd st(0), st(0)
    fistp dword ptr [{G_V:#x}]
    mov eax, dword ptr [{G_V:#x}]
    cmp eax, 78
    jle gv_hi
    mov eax, 78
gv_hi:
    cmp eax, -78
    jge gv_lo
    mov eax, -78
gv_lo:
    mov dword ptr [{G_V:#x}], eax
    mov ecx, eax
    test ecx, ecx
    jge gv_abs
    neg ecx
gv_abs:
    imul ecx, ecx, 255
    push eax
    mov eax, ecx
    xor edx, edx
    mov ecx, 78
    div ecx
    mov ecx, 255
    sub ecx, eax                          ; 255 - |v| * 255 / 78
    pop eax
    test eax, eax
    js gv_red
    mov eax, ecx                          ; surplus: yellow to green
    shl eax, 16
    or eax, 0xff00ff00
    mov dword ptr [{G_COLOR:#x}], eax
    or ecx, 0xff00
    mov dword ptr [{G_GREF:#x}], ecx
    ret
gv_red:
    mov eax, ecx                          ; deficit: yellow to red
    shl eax, 8
    or eax, 0xffff0000
    mov dword ptr [{G_COLOR:#x}], eax
    shl ecx, 8
    or ecx, 0xff
    mov dword ptr [{G_GREF:#x}], ecx
    ret

put_vert:                                 ; eax -> int x, edx -> int y, ecx = colour; edi = vertex
    fild dword ptr [eax]
    fstp dword ptr [edi]
    fild dword ptr [edx]
    fstp dword ptr [edi + 4]
    mov dword ptr [edi + 8], 0
    mov dword ptr [edi + 12], 0x3f800000
    mov dword ptr [edi + 16], ecx
    add edi, 20
    ret

add_quad:                                 ; (x0, y0, x1, y1, top colour, bottom colour): two triangles
    mov edi, dword ptr [{G_VP:#x}]
    lea eax, [esp + 4]
    lea edx, [esp + 8]
    mov ecx, dword ptr [esp + 0x14]
    call put_vert
    lea eax, [esp + 0xc]
    lea edx, [esp + 8]
    mov ecx, dword ptr [esp + 0x14]
    call put_vert
    lea eax, [esp + 4]
    lea edx, [esp + 0x10]
    mov ecx, dword ptr [esp + 0x18]
    call put_vert
    lea eax, [esp + 0xc]
    lea edx, [esp + 8]
    mov ecx, dword ptr [esp + 0x14]
    call put_vert
    lea eax, [esp + 0xc]
    lea edx, [esp + 0x10]
    mov ecx, dword ptr [esp + 0x18]
    call put_vert
    lea eax, [esp + 4]
    lea edx, [esp + 0x10]
    mov ecx, dword ptr [esp + 0x18]
    call put_vert
    mov dword ptr [{G_VP:#x}], edi
    ret

build_verts:                              ; band, its edge and the gauge; eax = number of vertices
    mov dword ptr [{G_VP:#x}], {VB:#x}
    movzx eax, word ptr [{W:#x}]
    push {BAND_BOTTOM:#x}
    push {BAND_TOP:#x}
    push dword ptr [{G_BAR:#x}]
    push eax
    push 0
    push 0
    call add_quad
    add esp, 24
    movzx eax, word ptr [{W:#x}]
    mov ecx, dword ptr [{G_BAR:#x}]
    lea edx, [ecx + 1]
    push {EDGE:#x}
    push {EDGE:#x}
    push edx
    push eax
    push ecx
    push 0
    call add_quad
    add esp, 24
    mov ebx, dword ptr [{G_GAUGE_X:#x}]
    test ebx, ebx
    je bv_count
    call gauge_value
    mov esi, dword ptr [{G_FHN:#x}]       ; gauge: 6 font heights wide, half a font height high
    imul esi, esi, 6
    mov edi, dword ptr [{G_FHN:#x}]
    shr edi, 1
    mov ecx, dword ptr [{G_BAR:#x}]
    sub ecx, edi
    sar ecx, 1                            ; top
    lea eax, [ecx + edi]                  ; bottom
    lea edx, [ebx + esi]                  ; right
    push ecx
    push eax
    mov eax, 0x90000000
    push eax
    push eax
    push dword ptr [esp + 8]
    push edx
    push dword ptr [esp + 0x14]
    push ebx
    call add_quad
    add esp, 24
    pop eax                               ; bottom
    pop ecx                               ; top
    inc ebx                               ; fill: 1 px inside, (v + 78) / 156 of the inner width
    inc ecx
    dec eax
    push ecx
    push eax
    lea eax, [esi - 2]
    mov edx, dword ptr [{G_V:#x}]
    add edx, 78
    imul eax, edx
    xor edx, edx
    mov ecx, 156
    div ecx
    add eax, ebx                          ; right
    pop edx                               ; bottom
    pop ecx                               ; top
    push dword ptr [{G_COLOR:#x}]
    push dword ptr [{G_COLOR:#x}]
    push edx
    push eax
    push ecx
    push ebx
    call add_quad
    add esp, 24
bv_count:
    mov eax, dword ptr [{G_VP:#x}]
    sub eax, {VB:#x}
    xor edx, edx
    mov ecx, 20
    div ecx
    ret

draw_band:
    cmp dword ptr [{DEVICE:#x}], 0
    je db_ret
    call layout
    call build_verts
    mov dword ptr [{G_NV:#x}], eax
    mov esi, dword ptr [{DEVICE:#x}]
    mov eax, dword ptr [esi]
    push esi
    call dword ptr [eax + 0x14]           ; BeginScene (fails if one is open: then it is not ended here)
    mov dword ptr [{G_SCENE:#x}], eax
    mov dword ptr [{G_TEX:#x}], 0
    push {G_TEX:#x}
    push 0
    push esi
    mov eax, dword ptr [esi]
    call dword ptr [eax + 0x88]           ; GetTexture(0)
    push 0
    push 0
    push esi
    mov eax, dword ptr [esi]
    call dword ptr [eax + 0x8c]           ; SetTexture(0, NULL)
    xor ebx, ebx
db_rs:
    lea eax, [ebx*4 + {SAVED_RS:#x}]
    push eax
    push dword ptr [ebx*8 + {RS_TABLE:#x}]
    push esi
    mov eax, dword ptr [esi]
    call dword ptr [eax + 0x54]           ; GetRenderState
    push dword ptr [ebx*8 + {RS_TABLE + 4:#x}]
    push dword ptr [ebx*8 + {RS_TABLE:#x}]
    push esi
    mov eax, dword ptr [esi]
    call dword ptr [eax + 0x50]           ; SetRenderState
    inc ebx
    cmp ebx, {len(RS)}
    jb db_rs
    xor ebx, ebx
db_ts:
    imul edi, ebx, 12
    lea eax, [ebx*4 + {SAVED_TSS:#x}]
    push eax
    push dword ptr [edi + {TSS_TABLE + 4:#x}]
    push dword ptr [edi + {TSS_TABLE:#x}]
    push esi
    mov eax, dword ptr [esi]
    call dword ptr [eax + 0x90]           ; GetTextureStageState
    push dword ptr [edi + {TSS_TABLE + 8:#x}]
    push dword ptr [edi + {TSS_TABLE + 4:#x}]
    push dword ptr [edi + {TSS_TABLE:#x}]
    push esi
    mov eax, dword ptr [esi]
    call dword ptr [eax + 0x94]           ; SetTextureStageState
    inc ebx
    cmp ebx, {len(TSS)}
    jb db_ts
    push 1                                ; D3DDP_WAIT
    push dword ptr [{G_NV:#x}]
    push {VB:#x}
    push 0x44                             ; D3DFVF_XYZRHW | D3DFVF_DIFFUSE
    push 4                                ; D3DPT_TRIANGLELIST
    push esi
    mov eax, dword ptr [esi]
    call dword ptr [eax + 0x64]           ; DrawPrimitive
    mov ebx, {len(TSS)}
db_ts_back:
    dec ebx
    imul edi, ebx, 12
    push dword ptr [ebx*4 + {SAVED_TSS:#x}]
    push dword ptr [edi + {TSS_TABLE + 4:#x}]
    push dword ptr [edi + {TSS_TABLE:#x}]
    push esi
    mov eax, dword ptr [esi]
    call dword ptr [eax + 0x94]
    test ebx, ebx
    jne db_ts_back
    mov ebx, {len(RS)}
db_rs_back:
    dec ebx
    push dword ptr [ebx*4 + {SAVED_RS:#x}]
    push dword ptr [ebx*8 + {RS_TABLE:#x}]
    push esi
    mov eax, dword ptr [esi]
    call dword ptr [eax + 0x50]
    test ebx, ebx
    jne db_rs_back
    push dword ptr [{G_TEX:#x}]
    push 0
    push esi
    mov eax, dword ptr [esi]
    call dword ptr [eax + 0x8c]           ; SetTexture(0, the game's)
    mov eax, dword ptr [{G_TEX:#x}]
    test eax, eax
    je db_scene
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 8]              ; Release (GetTexture added a reference)
db_scene:
    cmp dword ptr [{G_SCENE:#x}], 0
    jne db_ret
    push esi
    mov eax, dword ptr [esi]
    call dword ptr [eax + 0x18]           ; EndScene
db_ret:
    ret

labels:
    .long hud_frame, hud_res, hud_icons
'''

ks = Ks(KS_ARCH_X86, KS_MODE_32)
code = bytes(ks.asm('\n'.join(l.split(';')[0] for l in asm.splitlines()), CODE)[0])
hud_frame, hud_res, hud_icons = struct.unpack('<3I', code[-12:])
code = code[:-12]
assert CODE + len(code) <= DATA, f'code too large: {len(code)} bytes'

init = bytearray(DATA_END - DATA)
for i, (st, v) in enumerate(RS):
    struct.pack_into('<2I', init, RS_TABLE - DATA + 8 * i, st, v)
for i, t in enumerate(TSS):
    struct.pack_into('<3I', init, TSS_TABLE - DATA + 12 * i, *t)
struct.pack_into('<5I', init, VAL_OFF - DATA, *VALUES)
struct.pack_into('<6I', init, ICON_NAMES - DATA, *NAMES)
for at, x in zip(s_at, STRINGS):
    init[at - DATA:at - DATA + len(x)] = x
init[W_ZEROS - DATA:W_ZEROS - DATA + 10] = '00000'.encode('utf-16le')
init[W_BOLT - DATA:W_BOLT - DATA + 2] = '⚡'.encode('utf-16le')

data[off(CODE):off(CODE) + len(code)] = code
data[off(DATA):off(DATA_END)] = init
data[off(0x42b4ee):off(0x42b4ee) + 5] = call(0x42b4ee, hud_frame)
data[off(0x444e41):off(0x444e41) + 5] = jmp(0x444e41, hud_res)
data[off(0x4e0640):off(0x4e0640) + 5] = call(0x4e0640, hud_icons)
for va, _ in BEVEL_BLTS + THERMOMETER:            # call [reg + n] -> add esp, 0x18 (the 6 pushed arguments)
    data[off(va):off(va) + 3] = bytes.fromhex('83c418')

# fps_counter.py: its text on the band (x W - 280 for the larger font, y 4), without the black box
fps_mode = bytes.fromhex('6a0255ff1580879c00')    # push 2 (OPAQUE); push ebp; call [SetBkMode]
fps_pos = bytes.fromhex('6a185655ff1584879c00')   # push 24 (y); push esi; push ebp; call [TextOutA]
fps_x = bytes.fromhex('0fb7354ee25a0081eec8000000')   # movzx esi, word [W]; sub esi, 200 (x)
for pat, at, new in ((fps_mode, 1, b'\x01'), (fps_pos, 1, b'\x04'), (fps_x, 9, struct.pack('<I', 280))):
    i = data.find(pat)
    assert i > 0 and data.find(pat, i + 1) < 0, pat.hex()
    data[i + at:i + at + len(new)] = new

dd = pe.OPTIONAL_HEADER.get_file_offset() + 96 + 8 * 5   # the base relocation directory: none
struct.pack_into('<2I', data, dd, 0, 0)
fh = max(FONT_MIN, FONT_PER_1200)                 # the message goes below the band of 1920x1200 (the tallest)
data[off(0x4450c7) + 1] = fh * 4 // 3 + 8 + 6
open(dst, 'wb').write(data)
print(f'code {len(code)} bytes at {CODE:#x}, data {DATA:#x}-{DATA_END:#x}')
