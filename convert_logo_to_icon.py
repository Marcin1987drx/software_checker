# -*- coding: utf-8 -*-
"""
Converts logo.png to icon.ico for Windows application.
Requires: pip install pillow
"""
from PIL import Image
import sys

def convert_png_to_ico(png_path, ico_path):
    """Convert PNG to ICO with multiple sizes."""
    try:
        img = Image.open(png_path)
        
        # Convert to RGBA if needed
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        
        # Windows icon sizes
        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        
        # Prepare multiple sizes
        icon_images = []
        for size in sizes:
            resized = img.resize(size, Image.Resampling.LANCZOS)
            icon_images.append(resized)
        
        # Save as ICO
        icon_images[0].save(
            ico_path,
            format='ICO',
            sizes=sizes,
            append_images=icon_images[1:]
        )
        
        print(f"[OK] Ikona utworzona: {ico_path}")
        return True
        
    except FileNotFoundError:
        print(f"[ERROR] Nie znaleziono pliku: {png_path}")
        print("[INFO] Upewnij sie, ze logo.png jest w glownym folderze projektu")
        return False
    except Exception as e:
        print(f"[ERROR] Blad konwersji: {e}")
        return False

if __name__ == "__main__":
    png_file = "logo.png"
    ico_file = "icon.ico"
    
    print(f"[INFO] Konwersja {png_file} -> {ico_file}...")
    success = convert_png_to_ico(png_file, ico_file)
    
    if success:
        print("[OK] Gotowe! Ikona zostala utworzona.")
    else:
        print("[ERROR] Konwersja nie powiodla sie.")
        sys.exit(1)
