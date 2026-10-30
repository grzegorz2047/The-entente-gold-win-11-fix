"""Modern HUD for The Entente (improvements): no screen frame, a semi-transparent top bar.

Applied in the improvements chain after terrain_strip.py (prefetch.py follows). usage: python modern_hud.py IN.exe OUT.exe

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
- The minimap is N x N instead of 200 x 200, N = 5/32 of the mission mode's width (300 in 1920x1200,
  at least 200; the minimap is made while the loading screen still runs in the menu mode): the
  surface size (0x43dfe6), its position (200 + 13 from the screen edge), the map tiles per pixel
  (0.005 * map size, 6 functions) and the locked rectangle follow N; the generation writes rows with
  the surface pitch and takes whole map rows (W * y * fy with a fractional fy mixed rows); the fog of
  war keeps its 200 x 200 grid (0x978a00, overlay [0x982c70], 200 / map size at [0x9536f8]): the overlay
  is stretched over the minimap, generation and the visibility test 0x464190 convert to that grid.
  The saved game preview (0x43faa0) stays 200 x 200, so saves stay compatible. Units are 2 x 2 dots
  from N = 300. The six buttons above it (rectangles of 0x4e1df0, BltFast in 0x4e11c0) are scaled
  by N / 200 with Blt, and the minimap area of 0x4cd4b0 follows. Its wooden frame (MiniMapBevelLeft,
  MiniMapBevelUp) is replaced by a semi-transparent panel drawn before the minimap (0x42b4e9).
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
MM_BEVELS = [(0x43e919, 'ff511c'), (0x43e985, 'ff511c'), (0x43e9b8, 'ff511c')]   # minimap frame: button strip, left
for va, hexbytes in BEVEL_BLTS + THERMOMETER + MM_BEVELS:
    expect(va, hexbytes)

RELOC_VA, RELOC_SIZE = 0x9cb000, 0x12bc0          # the relocation table of the Steam exe
CODE = RELOC_VA
CODE_END = RELOC_VA + RELOC_SIZE - 0x100          # mode_redraw.py uses the last 0x100 bytes
assert pe.OPTIONAL_HEADER.DllCharacteristics & 0x40 == 0, 'relocations needed'
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
(MM_N, MM_N13, MM_NF, MM_INV, MM_PW, MM_F200X, MM_F200Y, K200, K160) = (DATA + 0x500 + 4 * i for i in range(9))
MM_RECT = DATA + 0x530                             # RECT of the stretched fog overlay
MM_UITOP, MM_PANEL = DATA + 0x540, DATA + 0x544    # minimap area and panel above the map (scaled 0x2c, 0x24 + 4)
BTN_RECT = DATA + 0x550                            # destination of a stretched minimap button
BTN_RECTS = 0x9b0c58                               # the 6 button rectangles of 0x4e1df0
FOG_SURFACE, BACK = 0x982c70, 0x5ae258
MISSION_SLOT, HUD_SCALE = 0x5ae245, 0x595e14     # mode of the mission; W / 1024 per mode (build_patched_exe.py)
VB = DATA + 0x560                                 # up to 48 vertices of 20 bytes
BEVEL_VT = VB + 48 * 20                           # vtable of the selection panel's bevels: 0x57fda0 without drawing
G_COMP, G_RET = BEVEL_VT + 6 * 4, BEVEL_VT + 7 * 4   # system memory surface the minimap is composed on
DATA_END = BEVEL_VT + 8 * 4
MINIMAP = 0x953704                                # the minimap's terrain picture (system memory, N x N)
SELECTION = 0x9a6334                              # window of the selection panel (bottom left) or 0
BITMAP_WND_VT = [0x4013e8, 0x401e01, 0x401fdc, 0x401d8e]   # window showing a bitmap (draw +0xc: 0x4f7f70)
# the bevels (TBevel, RBevel, LBevel, BBevel.bmp, used only there) of the selection panel's two layouts
SEL_BEVELS = [(0x4cfdac, 'c706'), (0x4cfe0b, 'c706'), (0x4cfe6f, 'c745'), (0x4cfec7, 'c706'), (0x4cff2d, 'c706'),
              (0x4d01f9, 'c745'), (0x4d025f, 'c707'), (0x4d02b2, 'c706')]
MM_X, MM_Y, MM_FX, MM_FY = 0x9536ea, 0x9536e8, 0x9536f0, 0x9536ec   # minimap position (words), map tiles per pixel
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
draw_vb:                                  ; draw the G_NV vertices in VB (the caller checked the device)
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

; ---- minimap: N x N instead of 200 x 200, on a semi-transparent panel ----
mm_frame:                                 ; instead of call 0x43e8d0 (minimap) at 0x42b4e9
    pushal
    cmp dword ptr [{DEVICE:#x}], 0
    je mf_done
    mov dword ptr [{G_VP:#x}], {VB:#x}
    movzx esi, word ptr [{MM_X:#x}]
    sub esi, 10                           ; panel left: the button row starts 7 px left of the map
    movzx ebp, word ptr [{MM_Y:#x}]
    sub ebp, dword ptr [{MM_PANEL:#x}]    ; panel top: above the button row
    movzx eax, word ptr [{W:#x}]
    movzx ebx, word ptr [{H:#x}]
    push {BAND_BOTTOM:#x}
    push {BAND_TOP:#x}
    push ebx
    push eax
    push ebp
    push esi
    call add_quad
    add esp, 24
    movzx eax, word ptr [{W:#x}]
    lea edx, [ebp + 1]
    push {EDGE:#x}
    push {EDGE:#x}
    push edx
    push eax
    push ebp
    push esi
    call add_quad                         ; light top edge
    add esp, 24
    movzx ebx, word ptr [{H:#x}]
    lea edx, [esi + 1]
    push {EDGE:#x}
    push {EDGE:#x}
    push ebx
    push edx
    push ebp
    push esi
    call add_quad                         ; light left edge
    add esp, 24
    mov dword ptr [{G_NV:#x}], 18
    mov eax, dword ptr [{SELECTION:#x}]   ; the same panel under the selection panel, if one is shown
    test eax, eax
    je mf_draw
    cmp byte ptr [eax + 0x1a], 0
    je mf_draw
    movsx esi, word ptr [eax + 0x20]
    movsx edx, word ptr [eax + 0x24]
    lea esi, [esi + edx + 6]              ; right
    movsx ebp, word ptr [eax + 0x22]
    sub ebp, 6                            ; top
    movzx ebx, word ptr [{H:#x}]
    push {BAND_BOTTOM:#x}
    push {BAND_TOP:#x}
    push ebx
    push esi
    push ebp
    push 0
    call add_quad
    add esp, 24
    lea edx, [ebp + 1]
    push {EDGE:#x}
    push {EDGE:#x}
    push edx
    push esi
    push ebp
    push 0
    call add_quad                         ; light top edge
    add esp, 24
    lea edx, [esi - 1]
    push {EDGE:#x}
    push {EDGE:#x}
    push ebx
    push esi
    push ebp
    push edx
    call add_quad                         ; light right edge
    add esp, 24
    add dword ptr [{G_NV:#x}], 18
mf_draw:
    call draw_vb
mf_done:
    popal
    jmp 0x4026cb

mm_compute:                               ; N = W * 5 / 32 of the mission mode (a multiple of 4, at least 200)
    movzx eax, byte ptr [{MISSION_SLOT:#x}]   ; the minimap is made while the loading screen is still shown
    fld dword ptr [eax*4 + {HUD_SCALE:#x}]    ; W / 1024 of that mode
    fmul dword ptr [{K160:#x}]
    fistp dword ptr [{MM_N:#x}]
    mov eax, dword ptr [{MM_N:#x}]
    and eax, -4
    cmp eax, 200
    jge mc_min
    mov eax, 200
mc_min:
    mov dword ptr [{MM_N:#x}], eax
    add eax, 13
    mov dword ptr [{MM_N13:#x}], eax
    fild dword ptr [{MM_N:#x}]
    fstp dword ptr [{MM_NF:#x}]
    fld1
    fidiv dword ptr [{MM_N:#x}]
    fstp dword ptr [{MM_INV:#x}]
    mov eax, dword ptr [{MM_N:#x}]        ; heights above the map, scaled: the minimap area, the panel
    imul eax, eax, 0x2c
    cdq
    idiv dword ptr [{K200:#x}]
    mov dword ptr [{MM_UITOP:#x}], eax
    mov eax, dword ptr [{MM_N:#x}]
    imul eax, eax, 0x24
    cdq
    idiv dword ptr [{K200:#x}]
    add eax, 4
    mov dword ptr [{MM_PANEL:#x}], eax
    ret

mm_create:                                ; instead of push 200; push 200 (size of the minimap surface)
    push eax
    push ecx
    call mm_compute
    pop ecx
    pop eax
    sub esp, 8
    push eax
    mov eax, dword ptr [esp + 12]         ; move the return address down, the size above it twice
    mov dword ptr [esp + 4], eax
    mov eax, dword ptr [{MM_N:#x}]
    mov dword ptr [esp + 8], eax
    mov dword ptr [esp + 12], eax
    pop eax
    ret

mm_y_ax:                                  ; instead of sub ax, 0xd5 (200 + 13 from the edge); mov [y], ax
    sub ax, word ptr [{MM_N13:#x}]
    mov word ptr [{MM_Y:#x}], ax
    ret
mm_sub_cx:                                ; instead of sub cx, 0xd5
    sub cx, word ptr [{MM_N13:#x}]
    ret
mm_sub_dx:                                ; instead of sub dx, 0xd5
    sub dx, word ptr [{MM_N13:#x}]
    ret
mm_add_eax:                               ; instead of add eax, 200 (the locked rectangle)
    add eax, dword ptr [{MM_N:#x}]
    ret

mm_pitch:                                 ; after the minimap surface is locked: its pitch in pixels
    mov eax, dword ptr [esp + 0x60]       ; DDSURFACEDESC2.lPitch
    shr eax, 1
    mov dword ptr [{MM_PW:#x}], eax
    mov edi, dword ptr [esp + 0x74]       ; the replaced mov edi, [esp + 0x70] (lpSurface)
    pop ecx
    push 0xff                             ; the replaced push
    jmp ecx

mm_row:                                   ; ebp = row eax * pitch (was eax * 25, used * 8)
    mov ebp, eax
    imul ebp, dword ptr [{MM_PW:#x}]
    ret

mm_preview:                               ; the saved game preview stays 200 x 200: its own scale
    fild dword ptr [{MM_N:#x}]
    fidiv dword ptr [{K200:#x}]
    fld st(0)
    fmul dword ptr [{MM_FX:#x}]
    fstp dword ptr [{MM_F200X:#x}]
    fmul dword ptr [{MM_FY:#x}]
    fstp dword ptr [{MM_F200Y:#x}]
    pop eax
    sub esp, 0xac                         ; the replaced instruction
    jmp eax

mm_index:                                 ; map tile under minimap pixel x [esp+0x2c], y [esp+0x44] (float)
    fld dword ptr [esp + 0x48]            ; the game added W * y * fy + x * fx: with a fractional fy
    fmul dword ptr [{MM_FY:#x}]           ; (N not dividing the map) rows mix; whole rows instead
    call {FTOL:#x}
    movzx ecx, word ptr [0x8be392]
    imul eax, ecx
    push eax
    fild dword ptr [esp + 0x34]
    fmul dword ptr [{MM_FX:#x}]
    call {FTOL:#x}
    pop ecx
    add eax, ecx
    ret

mm_fog:                                   ; fog test of minimap pixel (esi, [esp+0x24]): its grid is 200 x 200
    mov eax, dword ptr [esp + 0x28]
    imul eax, eax, 200
    xor edx, edx
    div dword ptr [{MM_N:#x}]
    push eax
    mov eax, esi
    imul eax, eax, 200
    xor edx, edx
    div dword ptr [{MM_N:#x}]
    push eax
    mov ecx, dword ptr [0x984d24]
    call 0x402a18
    ret

mm_fog_blit:                              ; the fog overlay (200 x 200) stretched over the N x N minimap
    movzx eax, word ptr [{MM_X:#x}]
    mov dword ptr [{MM_RECT:#x}], eax
    add eax, dword ptr [{MM_N:#x}]
    mov dword ptr [{MM_RECT + 8:#x}], eax
    movzx eax, word ptr [{MM_Y:#x}]
    mov dword ptr [{MM_RECT + 4:#x}], eax
    add eax, dword ptr [{MM_N:#x}]
    mov dword ptr [{MM_RECT + 12:#x}], eax
    mov eax, dword ptr [{BACK:#x}]
    mov ecx, dword ptr [{G_COMP:#x}]      ; onto the composed minimap instead, if there is one
    test ecx, ecx
    je fb_blt
    mov eax, ecx
    xor ecx, ecx
    mov dword ptr [{MM_RECT:#x}], ecx
    mov dword ptr [{MM_RECT + 4:#x}], ecx
    mov ecx, dword ptr [{MM_N:#x}]
    mov dword ptr [{MM_RECT + 8:#x}], ecx
    mov dword ptr [{MM_RECT + 12:#x}], ecx
fb_blt:
    push 0
    push 0x1008000                        ; DDBLT_KEYSRC | DDBLT_WAIT
    push 0
    push dword ptr [{FOG_SURFACE:#x}]
    push {MM_RECT:#x}
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x14]           ; Blt
    ret

; The game draws the minimap each frame straight into the back buffer: a BltFast of the terrain picture,
; then two Locks of the back buffer for the unit dots and the markers. Under dgVoodoo the first write to
; each page of a locked back buffer waits for the GPU and reads the surface back: over a town with many
; units that took several ms per frame, more when the terrain was redrawn. The minimap is now composed on
; a system memory surface and put on the back buffer with one BltFast.
mm_comp_create:                           ; instead of mov [0x953704], eax (the minimap surface was created)
    pushfd
    pushal
    mov dword ptr [{MINIMAP:#x}], eax
    mov eax, dword ptr [{G_COMP:#x}]
    test eax, eax
    je cc_new
    mov dword ptr [{G_COMP:#x}], 0
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 8]              ; Release the previous one
cc_new:
    push 1                                ; system memory
    push 0                                ; colour key
    push dword ptr [{MM_N:#x}]
    push dword ptr [{MM_N:#x}]
    call 0x401668                         ; as the game makes the minimap surface
    add esp, 16
    mov dword ptr [{G_COMP:#x}], eax
    popal
    popfd
    ret

mm_c_base:                                ; instead of push edx; push eax; call [ecx + 0x1c]: the terrain picture
    pop dword ptr [{G_RET:#x}]            ; at (edx, [esp]) of the back buffer eax
    mov ecx, dword ptr [{G_COMP:#x}]
    test ecx, ecx
    je cb_go
    mov eax, ecx                          ; at (0, 0) of the composed minimap
    xor edx, edx
    mov dword ptr [esp], edx
cb_go:
    push edx
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x1c]           ; BltFast
    jmp dword ptr [{G_RET:#x}]

mm_c_lock_edx:                            ; instead of push edx; push eax; call [ecx + 0x64]
    mov ecx, edx
mm_c_lock:                                ; instead of push ecx; push eax; call [edx + 0x64]: Lock of rect ecx
    pop dword ptr [{G_RET:#x}]            ; of the back buffer eax
    mov edx, dword ptr [{G_COMP:#x}]
    test edx, edx
    je cl_go
    mov eax, edx                          ; the whole composed minimap: the same offsets from lpSurface
    xor ecx, ecx
cl_go:
    push ecx
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x64]
    jmp dword ptr [{G_RET:#x}]

mm_c_unlock_edx:                          ; instead of push edx; push eax; mov ecx, [eax]; call [ecx + 0x80]
    mov ecx, edx
mm_c_unlock:                              ; instead of push ecx; push eax; mov edx, [eax]; call [edx + 0x80]
    mov edx, dword ptr [{G_COMP:#x}]
    test edx, edx
    je cu_go
    mov eax, edx
    xor ecx, ecx
cu_go:
    push ecx
    push eax
    mov edx, dword ptr [eax]
    call dword ptr [edx + 0x80]           ; Unlock
    ret

mm_c_unlock_show_edx:                     ; the last Unlock of the minimap (or the one after a failed Lock):
    mov ecx, edx                          ; then the composed minimap goes on the back buffer
mm_c_unlock_show:
    call mm_c_unlock
    push eax
    mov eax, dword ptr [{G_COMP:#x}]
    test eax, eax
    je cs_done
    cmp dword ptr [{MINIMAP:#x}], 0
    je cs_done
    push 0x10                             ; DDBLTFAST_WAIT
    push 0
    push eax
    movzx eax, word ptr [{MM_Y:#x}]
    push eax
    movzx eax, word ptr [{MM_X:#x}]
    push eax
    mov eax, dword ptr [{BACK:#x}]
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x1c]           ; BltFast
cs_done:
    pop eax
    ret

mm_div_fy200:                             ; st0 / (fy * N / 200) = map y * 200 / map size: row on the 200 x 200
    fdiv dword ptr [{MM_FY:#x}]           ; fog grid (fy = map size / N)
    fimul dword ptr [{K200:#x}]
    fdiv dword ptr [{MM_NF:#x}]
    ret
mm_div_fx200:
    fdiv dword ptr [{MM_FX:#x}]
    fimul dword ptr [{K200:#x}]
    fdiv dword ptr [{MM_NF:#x}]
    ret

mm_btn_scale:                             ; end of 0x4e1df0 (button rectangles): scale them by N / 200 from the
    mov dword ptr [0x9b0c74], eax         ; minimap corner (the replaced instruction)
    pushal
    movzx ebx, word ptr [{MM_X:#x}]
    movzx ebp, word ptr [{MM_Y:#x}]
    xor edi, edi
bs_next:
    mov ecx, ebx                          ; left, top, right, bottom: x, y, x, y
    test edi, 1
    je bs_x
    mov ecx, ebp
bs_x:
    mov eax, dword ptr [edi*4 + {BTN_RECTS:#x}]
    sub eax, ecx
    imul eax, dword ptr [{MM_N:#x}]
    cdq
    idiv dword ptr [{K200:#x}]
    add eax, ecx
    mov dword ptr [edi*4 + {BTN_RECTS:#x}], eax
    inc edi
    cmp edi, 24
    jb bs_next
    popal
    pop esi
    ret

mm_btn_blt_a:                             ; instead of push edx (x); push eax (surface); call [ecx + 0x1c] (BltFast)
    push edx
    push eax
    jmp btn_blt
mm_btn_blt_b:                             ; instead of push eax (x); push ecx (surface); call [edx + 0x1c]
    push eax
    push ecx
btn_blt:                                  ; a minimap button stretched by N / 200 with Blt
    pushal                                ; [esp+0x20] surface, +0x24 x, +0x2c y, +0x30 source, +0x34 its RECT
    mov esi, dword ptr [esp + 0x34]
    mov eax, dword ptr [esi + 8]
    sub eax, dword ptr [esi]
    imul eax, dword ptr [{MM_N:#x}]
    cdq
    idiv dword ptr [{K200:#x}]
    mov ecx, dword ptr [esp + 0x24]
    mov dword ptr [{BTN_RECT:#x}], ecx
    add eax, ecx
    mov dword ptr [{BTN_RECT + 8:#x}], eax
    mov eax, dword ptr [esi + 12]
    sub eax, dword ptr [esi + 4]
    imul eax, dword ptr [{MM_N:#x}]
    cdq
    idiv dword ptr [{K200:#x}]
    mov ecx, dword ptr [esp + 0x2c]
    mov dword ptr [{BTN_RECT + 4:#x}], ecx
    add eax, ecx
    mov dword ptr [{BTN_RECT + 12:#x}], eax
    push 0
    push 0x1000000                        ; DDBLT_WAIT (the buttons are opaque: BltFast flags 0x10)
    push esi
    push dword ptr [esp + 0x3c]
    push {BTN_RECT:#x}
    mov eax, dword ptr [esp + 0x34]
    push eax
    mov ecx, dword ptr [eax]
    call dword ptr [ecx + 0x14]
    mov dword ptr [esp + 0x1c], eax
    popal
    add esp, 8
    ret 16

mm_ui_top:                                ; top of the minimap area for 0x4cd4b0 (was my - 0x2c)
    movzx edx, word ptr [{MM_Y:#x}]
    sub edx, dword ptr [{MM_UITOP:#x}]
    ret

mm_dot:                                   ; a unit on the minimap: 2 x 2 pixels when N >= 300
    mov word ptr [ecx + ebp*2], di
    cmp dword ptr [{MM_N:#x}], 300
    jb md_done
    lea eax, [ecx + ebp*2]
    mov word ptr [eax + 2], di
    mov word ptr [eax + ebx*2], di
    mov word ptr [eax + ebx*2 + 2], di
md_done:
    mov ecx, dword ptr [esp + 0x14]       ; the replaced mov ecx, [esp + 0x10]
    ret

bevel_nodraw:                             ; draw method of the selection panel's bevels: the panel has its own edges
    ret

labels:
    .long hud_frame, hud_res, hud_icons, mm_frame, mm_create, mm_y_ax, mm_sub_cx, mm_sub_dx, mm_add_eax
    .long mm_pitch, mm_row, mm_preview, mm_dot, mm_index, mm_fog, mm_fog_blit, mm_div_fy200, mm_div_fx200
    .long mm_btn_scale, mm_btn_blt_a, mm_btn_blt_b, mm_ui_top, bevel_nodraw
    .long mm_comp_create, mm_c_base, mm_c_lock_edx, mm_c_lock, mm_c_unlock, mm_c_unlock_show_edx, mm_c_unlock_show
'''

ks = Ks(KS_ARCH_X86, KS_MODE_32)
code = bytes(ks.asm('\n'.join(l.split(';')[0] for l in asm.splitlines()), CODE)[0])
N_LABELS = 30
(hud_frame, hud_res, hud_icons, mm_frame, mm_create, mm_y_ax, mm_sub_cx, mm_sub_dx, mm_add_eax, mm_pitch,
 mm_row, mm_preview, mm_dot, mm_index, mm_fog, mm_fog_blit, mm_div_fy200, mm_div_fx200, mm_btn_scale, mm_btn_blt_a, mm_btn_blt_b, mm_ui_top,
 bevel_nodraw, mm_comp_create, mm_c_base, mm_c_lock_edx, mm_c_lock, mm_c_unlock, mm_c_unlock_show_edx,
 mm_c_unlock_show) = struct.unpack(f'<{N_LABELS}I', code[-4 * N_LABELS:])
code = code[:-4 * N_LABELS]
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
struct.pack_into('<2I2fI2fIf', init, MM_N - DATA, 300, 313, 300.0, 1 / 300, 300, 0.0, 0.0, 200, 160.0)
struct.pack_into('<2I', init, MM_UITOP - DATA, 0x2c * 300 // 200, 0x24 * 300 // 200 + 4)   # as for 1920x1200
init[W_BOLT - DATA:W_BOLT - DATA + 2] ='⚡'.encode('utf-16le')
struct.pack_into('<4I', init, BEVEL_VT - DATA, *BITMAP_WND_VT[:3], bevel_nodraw)

data[off(CODE):off(CODE) + len(code)] = code
data[off(DATA):off(DATA_END)] = init
data[off(0x42b4ee):off(0x42b4ee) + 5] = call(0x42b4ee, hud_frame)
data[off(0x444e41):off(0x444e41) + 5] = jmp(0x444e41, hud_res)
data[off(0x4e0640):off(0x4e0640) + 5] = call(0x4e0640, hud_icons)
for va, _ in BEVEL_BLTS + THERMOMETER + MM_BEVELS:   # call [reg + n] -> add esp, 0x18 (the 6 pushed arguments)
    data[off(va):off(va) + 3] = bytes.fromhex('83c418')

# minimap N x N: its size, position and scale wherever the game derives them from 200
def put(va, old_hex, new):
    expect(va, old_hex)
    new = new + b'\x90' * (len(bytes.fromhex(old_hex)) - len(new))
    data[off(va):off(va) + len(new)] = new
put(0x42b4e9, call(0x42b4e9, 0x4026cb).hex(), call(0x42b4e9, mm_frame))
put(0x43dfe6, '68c800000068c8000000', call(0x43dfe6, mm_create))           # CreateMiniMap: surface size
for va in (0x4352fc, 0x43530e, 0x43e058, 0x43e08e, 0x43f682, 0x43f6a2, 0x4459cf, 0x4459df, 0x478175, 0x478188,
           0x47c654, 0x47c666):                                            # fmul [0.005]: map size -> per pixel
    put(va, 'd80dec' + 'f15700', b'\xd8\x0d' + struct.pack('<I', MM_INV))
# the fog of war stays 200 x 200 (0x978a00, overlay [0x982c70], 200 / tiles at [0x9536f8], [0x9536f4]):
# its overlay is stretched over the minimap and the visibility test 0x464190 gets the 200 scale
put(0x43eb8b, '8b0d702c98006a01a158e25a006a00518b0de83695008b1081e1ffff00005133c9668b0dea3695005150ff521c',
    call(0x43eb8b, mm_fog_blit))
# the buttons above the minimap: rectangles and pictures scaled by N / 200
put(0x4e1ebe, 'a3740c9b005ec3', jmp(0x4e1ebe, mm_btn_scale))
for va in (0x4e1548, 0x4e16c2, 0x4e17e3, 0x4e1963):
    put(va, '5250ff511c', call(va, mm_btn_blt_a))
for va in (0x4e1a88, 0x4e1b6c):
    put(va, '5051ff521c', call(va, mm_btn_blt_b))
put(0x4cd4e1, '33d2668b15e836950083ea2c', call(0x4cd4e1, mm_ui_top))      # cursor over the minimap area
put(0x464209, 'd835ec369500', call(0x464209, mm_div_fy200))
put(0x46422f, 'd835f0369500', call(0x46422f, mm_div_fx200))
for va, reg, stub in ((0x43e06c, 'e9', mm_sub_cx), (0x43e071, 'ea', mm_sub_dx), (0x43f69d, 'ea', mm_sub_dx)):
    put(va, '6681' + reg + 'd500', call(va, stub))                       # sub r16, 0xd5: position
for va in (0x43f6cd, 0x43e28d):                                            # sub ax, 0xd5; mov [y], ax
    put(va, '662dd50066a3e8369500', call(va, mm_y_ax))
put(0x43e374, 'b8c8000000', b'\xa1' + struct.pack('<I', MM_N))           # full redraw: width and height
put(0x43e474, '8b7c247068ff000000', call(0x43e474, mm_pitch))             # after Lock: the pitch
put(0x43e4de, '33c066a192e38b0089442410db442410d84c2444d80dec369500db44242cd80df0369500dec1e8f7d81100',
    call(0x43e4de, mm_index))                                               # pixel -> map tile
put(0x43e58a, '8b4424248b0d244d98005056e87d44fcff', call(0x43e58a, mm_fog))   # fog of war (200 x 200 grid)
put(0x43e4b5, '8d34b68b44241c8d34b6c1e603', b'\x0f\xaf\x35' + struct.pack('<I', MM_PW) + bytes.fromhex('8b44241c'))
put(0x43e719, '81c7c8000000', b'\x03\x3d' + struct.pack('<I', MM_PW))    # next row
put(0x43e766, '8d04808d2c80', call(0x43e766, mm_row))                     # markers: row
put(0x43e777, '8d0ce8', bytes.fromhex('8d0c28'))
put(0x43e9e0, '05c8000000', call(0x43e9e0, mm_add_eax))                   # per frame: the locked rectangle
put(0x43e9f8, '81c1c8000000', b'\x03\x0d' + struct.pack('<I', MM_N))
put(0x43eb3d, '66893c698b4c2410', call(0x43eb3d, mm_dot))                 # unit dots
put(0x43faa0, '81ecac000000', call(0x43faa0, mm_preview))                 # saved game preview: 200 x 200
for va, old, new in ((0x43fb41, MM_FY, MM_F200Y), (0x43fb4b, MM_FX, MM_F200X)):
    put(va, 'd80d' + struct.pack('<I', old).hex(), b'\xd8\x0d' + struct.pack('<I', new))
for va, old, new in ((0x43fd56, MM_FY, MM_F200Y), (0x43fd6b, MM_FX, MM_F200X)):
    put(va, 'd835' + struct.pack('<I', old).hex(), b'\xd8\x35' + struct.pack('<I', new))

# the minimap is composed on a system memory surface (see mm_comp_create)
put(0x43dffa, 'a304379500', call(0x43dffa, mm_comp_create))
put(0x43e950, '5250ff511c', call(0x43e950, mm_c_base))
put(0x43ea11, '5250ff5164', call(0x43ea11, mm_c_lock_edx))
put(0x43ebcc, '5150ff5264', call(0x43ebcc, mm_c_lock))
put(0x43ea35, '52508b08ff9180000000', call(0x43ea35, mm_c_unlock_show_edx))
put(0x43eb6f, '51508b10ff9280000000', call(0x43eb6f, mm_c_unlock))
put(0x43f00d, '51508b10ff9280000000', call(0x43f00d, mm_c_unlock_show))
# the selection panel lies on the minimap's kind of panel (mm_frame): its bevels are not drawn
expect(0x57fda0, struct.pack('<4I', *BITMAP_WND_VT).hex())
for va, op in SEL_BEVELS:
    put(va, op + ('00' if op == 'c745' else '') + 'a0fd5700',
        bytes.fromhex(op) + (b'\0' if op == 'c745' else b'') + struct.pack('<I', BEVEL_VT))

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
