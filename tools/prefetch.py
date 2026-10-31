"""The Entente: read the game's graphics archives into the Windows file cache in the background.

Applied last, in both variants. usage: python prefetch.py IN.exe OUT.exe

The game loads the graphics of a unit or building type (Data\\...\\*.les) the first time one is on
screen, in the main thread. Usually that takes a few ms, but a read from a slow or removable drive can
stall: one 216 KB read took 0.9 s (Junkers_J1.les, market save, scrolling across the town zoomed out).
Sound effects (media\\...\\*.wav) are opened and read from their file whenever the sound is not in
one of the sound channels already (mmioOpenA at 0x41d2c5): one open over a town took 0.95 s, with the
game on an SD card that had gone idle.
At its first main loop iteration the game now starts a thread with background priority (low CPU and
I/O priority) that reads every .les file under Data\\ (283 MB in the Steam version) and then every
.wav file under media\\ (105 MB; the music plays from .ogg files and is left out) once, so that the
loads in the game come from memory.
The code and the 64 KB read buffer live in the old relocation table, between modern_hud.py's area and
mode_redraw.py's. The buffer is not allocated: a VirtualAlloc of it changed where the game's later
allocations land, and with that the buildings came out black after saving from the in-game menu in
about half of the tests (the black buildings of mode_redraw.py, which its redraws then did not fix).
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

LOOP_FIRST = 0x404156                             # first call of the main loop iteration 0x46df20
expect(0x46df20, call(0x46df20, LOOP_FIRST).hex())
RELOC_VA, RELOC_SIZE = 0x9cb000, 0x12bc0          # the relocation table of the Steam exe
assert pe.OPTIONAL_HEADER.DllCharacteristics & 0x40 == 0, 'relocations needed'
CODE = RELOC_VA + RELOC_SIZE - 0x900              # mode_redraw.py: the last 0x100 bytes
DATA = CODE + 0x400
assert CODE >= RELOC_VA + 0x1600                  # modern_hud.py: up to there
GetModuleHandleA, GetProcAddress = 0x9c88b8, 0x9c8924
FUNCS = ['CreateThread', 'SetThreadPriority', 'SetThreadInformation', 'FindFirstFileA', 'FindNextFileA',
         'FindClose', 'CreateFileA', 'ReadFile', 'CloseHandle']
G_ONCE, G_EXT, G_GOT, G_MEMPRIO = DATA, DATA + 4, DATA + 8, DATA + 0xc
P = {name: DATA + 0x10 + 4 * i for i, name in enumerate(FUNCS)}
STR = DATA + 0x40
strings, s_at, a = [b'KERNEL32.dll'] + [f.encode() for f in FUNCS], [], STR
for x in strings:
    s_at.append(a); a += len(x) + 1
PATH = a + 3 & ~3                                 # the path being walked, "Data\..."
PATH_MAX = 0x200
DATA_END = PATH + PATH_MAX
assert DATA_END <= RELOC_VA + RELOC_SIZE - 0x100
BLOCK = 0x10000
BUF = RELOC_VA + 0x2000                           # the read buffer, after modern_hud.py's area
assert BUF + BLOCK <= RELOC_VA + RELOC_SIZE - 0xbc0   # mode_redraw.py's building layer follows

def source(thread):
    return f'''
pf_start:                                ; instead of call 0x404156 at 0x46df20 (each main loop iteration)
    cmp byte ptr [{G_ONCE:#x}], 0
    jne pf_loop
    mov byte ptr [{G_ONCE:#x}], 1
    pushal
    push {s_at[0]:#x}
    call dword ptr [{GetModuleHandleA:#x}]
    mov ebx, eax
{"".join(f"""    push {s_at[i + 1]:#x}
    push ebx
    call dword ptr [{GetProcAddress:#x}]
    mov dword ptr [{P[name]:#x}], eax
""" for i, name in enumerate(FUNCS))}    push 0
    push 0
    push 0
    push {thread:#x}                      ; pf_thread
    push 0
    push 0
    call dword ptr [{P['CreateThread']:#x}]
    test eax, eax
    je pf_started
    push eax
    call dword ptr [{P['CloseHandle']:#x}]
pf_started:
    popal
pf_loop:
    jmp {LOOP_FIRST:#x}

pf_thread:                                ; read Data\\**\\*.les and media\\**\\*.wav once, with background priority
    push 0x10000                          ; THREAD_MODE_BACKGROUND_BEGIN
    push -2                               ; the current thread
    call dword ptr [{P['SetThreadPriority']:#x}]
    mov eax, dword ptr [{P['SetThreadInformation']:#x}]
    test eax, eax
    je pt_memprio
    push 4                                ; the background mode also gives the pages it reads a low priority:
    push {G_MEMPRIO:#x}                   ; Windows would reuse them first. Normal memory priority instead
    push 0                                ; ThreadMemoryPriority
    push -2
    call eax
pt_memprio:
    mov dword ptr [{G_EXT:#x}], 0x73656c2e ; ".les"
    mov dword ptr [{PATH:#x}], 0x61746144 ; "Data\\"
    mov byte ptr [{PATH + 4:#x}], 0x5c
    push 5
    call walk
    add esp, 4
    mov dword ptr [{G_EXT:#x}], 0x7661772e ; ".wav"
    mov dword ptr [{PATH:#x}], 0x6964656d ; "media\\"
    mov word ptr [{PATH + 4:#x}], 0x5c61
    push 6
    call walk
    add esp, 4
    xor eax, eax
    ret 4

walk:                                     ; [esp+4]: length of the directory in PATH, with its trailing backslash
    push ebp
    mov ebp, esp
    sub esp, 0x140                        ; WIN32_FIND_DATAA
    push ebx
    push esi
    push edi
    mov ebx, dword ptr [ebp + 8]
    cmp ebx, {PATH_MAX - 0x110}
    ja wk_ret
    mov word ptr [ebx + {PATH:#x}], 0x2a  ; "*"
    lea eax, [ebp - 0x140]
    push eax
    push {PATH:#x}
    call dword ptr [{P['FindFirstFileA']:#x}]
    cmp eax, -1
    je wk_ret
    mov esi, eax
wk_entry:
    lea edi, [ebp - 0x140 + 0x2c]         ; cFileName
    cmp byte ptr [edi], 0x2e              ; ".", ".."
    je wk_next
    mov ecx, ebx
wk_copy:
    mov al, byte ptr [edi]
    mov byte ptr [ecx + {PATH:#x}], al
    test al, al
    je wk_copied
    inc edi
    inc ecx
    jmp wk_copy
wk_copied:                                ; ecx: length of the path
    test byte ptr [ebp - 0x140], 0x10     ; FILE_ATTRIBUTE_DIRECTORY
    je wk_file
    mov byte ptr [ecx + {PATH:#x}], 0x5c
    inc ecx
    push ecx
    call walk
    add esp, 4
    jmp wk_next
wk_file:
    mov eax, dword ptr [ecx + {PATH - 4:#x}]
    or eax, 0x20202000                    ; lower case
    cmp eax, dword ptr [{G_EXT:#x}]       ; ".les" or ".wav"
    jne wk_next
    call read_file
wk_next:
    lea eax, [ebp - 0x140]
    push eax
    push esi
    call dword ptr [{P['FindNextFileA']:#x}]
    test eax, eax
    jne wk_entry
    push esi
    call dword ptr [{P['FindClose']:#x}]
wk_ret:
    pop edi
    pop esi
    pop ebx
    mov esp, ebp
    pop ebp
    ret

read_file:                                ; read the file PATH to its end
    push edi
    push 0
    push 0                                ; no FILE_FLAG_SEQUENTIAL_SCAN: it lets the cache drop what was read
    push 3                               ; OPEN_EXISTING
    push 0
    push 3                                ; FILE_SHARE_READ | FILE_SHARE_WRITE
    push 0x80000000                       ; GENERIC_READ
    push {PATH:#x}
    call dword ptr [{P['CreateFileA']:#x}]
    cmp eax, -1
    je rd_ret
    mov edi, eax
rd_block:
    push 0
    push {G_GOT:#x}
    push {BLOCK:#x}
    push {BUF:#x}
    push edi
    call dword ptr [{P['ReadFile']:#x}]
    test eax, eax
    je rd_close
    cmp dword ptr [{G_GOT:#x}], 0
    jne rd_block
rd_close:
    push edi
    call dword ptr [{P['CloseHandle']:#x}]
rd_ret:
    pop edi
    ret
labels:
    .long pf_thread
'''
assemble = lambda asm: bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm('\n'.join(l.split(';')[0] for l in asm.splitlines()), CODE)[0])
thread = struct.unpack('<I', assemble(source(0x7fffffff))[-4:])[0]   # push imm32 of a forward label: 2 passes
code = assemble(source(thread))
assert struct.unpack('<I', code[-4:])[0] == thread
code = code[:-4]
assert CODE + len(code) <= DATA, f'code too large: {len(code)} bytes'
init = bytearray(DATA_END - DATA)
struct.pack_into('<I', init, G_MEMPRIO - DATA, 5)   # MEMORY_PRIORITY_NORMAL
for at, x in zip(s_at, strings):
    init[at - DATA:at - DATA + len(x)] = x
data[off(CODE):off(CODE) + len(code)] = code
data[off(DATA):off(DATA_END)] = init
data[off(0x46df20):off(0x46df20) + 5] = call(0x46df20, CODE)
open(dst, 'wb').write(data)
print(f'code {len(code)} bytes at {CODE:#x}, data {DATA:#x}-{DATA_END:#x}')
