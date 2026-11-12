# py -m PyInstaller --onefile --noconsole main.py


import json
import os
import queue
import socket
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from PIL import Image


APP_DIR = (
    os.path.dirname(os.path.abspath(sys.executable))
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.abspath(__file__))
)
DEFAULT_IMAGE = os.path.join(APP_DIR, "test.gif")

def renderer_process(host, port, token):
    from PySide6.QtCore import Qt, QTimer, QObject, Signal, Slot
    from PySide6.QtGui import QImage, QPixmap
    from PySide6.QtWidgets import QApplication, QLabel, QWidget

    class SocketReader(QObject):
        received = Signal(dict)
        disconnected = Signal()

        def __init__(self, connection):
            super().__init__()
            self.connection = connection

        def run(self):
            buffer = b""
            try:
                while True:
                    data = self.connection.recv(65536)
                    if not data:
                        break
                    buffer += data

                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        try:
                            self.received.emit(json.loads(line))
                        except (ValueError, UnicodeDecodeError):
                            pass
            except OSError:
                pass
            self.disconnected.emit()

    class Character(QWidget):
        def __init__(self, connection):
            super().__init__()

            self.connection = connection
            self.send_lock = threading.Lock()

            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self.setAttribute(
                Qt.WidgetAttribute.WA_TranslucentBackground, True
            )
            self.setAttribute(
                Qt.WidgetAttribute.WA_NoSystemBackground, True
            )
            self.setStyleSheet("background: transparent;")

            self.label = QLabel(self)
            self.label.setStyleSheet("background: transparent;")
            self.label.setAttribute(
                Qt.WidgetAttribute.WA_TranslucentBackground, True
            )
            self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            self.frames = []
            self.durations = []
            self.frame_index = 0
            self.scale = 1.0
            self.speed = 1.0
            self.drag_offset = None

            self.timer = QTimer(self)
            self.timer.timeout.connect(self.next_frame)

            self.reader = SocketReader(connection)
            self.reader.received.connect(self.handle_command)
            self.reader.disconnected.connect(
                QApplication.instance().quit
            )

            threading.Thread(
                target=self.reader.run,
                daemon=True
            ).start()

            self.move(100, 100)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        def send(self, event, **data):
            packet = {"event": event, **data}
            try:
                with self.send_lock:
                    self.connection.sendall(
                        (json.dumps(packet) + "\n").encode()
                    )
            except OSError:
                QApplication.instance().quit()

        @Slot(dict)
        def handle_command(self, packet):
            command = packet.get("command")

            if command == "load":
                self.load_image(packet.get("path", ""))

            elif command == "size":
                self.scale = float(packet["value"])
                self.show_frame()

            elif command == "speed":
                self.speed = float(packet["value"])
                self.schedule_frame()

            elif command == "exit":
                self.close()

        def load_image(self, path):
            try:
                image = Image.open(path)
                frames = []
                durations = []

                for i in range(getattr(image, "n_frames", 1)):
                    image.seek(i)
                    frames.append(image.convert("RGBA").copy())
                    durations.append(
                        max(20, int(image.info.get("duration", 100) or 100))
                    )

                if not frames:
                    raise ValueError("No frames found in image.")

                self.timer.stop()
                self.frames = frames
                self.durations = durations
                self.frame_index = 0
                self.show_frame()
                self.schedule_frame()
                self.send("image_loaded", path=path)

            except Exception as error:
                self.send("image_error", error=str(error))

        def show_frame(self):
            if not self.frames:
                return

            frame = self.frames[self.frame_index]
            width = max(1, int(frame.width * self.scale))
            height = max(1, int(frame.height * self.scale))

            frame = frame.resize(
                (width, height),
                Image.Resampling.LANCZOS
            )

            qimage = QImage(
                frame.tobytes(),
                width,
                height,
                width * 4,
                QImage.Format.Format_RGBA8888
            ).copy()

            self.label.setPixmap(QPixmap.fromImage(qimage))
            self.label.resize(width, height)
            self.resize(width, height)

        def schedule_frame(self):
            if len(self.frames) < 2:
                self.timer.stop()
                return

            delay = int(
                self.durations[self.frame_index] / max(0.05, self.speed)
            )
            self.timer.start(max(10, delay))

        def next_frame(self):
            if not self.frames:
                return

            self.frame_index = (
                self.frame_index + 1
            ) % len(self.frames)

            self.show_frame()
            self.schedule_frame()

        def mousePressEvent(self, event):
            if event.button() == Qt.MouseButton.LeftButton:
                self.drag_offset = (
                    event.globalPosition().toPoint()
                    - self.frameGeometry().topLeft()
                )
                self.activateWindow()
                self.setFocus()
                event.accept()

            elif event.button() == Qt.MouseButton.RightButton:
                self.send(
                    "open_settings",
                    x=self.x(),
                    y=self.y(),
                    width=self.width()
                )
                event.accept()

            else:
                super().mousePressEvent(event)

        def mouseMoveEvent(self, event):
            if (
                self.drag_offset is not None
                and event.buttons() & Qt.MouseButton.LeftButton
            ):
                self.move(
                    event.globalPosition().toPoint() - self.drag_offset
                )
                event.accept()
            else:
                super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event):
            if event.button() == Qt.MouseButton.LeftButton:
                self.drag_offset = None
            super().mouseReleaseEvent(event)

        def keyPressEvent(self, event):
            if event.key() == Qt.Key.Key_Escape:
                self.send("exit_requested")
                self.close()
                return
            super().keyPressEvent(event)

        def closeEvent(self, event):
            self.timer.stop()
            event.accept()
            QApplication.instance().quit()

    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.settimeout(15)
    connection.connect((host, int(port)))
    connection.settimeout(None)

    connection.sendall(
        (json.dumps({"token": token}) + "\n").encode()
    )

    app = QApplication(sys.argv[:1])
    window = Character(connection)
    window.show()
    window.setFocus()
    app.exec()

    connection.close()

class RendererController:
    def __init__(self, root, callback):
        self.root = root
        self.callback = callback
        self.messages = queue.Queue()
        self.connection = None
        self.closed = False
        self.lock = threading.Lock()

        self.listener = socket.socket(
            socket.AF_INET, socket.SOCK_STREAM
        )
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)

        host, port = self.listener.getsockname()
        self.host = host
        self.port = port
        self.token = os.urandom(24).hex()

        self.authenticated = threading.Event()
        self.process = None

    def start(self):
        if getattr(sys, "frozen", False):
            command = [
                sys.executable,
                "--kdesktop-renderer",
                self.host,
                str(self.port),
                self.token
            ]
        else:
            command = [
                sys.executable,
                os.path.abspath(__file__),
                "--kdesktop-renderer",
                self.host,
                str(self.port),
                self.token
            ]

        options = {}

        if sys.platform == "win32":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            options["startupinfo"] = startup

        self.process = subprocess.Popen(
            command,
            cwd=APP_DIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **options
        )

        threading.Thread(
            target=self.accept_connection,
            daemon=True
        ).start()

        self.root.after(30, self.poll_messages)
        self.root.after(500, self.monitor_process)

    def accept_connection(self):
        try:
            self.listener.settimeout(20)
            connection, _ = self.listener.accept()
            reader = connection.makefile("rb")
            auth = json.loads(reader.readline().decode())

            if auth.get("token") != self.token:
                connection.close()
                return

            self.connection = connection
            self.authenticated.set()
            self.messages.put({"event": "connected"})

            for line in reader:
                try:
                    self.messages.put(json.loads(line.decode()))
                except (ValueError, UnicodeDecodeError):
                    pass

        except Exception as error:
            if not self.closed:
                self.messages.put({
                    "event": "renderer_error",
                    "error": str(error)
                })

        finally:
            self.messages.put({"event": "disconnected"})

    def send(self, command, **data):
        if self.connection is None or self.closed:
            return

        packet = {"command": command, **data}

        try:
            with self.lock:
                self.connection.sendall(
                    (json.dumps(packet) + "\n").encode()
                )
        except OSError:
            pass

    def poll_messages(self):
        if self.closed:
            return

        try:
            while True:
                self.callback(self.messages.get_nowait())
        except queue.Empty:
            pass

        self.root.after(30, self.poll_messages)

    def monitor_process(self):
        if self.closed:
            return

        if self.process and self.process.poll() is not None:
            self.callback({
                "event": "renderer_process_exited",
                "code": self.process.returncode
            })
            return

        self.root.after(500, self.monitor_process)

    def close(self):
        if self.closed:
            return

        self.send("exit")
        self.closed = True

        try:
            self.listener.close()
        except OSError:
            pass

        if self.connection:
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
            except OSError:
                pass

        if self.process and self.process.poll() is None:
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.terminate()


def run_controller():
    root = tk.Tk()
    root.withdraw()

    renderer = None
    settings_window = None
    current_size = 1.0
    current_speed = 1.0
    shutting_down = False

    def shutdown():
        nonlocal shutting_down
        if shutting_down:
            return

        shutting_down = True

        if renderer:
            renderer.close()

        try:
            root.destroy()
        except tk.TclError:
            pass

    def change_size(value):
        nonlocal current_size
        current_size = float(value)
        if renderer:
            renderer.send("size", value=current_size)

    def change_speed(value):
        nonlocal current_speed
        current_speed = float(value)
        if renderer:
            renderer.send("speed", value=current_speed)

    def close_settings():
        nonlocal settings_window

        if settings_window:
            try:
                settings_window.destroy()
            except tk.TclError:
                pass

        settings_window = None

    def choose_image():
        if not settings_window:
            return

        path = filedialog.askopenfilename(
            parent=settings_window,
            title="Choose Your Buddy",
            filetypes=[
                ("Supported images",
                 "*.gif *.png *.jpg *.jpeg *.bmp *.webp"),
                ("All files", "*.*")
            ]
        )

        if path and renderer:
            renderer.send("load", path=path)

    def reset_image():
        if os.path.exists(DEFAULT_IMAGE):
            renderer.send("load", path=DEFAULT_IMAGE)
        else:
            messagebox.showerror(
                "Missing Default",
                "Could not find test.gif next to the application.",
                parent=settings_window
            )

    def open_settings(x=110, y=100):
        nonlocal settings_window

        if settings_window:
            close_settings()
            return

        window = tk.Toplevel(root)
        settings_window = window

        window.title("Settings")
        window.geometry(f"255x390+{int(x)}+{int(y)}")
        window.resizable(False, False)
        window.attributes("-topmost", True)

        bg = "#ECE9D8"
        blue = "#316AC5"
        dark_blue = "#1941A5"

        window.configure(bg=bg)

        outer = tk.Frame(
            window, bg="white", bd=2, relief="raised"
        )
        outer.pack(fill="both", expand=True, padx=3, pady=3)

        title_bar = tk.Frame(outer, bg=blue, height=28)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)

        tk.Label(
            title_bar,
            text="Character Settings",
            bg=blue,
            fg="white",
            font=("Tahoma", 9, "bold")
        ).pack(side="left", padx=8, pady=4)

        panel = tk.Frame(outer, bg=bg, padx=12, pady=10)
        panel.pack(fill="both", expand=True)

        tk.Label(
            panel,
            text="Change character size and playback speed",
            bg=bg,
            fg=dark_blue,
            font=("Tahoma", 7, "bold")
        ).pack(anchor="w", pady=(2, 5))

        tk.Label(
            panel,
            text="Character Size",
            bg=bg,
            font=("Tahoma", 9, "bold")
        ).pack(anchor="w")

        size_slider = tk.Scale(
            panel,
            from_=0.3,
            to=2.5,
            resolution=0.1,
            orient="horizontal",
            command=change_size,
            bg=bg,
            fg="#222222",
            troughcolor="#A6C8F0",
            activebackground=blue,
            highlightthickness=0,
            bd=1,
            relief="sunken",
            font=("Tahoma", 8),
            showvalue=True,
            sliderlength=18
        )
        size_slider.set(current_size)
        size_slider.pack(fill="x", pady=(0, 8))

        tk.Label(
            panel,
            text="GIF Playback Speed",
            bg=bg,
            font=("Tahoma", 9, "bold")
        ).pack(anchor="w")

        speed_slider = tk.Scale(
            panel,
            from_=0.25,
            to=3.0,
            resolution=0.25,
            orient="horizontal",
            command=change_speed,
            bg=bg,
            fg="#222222",
            troughcolor="#A6C8F0",
            activebackground=blue,
            highlightthickness=0,
            bd=1,
            relief="sunken",
            font=("Tahoma", 8),
            showvalue=True,
            sliderlength=18
        )
        speed_slider.set(current_speed)
        speed_slider.pack(fill="x", pady=(0, 10))

        tk.Label(
            panel,
            text="Character Appearance",
            bg=bg,
            fg=dark_blue,
            font=("Tahoma", 9, "bold")
        ).pack(anchor="w", pady=(2, 5))

        tk.Button(
            panel,
            text="Choose Image / GIF",
            command=choose_image,
            bg=bg,
            font=("Tahoma", 8),
            relief="raised",
            bd=2
        ).pack(fill="x", pady=3)

        tk.Button(
            panel,
            text="Reset to Default",
            command=reset_image,
            bg=bg,
            font=("Tahoma", 8),
            relief="raised",
            bd=2
        ).pack(fill="x", pady=3)

        buttons = tk.Frame(panel, bg=bg)
        buttons.pack(fill="x", pady=(8, 0))

        tk.Button(
            buttons,
            text="OK",
            width=9,
            command=close_settings,
            bg=bg,
            font=("Tahoma", 8),
            relief="raised",
            bd=2
        ).pack(side="right")

        tk.Label(
            panel,
            text="To leave program press [ESCAPE]",
            bg=bg,
            fg=dark_blue,
            font=("Tahoma", 9, "bold")
        ).pack(anchor="w", pady=(2, 5))

        tk.Label(
            panel,
            text="KTesktop by @KTo",
            bg=bg,
            fg=dark_blue,
            font=("Tahoma", 5, "bold")
        ).pack(anchor="w", pady=(2, 5))

        window.protocol("WM_DELETE_WINDOW", close_settings)

    def handle_message(packet):
        event = packet.get("event")

        if event == "open_settings":
            x = packet.get("x", 100)
            y = packet.get("y", 100)
            width = packet.get("width", 0)
            open_settings(x + width + 10, y)

        elif event == "image_error":
            messagebox.showerror(
                "Image Error",
                packet.get("error", "Could not load image."),
                parent=settings_window or root
            )

        elif event == "renderer_error":
            messagebox.showerror(
                "Renderer Error",
                packet.get("error", "The renderer failed."),
                parent=root
            )
            shutdown()

        elif event in ("exit_requested", "renderer_process_exited"):
            shutdown()

    if not os.path.exists(DEFAULT_IMAGE):
        messagebox.showerror(
            "Missing Default",
            "Please put test.gif next to main.py.",
            parent=root
        )
        root.destroy()
        return

    renderer = RendererController(root, handle_message)
    renderer.start()

    def load_default_when_ready():
        if shutting_down:
            return

        if renderer.authenticated.is_set():
            renderer.send("load", path=DEFAULT_IMAGE)
            renderer.send("size", value=current_size)
            renderer.send("speed", value=current_speed)
        elif renderer.process and renderer.process.poll() is None:
            root.after(100, load_default_when_ready)

    root.after(100, load_default_when_ready)
    root.bind("<Escape>", lambda _event: shutdown())
    root.protocol("WM_DELETE_WINDOW", shutdown)
    root.mainloop()


if __name__ == "__main__":
    args = sys.argv[1:]

    if len(args) >= 4 and args[0] == "--kdesktop-renderer":
        renderer_process(args[1], args[2], args[3])
    else:
        run_controller()
