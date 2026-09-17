"""Build the ImageGen Desktop GUI as a Windows executable using PyInstaller."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

def build():
    args = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "ImageGen-GUI",
        "--icon", str(ROOT / "gui" / "assets" / "icon.ico") if (ROOT / "gui" / "assets" / "icon.ico").exists() else "NONE",
        "--add-data", f"{ROOT / 'gui' / 'config' / 'command_schema.json'};gui/config",
        "--paths", str(ROOT),
        str(ROOT / "gui" / "main.py"),
    ]
    subprocess.run(args, check=True)

if __name__ == "__main__":
    build()
