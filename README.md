# The Entente Gold – Windows 10/11 fix

Fix for **The Entente Gold** (Steam) on Windows 10 and 11: the game starts, runs full screen
in widescreen resolutions without stretching, and units no longer disappear while scrolling.

[Polska wersja poniżej](#polski)

## English

### Install (2 minutes)

1. Download **`The-Entente-Gold-Win11-Fix.zip`** from the
   [latest release](https://github.com/grzegorz2047/The-entente-gold-win-11-fix/releases/latest).
2. Right-click the downloaded file → **Extract All…** → **Extract**.
3. In the extracted folder, double-click **`Install.cmd`**.
   - If Windows shows *"Windows protected your PC"*, click **More info** → **Run anyway**.
4. Wait for **DONE!** and press any key.
5. Start the game from Steam as usual.

The installer finds the game in your Steam library by itself. If it cannot, it asks you to
select the game folder (the one with `Antanta.exe`). An internet connection is needed once,
to download dgVoodoo2.

### Changing the resolution

In the game, open **Options** and **press and hold** the resolution button. Available:
1024×768 (original), 1152×720, 1280×800 (default), 1440×900. The image keeps its proportions
on any monitor; on 16:9 screens there are thin black bars at the sides.

### Improvements: zoom with the mouse wheel (optional)

Instead of `Install.cmd`, double-click **`Install-Improvements.cmd`**. In addition to the fix, the
mouse wheel then zooms the map smoothly: out, to a view 1.5× wider than usual, and in, up to 2.5×.
The **+** and **-** keys zoom as well (main keyboard or numeric keypad; hold to keep zooming).
The game starts with the usual view. Clicks and selection work on the zoomed map, and the minimap
frame shows the visible area.

To make zooming out possible, the game runs in 1920×1200 in this variant, so the game's panels and
the minimap are about a third smaller than with the basic fix (the new top bar scales with the
resolution). Zooming in enlarges the
original graphics, so close up they are less sharp. You can switch between the two variants at any
time by running the other `.cmd` file.

This variant also has a modern HUD: the map fills the whole screen without the wooden frame, and the
resources are shown on a semi-transparent bar at the top: the game's resource icons with their values,
the population with the housing limit (red when it is reached) and the electricity balance as a gauge
(green: surplus, yellow: balanced, red: shortage) instead of the thermometer at the right edge.
The minimap grows with the resolution (300×300 instead of 200×200 in 1920×1200), shows units as larger
dots, sits on the same kind of panel instead of the wooden frame, and its buttons are scaled with it.
The selection panel at the bottom left lies on such a panel too, instead of thin bronze lines over the
map, so its text stays readable on any terrain. Saved games stay compatible with the basic fix and the
original game.

### Uninstall

Double-click **`Uninstall.cmd`**. All original game files are restored.

If Steam updates the game or you use *Verify integrity of game files*, Steam restores the
original `Antanta.exe` – just run `Install.cmd` again.

### What it does

- **dgVoodoo2** (downloaded from [its author](https://github.com/dege-diosg/dgVoodoo2), checksum
  verified) translates the game's DirectDraw/Direct3D 7 to Direct3D 11. Without it the game
  crashes on modern Windows.
- **Patches `Antanta.exe`** (the original is kept in `_win11fix_backup`; the patch is applied
  only to the known Steam version):
  - widescreen resolutions instead of 1152×864/1280×960/1280×1024, with the map view and the
    top bar adjusted to the screen width;
  - units no longer vanish while the map scrolls (the game copied its depth buffer onto itself,
    which modern graphics drivers do not support; it is now cleared instead);
  - units move smoothly at up to 60 fps: the game logic keeps its original pace (one step per
    "game speed" milliseconds), and in the time the game used to sleep it shows extra frames with
    units drawn between their positions;
  - button tooltips (e.g. building costs) no longer flicker in those extra frames;
  - HUD text is drawn on a separate layer, which keeps the frame rate steady;
  - an FPS counter in the top-right corner ("FPS 60  max 33 ms": frames per second and the
    longest frame of the last second);
  - buildings no longer turn black after saving or loading from the in-game menu (the dialogs
    switch the screen mode; the map is now redrawn afterwards);
  - no freezes when units or buildings appear on screen for the first time: the game loads their
    graphics only then, and a read from a slow or removable drive could stall it for up to a second.
    At start a background thread now reads the graphics archives (about 300 MB) into the Windows
    file cache.
- Sharp picture with Windows display scaling (125 %, 150 %, 175 %…).
- Skips the intro video, which hangs on a black screen on modern Windows.

### Known limitations

- The map still scrolls in whole-tile steps, as in the original; while scrolling the game runs at
  its original frame rate.
- The main menu is drawn in 4:3, so it has black bars at the sides.

### For developers

`installer/antanta.patch` is a byte-level patch generated from `tools/build_patched_exe.py` and
`tools/smooth60.py` (`pip install pefile keystone-engine`):

```
python tools/build_patched_exe.py Antanta.exe base.exe 1024x768 1152x720 1280x800 1440x900
python tools/smooth60.py base.exe smooth.exe
python tools/text_overlay.py smooth.exe overlay.exe
python tools/fps_counter.py overlay.exe counter.exe
python tools/mode_redraw.py counter.exe redraw.exe
python tools/terrain_strip.py redraw.exe strip.exe
python tools/prefetch.py strip.exe out.exe
python tools/make_diff.py Antanta.exe out.exe installer/antanta.patch "tools/build_patched_exe.py + smooth60.py + text_overlay.py + fps_counter.py + mode_redraw.py + terrain_strip.py + prefetch.py"

python tools/build_patched_exe.py Antanta.exe base2.exe 1024x768 1152x720 1280x800 1920x1200
python tools/smooth60.py base2.exe smooth2.exe
python tools/text_overlay.py smooth2.exe overlay2.exe
python tools/fps_counter.py overlay2.exe out2.exe
python tools/mode_redraw.py out2.exe redraw2.exe
python tools/zoom.py redraw2.exe zoom.exe
python tools/terrain_strip.py zoom.exe zoom2.exe
python tools/modern_hud.py zoom2.exe hud.exe
python tools/prefetch.py hud.exe out2.exe
python tools/make_diff.py Antanta.exe out2.exe installer/antanta-improvements.patch "tools/build_patched_exe.py (1920x1200) + smooth60.py + text_overlay.py + fps_counter.py + mode_redraw.py + zoom.py + terrain_strip.py + modern_hud.py + prefetch.py"
```

---

## Polski

Poprawka do gry **The Entente Gold** (Steam) dla Windows 10 i 11: gra się uruchamia, działa na
pełnym ekranie w panoramicznych rozdzielczościach bez rozciągania obrazu, a jednostki nie znikają
przy przewijaniu mapy.

### Instalacja (2 minuty)

1. Pobierz plik **`The-Entente-Gold-Win11-Fix.zip`** z
   [najnowszego wydania](https://github.com/grzegorz2047/The-entente-gold-win-11-fix/releases/latest).
2. Kliknij pobrany plik prawym przyciskiem → **Wyodrębnij wszystkie…** → **Wyodrębnij**.
3. W rozpakowanym folderze kliknij dwukrotnie **`Install.cmd`**.
   - Jeśli Windows pokaże *„System Windows ochronił ten komputer”*, kliknij **Więcej informacji**
     → **Uruchom mimo to**.
4. Poczekaj na napis **GOTOWE!** i naciśnij dowolny klawisz.
5. Uruchom grę normalnie ze Steama.

Instalator sam znajdzie grę w bibliotece Steam. Jeśli mu się nie uda, poprosi o wskazanie folderu
gry (tego z plikiem `Antanta.exe`). Potrzebny jest jednorazowo internet do pobrania dgVoodoo2.

### Zmiana rozdzielczości

W grze wejdź w **Opcje** i **przytrzymaj** przycisk zmiany rozdzielczości. Do wyboru:
1024×768 (oryginalna), 1152×720, 1280×800 (domyślna), 1440×900. Obraz zachowuje proporcje na
każdym monitorze; na ekranach 16:9 po bokach są wąskie czarne pasy.

### Ulepszenia: zoom kółkiem myszy (opcjonalne)

Zamiast `Install.cmd` kliknij dwukrotnie **`Install-Improvements.cmd`**. Oprócz poprawki kółko myszy
płynnie oddala mapę (do widoku 1,5× szerszego niż zwykle) i przybliża ją (do 2,5×). Tak samo działają
klawisze **+** i **-** (na głównej klawiaturze lub numerycznej; przytrzymanie zoomuje dalej). Gra startuje
ze zwykłym widokiem. Klikanie i zaznaczanie działają na przybliżonej mapie, a ramka na minimapie
pokazuje widoczny obszar.

Żeby dało się oddalać, w tym wariancie gra działa w rozdzielczości 1920×1200, więc panele gry
i minimapa są o około jedną trzecią mniejsze niż w podstawowej poprawce (nowy górny pasek skaluje
się z rozdzielczością).
Przybliżenie powiększa oryginalną grafikę, więc z bliska jest mniej ostra. Między wariantami można
przełączać się w każdej chwili, uruchamiając drugi plik `.cmd`.

Ten wariant ma też nowoczesny interfejs: mapa zajmuje cały ekran, bez drewnianej ramki, a zasoby są
na półprzezroczystym pasku u góry: ikony zasobów z gry z ich wartościami, ludność z limitem
mieszkań (na czerwono, gdy limit jest osiągnięty) i bilans prądu jako wskaźnik (zielony: nadwyżka,
żółty: równowaga, czerwony: brak) zamiast termometru przy prawej krawędzi. Minimapa rośnie razem
z rozdzielczością (300×300 zamiast 200×200 w 1920×1200), pokazuje jednostki większymi kropkami, leży
na takim samym panelu zamiast drewnianej ramki, a jej przyciski są przeskalowane razem z nią. Panel
zaznaczenia w lewym dolnym rogu też leży na takim panelu, zamiast cienkich brązowych linii na tle mapy,
więc jego tekst jest czytelny na każdym terenie. Zapisy gry pozostają zgodne z podstawową poprawką
i oryginalną grą.

### Odinstalowanie

Kliknij dwukrotnie **`Uninstall.cmd`**. Wszystkie oryginalne pliki gry zostaną przywrócone.

Jeśli Steam zaktualizuje grę albo użyjesz *Zweryfikuj spójność plików gry*, Steam przywróci
oryginalny `Antanta.exe` – wystarczy ponownie uruchomić `Install.cmd`.

### Co robi poprawka

- **dgVoodoo2** (pobierany od [autora](https://github.com/dege-diosg/dgVoodoo2), z kontrolą sumy
  kontrolnej) tłumaczy grafikę gry (DirectDraw/Direct3D 7) na Direct3D 11. Bez niego gra na
  współczesnym Windows się wysypuje.
- **Poprawia `Antanta.exe`** (oryginał zostaje w `_win11fix_backup`; poprawka nakłada się tylko na
  znaną wersję ze Steama):
  - rozdzielczości panoramiczne zamiast 1152×864/1280×960/1280×1024, z widokiem mapy i górnym
    paskiem dopasowanymi do szerokości ekranu;
  - jednostki nie znikają przy przewijaniu mapy (gra kopiowała bufor głębi sam na siebie, czego
    współczesne sterowniki nie obsługują; teraz jest on czyszczony);
  - jednostki poruszają się płynnie do 60 klatek na sekundę: logika gry zachowuje oryginalne tempo
    (jeden krok co „prędkość gry” milisekund), a w czasie, w którym gra dotąd czekała, pokazuje
    dodatkowe klatki z jednostkami narysowanymi między ich pozycjami;
  - opisy przycisków (np. koszt budowy) nie migają w tych dodatkowych klatkach;
  - teksty interfejsu są rysowane na osobnej warstwie, co stabilizuje liczbę klatek;
  - licznik klatek w prawym górnym rogu („FPS 60  max 33 ms”: klatki na sekundę i najdłuższa
    klatka z ostatniej sekundy);
  - budynki nie robią się czarne po zapisaniu lub wczytaniu gry z menu w trakcie gry (okna
    zapisu zmieniają tryb ekranu; teraz mapa jest potem rysowana na nowo);
  - brak przycięć, gdy jednostki lub budynki pierwszy raz pojawiają się na ekranie: gra wczytuje
    ich grafikę dopiero wtedy, a odczyt z wolnego lub wymiennego dysku potrafił ją zatrzymać nawet na
    sekundę. Teraz przy starcie wątek w tle wczytuje archiwa grafiki (około 300 MB) do pamięci
    podręcznej Windows.
- Ostry obraz przy skalowaniu ekranu w Windows (125 %, 150 %, 175 %…).
- Pomija film wstępny, który na współczesnym Windows zawiesza się na czarnym ekranie.

### Znane ograniczenia

- Mapa nadal przewija się skokami o całe pole, jak w oryginale; podczas przewijania gra działa
  w oryginalnej liczbie klatek.
- Menu główne jest rysowane w proporcjach 4:3, więc ma czarne pasy po bokach.

## Credits

- [dgVoodoo2](https://github.com/dege-diosg/dgVoodoo2) by Dege – downloaded by the installer, not
  redistributed here.
- The Entente / Антанта © Lesta Studio, Buka Entertainment. This project contains no game files.
