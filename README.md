A simple desktop companion engine with customization settings

git clone https://github.com/CaptainKTo12/KTesktop.git

Requirements  
- Python 3.10
- Pillow
- PySide6
- Tkinter

Install the Python dependencies:  

python -m pip install Pillow PySide6 

Tkinter is included with many Python installations, but on Linux you may need to install it separately.

Linux dependencies:  

Fedora:  

**sudo dnf install python3 python3-tkinter**  

Ubuntu / Linux Mint:  

**sudo apt update**  
**sudo apt install python3 python3-tk**  

Arch Linux:  

**sudo pacman -S tk**  

------------------------

Install PyInstaller:

**python -m pip install pyinstaller**

Windows:

**python -m PyInstaller --clean --onefile --windowed --name KTesktop main.py**

The executable will be generated in the dist folder.

If there is no test.gif, place it next to the executable.

Linux:

**python3 -m PyInstaller --clean --onefile --name KTesktop main.py**

Make the generated executable runnable:

**chmod +x dist/KTesktop**

If there is no test.gif, place it next to the executable.

Note: Build separately on Windows and Linux. PyInstaller does not cross-compile between operating systems.
