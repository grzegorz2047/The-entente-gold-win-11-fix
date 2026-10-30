"""On-screen frame counter for The Entente: "FPS nn  max nn ms" under the top bar, right side.

Applied on top of smooth60.py output. usage: python fps_counter.py IN.exe OUT.exe

- 0x42b8ce (every presented map frame, right before Flip) counts frames and the longest frame time
  with QueryPerformanceCounter; once per second the values shown are updated.
- 0x44506d (the resource bar still holds the back buffer DC from GetDC, right before ReleaseDC)
  prints the text with that DC, so no extra GetDC / GPU synchronisation is needed.
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

# 0x42b8ce: cmp byte ptr [0x5ae260], 1 before Flip, or a call placed there by text_overlay.py that
# performs the same cmp; in that case the frame hook chains to it.
site = bytes(data[off(0x42b8ce):off(0x42b8ce) + 7])
if site == bytes.fromhex('803d60e25a0001'):
    FRAME_TAIL = '    cmp byte ptr [0x5ae260], 1\n    ret'
elif site[0] == 0xe8 and site[5:] == b'\x90\x90':
    FRAME_TAIL = f'    jmp {0x42b8ce + 5 + struct.unpack("<i", site[1:5])[0]:#x}'
else:
    sys.exit(f'unexpected bytes at 0x42b8ce: {site.hex()}')
expect(0x44506d, 'a158e25a008b4c2440')             # mov eax,[backbuffer] / mov ecx,[esp+0x40] (hdc)
if data[off(0x46e2d5)] != 0xe8:                   # smooth60.py applied (its call instead of Sleep)
    sys.exit('apply smooth60.py first')

reloc = next(s for s in pe.sections if s.Name.startswith(b'.reloc'))
raw_lo = B + reloc.VirtualAddress
raw_hi = raw_lo + reloc.SizeOfRawData
used = max(i for i in range(off(raw_lo), off(raw_hi)) if data[i]) - off(raw_lo) + raw_lo
CODE = (used + 17) & ~15                           # past the NUL ending the previous code's strings
D = 0xa0cc00                                       # between smooth60.py's data (ends 0xa0c960) and text_overlay's (0xa0d000)
assert D + 0x100 <= raw_lo + reloc.Misc_VirtualSize
QPF_, NOW, LAST, WS, MAXDT, COUNT, SHOWFPS, SHOWMAX, TMP = (D + 8 * i for i in range(9))
BUF = D + 0x80
QPC, QPF = 0x9c87e8, 0x9c87f8
SetTextColor, SetBkColor, SetBkMode, TextOutA = 0x9c8778, 0x9c877c, 0x9c8780, 0x9c8784
W = 0x5ae24e

asm = f'''
fps_frame:
    pushal
    cmp dword ptr [{QPF_:#x}], 0
    jne ff_have
    push {QPF_:#x}
    call dword ptr [{QPF:#x}]
ff_have:
    push {NOW:#x}
    call dword ptr [{QPC:#x}]
    mov eax, dword ptr [{NOW:#x}]
    cmp dword ptr [{LAST:#x}], 0
    jne ff_run
    mov dword ptr [{LAST:#x}], eax
    mov dword ptr [{WS:#x}], eax
    jmp ff_done
ff_run:
    mov ecx, eax
    sub ecx, dword ptr [{LAST:#x}]
    mov dword ptr [{LAST:#x}], eax
    cmp ecx, dword ptr [{MAXDT:#x}]
    jbe ff_nomax
    mov dword ptr [{MAXDT:#x}], ecx
ff_nomax:
    inc dword ptr [{COUNT:#x}]
    mov ecx, eax
    sub ecx, dword ptr [{WS:#x}]
    cmp ecx, dword ptr [{QPF_:#x}]
    jb ff_done
    mov dword ptr [{TMP:#x}], ecx              ; fps = count * qpf / elapsed (rounded)
    fild dword ptr [{COUNT:#x}]
    fild dword ptr [{QPF_:#x}]
    fmulp st(1), st(0)
    fild dword ptr [{TMP:#x}]
    fdivp st(1), st(0)
    fistp dword ptr [{SHOWFPS:#x}]
    fild dword ptr [{MAXDT:#x}]                ; max ms = maxdt * 1000 / qpf
    mov dword ptr [{TMP:#x}], 1000
    fimul dword ptr [{TMP:#x}]
    fild dword ptr [{QPF_:#x}]
    fdivp st(1), st(0)
    fistp dword ptr [{SHOWMAX:#x}]
    mov dword ptr [{COUNT:#x}], 0
    mov dword ptr [{MAXDT:#x}], 0
    mov dword ptr [{WS:#x}], eax
ff_done:
    popal
{FRAME_TAIL}

; ---- append the decimal digits of eax at edi ----
put_num:
    push ebx
    push ecx
    push edx
    mov ebx, 10
    xor ecx, ecx
pn_div:
    xor edx, edx
    div ebx
    add dl, 0x30
    push edx
    inc ecx
    test eax, eax
    jne pn_div
pn_out:
    pop eax
    mov byte ptr [edi], al
    inc edi
    dec ecx
    jne pn_out
    pop edx
    pop ecx
    pop ebx
    ret

put_str:                                     ; copy zero-terminated esi to edi (without the zero)
    lodsb
    test al, al
    je ps_end
    stosb
    jmp put_str
ps_end:
    ret

fps_draw:
    pushal
    mov ebp, dword ptr [esp + 0x64]            ; hdc of the resource bar (was [esp+0x40] at 0x44506d)
    cmp dword ptr [{SHOWFPS:#x}], 0
    je fd_done
    mov edi, {BUF:#x}
    mov esi, STR_FPS
    call put_str
    mov eax, dword ptr [{SHOWFPS:#x}]
    call put_num
    mov esi, STR_MAX
    call put_str
    mov eax, dword ptr [{SHOWMAX:#x}]
    call put_num
    mov esi, STR_MS
    call put_str
    mov ebx, edi
    sub ebx, {BUF:#x}                          ; length
    push 2                                     ; OPAQUE on a black box, readable on any terrain
    push ebp
    call dword ptr [{SetBkMode:#x}]
    push 0
    push ebp
    call dword ptr [{SetBkColor:#x}]
    movzx esi, word ptr [{W:#x}]
    sub esi, 200                               ; x
    mov eax, 0x0000ffff                        ; yellow (keystone mis-assembles push 0xffff as push -1)
    push eax
    push ebp
    call dword ptr [{SetTextColor:#x}]         ; yellow
    push ebx
    push {BUF:#x}
    push 24
    push esi
    push ebp
    call dword ptr [{TextOutA:#x}]
fd_done:
    popal
    mov eax, dword ptr [0x5ae258]
    ret
'''

ks = Ks(KS_ARCH_X86, KS_MODE_32)
strings = [b'FPS ', b'   max ', b' ms']
def assemble(addrs):
    t = asm.replace('STR_FPS', hex(addrs[0])).replace('STR_MAX', hex(addrs[1])).replace('STR_MS', hex(addrs[2]))
    t = '\n'.join(l.split(';')[0] for l in t.splitlines())
    return bytes(ks.asm(t, CODE)[0]), t
at = CODE + 0x1000
while True:
    addrs, a = [], at
    for x in strings:
        addrs.append(a); a += len(x) + 1
    code, text = assemble(addrs)
    if CODE + len(code) == at:
        break
    at = CODE + len(code)
code += b''.join(x + b'\0' for x in strings)
assert CODE + len(code) <= raw_hi, f'code too large: {len(code)}'
assert not any(data[off(CODE):off(CODE) + len(code)])
data[off(CODE):off(CODE) + len(code)] = code

def label(name):
    head = text.split('\n' + name + ':')[0]
    return CODE + len(bytes(ks.asm(head + '\n' + name + ':\n nop', CODE)[0])) - 1

data[off(0x42b8ce):off(0x42b8ce) + 7] = b'\xe8' + struct.pack('<i', label('fps_frame') - (0x42b8ce + 5)) + b'\x90\x90'
data[off(0x44506d):off(0x44506d) + 5] = b'\xe8' + struct.pack('<i', label('fps_draw') - (0x44506d + 5))
open(dst, 'wb').write(data)
print(f'code {len(code)} bytes at {CODE:#x}')
