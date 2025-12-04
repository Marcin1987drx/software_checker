# 🎨 Jak dodać własną ikonę do aplikacji

## Krok 1: Przygotuj logo
- Format: **PNG** (preferowany) lub JPG
- Rozmiar: minimum **256x256** pikseli (im większe, tym lepiej)
- Przezroczystość: Opcjonalna (PNG z alpha channel)
- Nazwa pliku: **logo.png**

## Krok 2: Umieść w projekcie
```
software_checker/
├── logo.png          ← Tu wstaw swoje logo
├── convert_logo_to_icon.py
├── SoftwareChecker.spec
└── build_exe.bat
```

## Krok 3a: Budowanie lokalnie (Windows)
```bash
# Uruchom skrypt budowania
build_exe.bat
```
Skrypt automatycznie:
1. Wykryje logo.png
2. Zainstaluje Pillow (jeśli potrzeba)
3. Skonwertuje logo.png → icon.ico
4. Zbuduje EXE z ikoną

## Krok 3b: Budowanie przez GitHub Actions
```bash
# Commituj logo.png
git add logo.png
git commit -m "Add application icon"
git push origin main

# Lub stwórz tag dla release
git tag v3.0
git push origin v3.0
```

GitHub Actions automatycznie:
1. Wykryje logo.png w repo
2. Skonwertuje na icon.ico
3. Zbuduje EXE z ikoną
4. Udostępni jako artifact/release

## Krok 4: Sprawdź wynik
Wykonany plik `SoftwareChecker.exe` będzie miał:
- ✅ Twoją ikonę w Eksploratorze Windows
- ✅ Twoją ikonę na pasku zadań
- ✅ Twoją ikonę w Alt+Tab

## 📝 Uwagi
- Jeśli nie ma logo.png, EXE zbuduje się z domyślną ikoną Pythona
- Konwersja tworzy icon.ico z rozmiarami: 16, 32, 48, 64, 128, 256 px
- Plik icon.ico można dodać do .gitignore (generowany automatycznie)

## 🔧 Ręczna konwersja (opcjonalnie)
```bash
pip install pillow
python convert_logo_to_icon.py
```
Stworzy plik `icon.ico` gotowy do użycia.

## 🚨 Troubleshooting
**Problem**: "Pillow not found"
```bash
pip install pillow
```

**Problem**: "Cannot identify image file"
- Sprawdź czy logo.png nie jest uszkodzone
- Otwórz w Paint/GIMP i zapisz ponownie

**Problem**: "Icon.ico not found during build"
- Uruchom ręcznie: `python convert_logo_to_icon.py`
- Sprawdź czy icon.ico został utworzony

## ✨ Przykładowe logo
Możesz użyć:
- Własnego projektu graficznego
- Darmowego logo z https://icons8.com
- Wygenerować AI (DALL-E, Midjourney)
- Użyć emoji jako podstawy
