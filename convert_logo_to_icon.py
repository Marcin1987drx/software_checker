"""
Konwertuje logo.png na icon.ico dla aplikacji Windows.
Wymaga: pip install pillow
"""
from PIL import Image
import sys

def convert_png_to_ico(png_path, ico_path):
    """Konwertuje PNG na ICO z różnymi rozmiarami."""
    try:
        img = Image.open(png_path)
        
        # Konwertuj na RGBA jeśli potrzeba
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        
        # Rozmiary ikon Windows
        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        
        # Przygotuj różne rozmiary
        icon_images = []
        for size in sizes:
            resized = img.resize(size, Image.Resampling.LANCZOS)
            icon_images.append(resized)
        
        # Zapisz jako ICO
        icon_images[0].save(
            ico_path,
            format='ICO',
            sizes=sizes,
            append_images=icon_images[1:]
        )
        
        print(f"✅ Ikona utworzona: {ico_path}")
        return True
        
    except FileNotFoundError:
        print(f"❌ Nie znaleziono pliku: {png_path}")
        print("💡 Upewnij się, że logo.png jest w głównym folderze projektu")
        return False
    except Exception as e:
        print(f"❌ Błąd konwersji: {e}")
        return False

if __name__ == "__main__":
    png_file = "logo.png"
    ico_file = "icon.ico"
    
    print(f"🔄 Konwersja {png_file} → {ico_file}...")
    success = convert_png_to_ico(png_file, ico_file)
    
    if success:
        print("✅ Gotowe! Ikona została utworzona.")
    else:
        print("❌ Konwersja nie powiodła się.")
        sys.exit(1)
