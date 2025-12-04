# 🚀 Quick Start: Budowanie EXE

## Sposób 1: GitHub Actions (Zalecany! ⭐)

### Automatyczne budowanie przy każdym commit:
```bash
git add .
git commit -m "Your changes"
git push origin main
```
➡️ Idź na GitHub → zakładka **Actions** → pobierz zbudowany EXE

### Tworzenie Release z tagiem:
```bash
git tag v3.0
git push origin v3.0
```
➡️ GitHub automatycznie:
- Zbuduje EXE
- Stworzy Release
- Doda ZIP do pobrania

### Ręczne uruchomienie (bez commitu):
1. Idź na GitHub → **Actions** tab
2. Wybierz "Build Windows EXE"
3. Kliknij **"Run workflow"**
4. Wybierz branch `main`
5. Kliknij zielony przycisk "Run workflow"

---

## Sposób 2: Lokalne budowanie (Windows)

### Wymagania:
```bash
python --version  # Python 3.11+
pip install -r requirements.txt
pip install pyinstaller pillow
```

### Budowanie:
```bash
# Opcja A: Używając gotowego skryptu (najprostsze)
build_exe.bat

# Opcja B: Ręcznie
python convert_logo_to_icon.py    # Jeśli masz logo.png
pyinstaller SoftwareChecker.spec
```

### Wynik:
```
dist/
└── SoftwareChecker.exe    ← Twoja aplikacja!
```

---

## 🎨 Dodawanie ikony

1. Wrzuć `logo.png` do głównego folderu projektu
2. Uruchom budowanie (jak wyżej)
3. Ikona zostanie automatycznie skonwertowana i dodana do EXE

**Wymogi logo:**
- Format: PNG (zalecane) lub JPG
- Rozmiar: minimum 256x256 px
- Nazwa: `logo.png`

---

## 📦 Dystrybucja

### Co dystrybuować:
```
SoftwareChecker.exe    ← TYLKO TEN PLIK!
```

### Co NIE dystrybuować:
- ❌ Folder `build/`
- ❌ Folder `dist/` (tylko .exe)
- ❌ Python, pip, biblioteki
- ❌ Foldery `app/`, źródła `.py`

### Pierwsze uruchomienie (użytkownik):
1. Kliknij `SoftwareChecker.exe`
2. Aplikacja automatycznie stworzy folder `user_data/`
3. Skonfiguruj ścieżki w Settings

---

## 🔧 Konfiguracja budowania

### Zmiana zachowania konsoli:
Edytuj `SoftwareChecker.spec`:
```python
console=False,  # Bez konsoli (wersja produkcyjna)
console=True,   # Z konsolą (debugowanie)
```

### Dodawanie nowych bibliotek:
1. Dodaj do `requirements.txt`
2. Dodaj do `hiddenimports` w `SoftwareChecker.spec`:
```python
hiddenimports=[
    'twoja_biblioteka',
    'twoja_biblioteka.modul',
],
```

---

## ❓ FAQ

**Q: Jak długo trwa budowanie?**
A: GitHub Actions: ~5-10 minut | Lokalnie: ~2-3 minuty

**Q: Czy mogę budować na Linux/Mac?**
A: Nie. EXE wymaga Windows. Użyj GitHub Actions z Windows runner.

**Q: Co jeśli antywirus blokuje EXE?**
A: Normalne dla nowych EXE. Dodaj do wyjątków lub podpisz certyfikatem.

**Q: Jak zaktualizować wersję?**
A: Zmień numer w kodzie + stwórz nowy tag (np. `v3.1`)

**Q: Gdzie są logi w wersji EXE?**
A: W folderze `user_data/logs/app.log`

---

## 📞 Pomoc

- GitHub Issues: https://github.com/Marcin1987drx/software_checker/issues
- Dokumentacja PyInstaller: https://pyinstaller.org/
- Dokumentacja Actions: https://docs.github.com/actions
