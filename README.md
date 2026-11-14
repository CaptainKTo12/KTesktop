
A simple desktop companion engine with customization settings and text-to-speech (TTS) support.

Clone the repository

```bash
git clone https://github.com/CaptainKTo12/KTesktop.git
cd KTesktop
```

Requirements

- Python 3.10
- Pillow
- PySide6
- Tkinter
- pyttsx3

Install Python dependencies

```bash
python -m pip install Pillow PySide6 pyttsx3
```

Tkinter is included with many Python installations, but on Linux you may need to install it separately.

Linux dependencies

**Fedora:**

```bash
sudo dnf install python3 python3-tkinter
```

**Ubuntu / Linux Mint:**

```bash
sudo apt update
sudo apt install python3 python3-tk
```

**Arch Linux:**

```bash
sudo pacman -S tk
```

---

Install PyInstaller

```bash
python -m pip install pyinstaller
```

## Windows

```bash
python -m PyInstaller --clean --onefile --windowed --name KTesktop main.py
```

The executable will be generated in the `dist` folder.

If there is no `test.gif`, place it next to the executable.

## Linux

```bash
python3 -m PyInstaller --clean --onefile --name KTesktop main.py
```

Make the generated executable runnable:

```bash
chmod +x dist/KTesktop
```

If there is no `test.gif`, place it next to the executable.

**Note:** Build separately on Windows and Linux. PyInstaller does not cross-compile between operating systems.
