# py -m PyInstaller --onefile --noconsole main.py



import json
import html
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


class TTSWorker:
    """Owns the pyttsx3 engine on one background thread."""

    def __init__(self, callback):
        self.callback = callback
        self.commands = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def send(self, command, **data):
        self.commands.put((command, data))

    @staticmethod
    def _voice_gender(voice):
        details = " ".join([
            str(getattr(voice, "name", "")),
            str(getattr(voice, "id", "")),
            str(getattr(voice, "gender", ""))
        ]).lower()

        if any(x in details for x in (
            "zira", "hazel", "susan", "samantha",
            "victoria", "karen", "female"
        )) or "woman" in details:
            return "female"

        if any(x in details for x in (
            "david", "mark", "george", "james",
            "daniel", "male"
        )) or "man" in details:
            return "male"

        return "unknown"

    @staticmethod
    def _sentences(text):
        import re

        # Convert decimal numbers before splitting sentences.
        # Example: 0.999 -> 0 dot 9 9 9
        text = re.sub(
            r'(\d+)\.(\d+)(?!\w)',
            lambda m: (
                m.group(1) + " dot " + " ".join(m.group(2))
            ),
            text
        )

        # Split at periods and newlines.
        # Decimal points have already been converted.
        sentences = re.split(r'(?<=\.)\s*|\n+', text)

        return [
            sentence.strip()
            for sentence in sentences
            if sentence.strip()
        ]

    def _run(self):
        try:
            import pyttsx3

            engine = pyttsx3.init()

            voices = engine.getProperty("voices") or []

            voice_data = [
                {
                    "id": str(getattr(v, "id", "")),
                    "name": str(
                        getattr(v, "name", "")
                        or getattr(v, "id", "System voice")
                    ),
                    "gender": self._voice_gender(v)
                }
                for v in voices
            ]

            self.callback("ready", voices=voice_data)

            engine.startLoop(False)

            try:
                import pythoncom
            except ImportError:
                pythoncom = None

            state = {
                "sentences": [],
                "index": 0,
                "loop": False,
                "sentence": "",
                "advance": False
            }

            def on_word(name, location, length):
                self.callback(
                    "word",
                    sentence=state["sentence"],
                    location=int(location),
                    length=int(length)
                )

            def on_finished(name, completed):
                state["advance"] = True

            engine.connect("started-word", on_word)
            engine.connect("finished-utterance", on_finished)

            def queue_sentence():
                if state["sentences"]:
                    state["index"] %= len(state["sentences"])

                    state["sentence"] = state["sentences"][
                        state["index"]
                    ]

                    self.callback(
                        "sentence",
                        text=state["sentence"]
                    )

                    engine.say(state["sentence"])

            running = True

            while running:
                try:
                    command, data = self.commands.get(timeout=0.01)

                    if command == "shutdown":
                        engine.stop()
                        running = False

                    elif command == "stop":
                        state.update(
                            loop=False,
                            sentences=[],
                            advance=False
                        )

                        engine.stop()
                        self.callback("clear")

                    elif command in ("speak", "update_text"):
                        engine.stop()

                        state["sentences"] = self._sentences(
                            data.get("text", "").strip()
                        )

                        state["index"] = 0
                        state["loop"] = bool(state["sentences"])
                        state["advance"] = False

                        self.callback("clear")
                        queue_sentence()

                    elif command == "voice":
                        gender = data.get("gender", "female")

                        candidates = [
                            v for v in voices
                            if self._voice_gender(v) == gender
                        ]

                        if candidates:
                            engine.setProperty(
                                "voice",
                                candidates[0].id
                            )

                            self.callback(
                                "voice_selected",
                                gender=gender,
                                name=str(
                                    getattr(
                                        candidates[0],
                                        "name",
                                        candidates[0].id
                                    )
                                )
                            )
                        else:
                            self.callback(
                                "voice_unavailable",
                                gender=gender
                            )

                    elif command == "volume":
                        engine.setProperty(
                            "volume",
                            max(
                                0.0,
                                min(
                                    1.0,
                                    float(data.get("value", 1.0))
                                )
                            )
                        )

                except queue.Empty:
                    pass

                engine.iterate()

                if state["advance"]:
                    state["advance"] = False

                    if state["loop"] and state["sentences"]:
                        state["index"] = (
                            state["index"] + 1
                        ) % len(state["sentences"])

                        queue_sentence()
                    else:
                        self.callback("clear")

                if pythoncom is not None:
                    pythoncom.PumpWaitingMessages()

            engine.endLoop()

        except Exception as error:
            self.callback("error", error=str(error))


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
                Qt.WidgetAttribute.WA_TranslucentBackground,
                True
            )

            self.setAttribute(
                Qt.WidgetAttribute.WA_NoSystemBackground,
                True
            )

            self.setStyleSheet("background: transparent;")

            self.label = QLabel(self)

            self.label.setStyleSheet("background: transparent;")

            self.label.setAttribute(
                Qt.WidgetAttribute.WA_TranslucentBackground,
                True
            )

            self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            self.bubble = QLabel(self)
            self.bubble.setWordWrap(True)

            self.bubble.setAlignment(
                Qt.AlignmentFlag.AlignCenter
            )

            self.bubble.setTextFormat(
                Qt.TextFormat.RichText
            )

            self.bubble.setStyleSheet(
                "QLabel { background: #FFF8D9; color: #202020; "
                "border: 2px solid #333333; border-radius: 12px; "
                "padding: 8px; font: 10pt 'Tahoma'; }"
            )

            self.bubble.hide()
            self.bubble_height = 76
            self.current_sentence = ""

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

            elif command == "tts_sentence":
                self.current_sentence = packet.get("text", "")
                self.update_bubble()

            elif command == "tts_word":
                self.update_bubble(
                    packet.get("location", 0),
                    packet.get("length", 0)
                )

            elif command == "tts_clear":
                self.current_sentence = ""
                self.bubble.hide()

                if self.frames:
                    self.show_frame()

            elif command == "exit":
                self.close()

        def update_bubble(self, word_start=None, word_length=0):
            if not self.current_sentence:
                self.bubble.hide()
                return

            sentence = self.current_sentence

            if word_start is not None and word_length > 0:
                a = max(
                    0,
                    min(len(sentence), int(word_start))
                )

                b = max(
                    a,
                    min(len(sentence), a + int(word_length))
                )

                safe = (
                    html.escape(sentence[:a])
                    + '<span style="background:#FFE066;'
                    'color:#111111;font-weight:bold;">'
                    + html.escape(sentence[a:b])
                    + '</span>'
                    + html.escape(sentence[b:])
                )

            else:
                safe = html.escape(sentence)

            self.bubble.setText(safe)
            self.bubble.show()
            self.show_frame()

        def load_image(self, path):
            try:
                image = Image.open(path)

                frames = []
                durations = []

                for i in range(getattr(image, "n_frames", 1)):
                    image.seek(i)

                    frames.append(
                        image.convert("RGBA").copy()
                    )

                    durations.append(
                        max(
                            20,
                            int(image.info.get("duration", 100) or 100)
                        )
                    )

                if not frames:
                    raise ValueError(
                        "No frames found in image."
                    )

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

            width = max(
                1,
                int(frame.width * self.scale)
            )

            height = max(
                1,
                int(frame.height * self.scale)
            )

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

            self.label.setPixmap(
                QPixmap.fromImage(qimage)
            )

            self.label.resize(width, height)

            if self.current_sentence:
                bubble_width = min(
                    520,
                    max(280, width)
                )

                bubble_height = max(
                    self.bubble_height,
                    self.bubble.heightForWidth(bubble_width)
                )

                self.bubble.setGeometry(
                    0,
                    0,
                    bubble_width,
                    bubble_height
                )

                self.label.move(
                    max(0, (bubble_width - width) // 2),
                    bubble_height + 8
                )

                self.resize(
                    max(width, bubble_width),
                    height + bubble_height + 8
                )

            else:
                self.bubble.hide()
                self.label.move(0, 0)
                self.resize(width, height)

        def schedule_frame(self):
            if len(self.frames) < 2:
                self.timer.stop()
                return

            delay = int(
                self.durations[self.frame_index]
                / max(0.05, self.speed)
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
                    event.globalPosition().toPoint()
                    - self.drag_offset
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

    connection = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

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
            socket.AF_INET,
            socket.SOCK_STREAM
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
            options["creationflags"] = (
                subprocess.CREATE_NO_WINDOW
            )

            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= (
                subprocess.STARTF_USESHOWWINDOW
            )

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

            self.messages.put({
                "event": "connected"
            })

            for line in reader:
                try:
                    self.messages.put(
                        json.loads(line.decode())
                    )

                except (ValueError, UnicodeDecodeError):
                    pass

        except Exception as error:
            if not self.closed:
                self.messages.put({
                    "event": "renderer_error",
                    "error": str(error)
                })

        finally:
            self.messages.put({
                "event": "disconnected"
            })

    def send(self, command, **data):
        if self.connection is None or self.closed:
            return

        packet = {
            "command": command,
            **data
        }

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
                self.callback(
                    self.messages.get_nowait()
                )

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
                self.connection.shutdown(
                    socket.SHUT_RDWR
                )

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
    tts_window = None

    tts_enabled = False
    tts_text_widget = None
    tts_voice_choice = None
    tts_volume_scale = None
    tts_edit_job = None
    tts_loop_active = False
    last_tts_text = ""

    tts_voice_names = {
        "female": [],
        "male": []
    }

    current_size = 1.0
    current_speed = 1.0
    shutting_down = False

    tts_worker = TTSWorker(
        lambda event, **data: root.after(
            0,
            handle_tts_event,
            event,
            data
        )
    )

    def shutdown():
        nonlocal shutting_down

        if shutting_down:
            return

        shutting_down = True

        if renderer:
            renderer.close()

        tts_worker.send("shutdown")

        try:
            root.destroy()

        except tk.TclError:
            pass

    def change_size(value):
        nonlocal current_size

        current_size = float(value)

        if renderer:
            renderer.send(
                "size",
                value=current_size
            )

    def change_speed(value):
        nonlocal current_speed

        current_speed = float(value)

        if renderer:
            renderer.send(
                "speed",
                value=current_speed
            )

    def close_settings():
        nonlocal settings_window

        if settings_window:
            try:
                settings_window.destroy()

            except tk.TclError:
                pass

        settings_window = None

    def close_tts_window():
        nonlocal tts_window

        # Closing the window does NOT stop playback.
        # The TTS worker continues in the background.

        if tts_window:
            try:
                tts_window.destroy()

            except tk.TclError:
                pass

        tts_window = None

    def handle_tts_event(event, data):
        if shutting_down:
            return

        if event == "ready":
            for voice in data.get("voices", []):
                gender = voice.get("gender", "unknown")

                if gender in tts_voice_names:
                    tts_voice_names[gender].append(voice)

            # Select the best available female voice by default.
            tts_worker.send(
                "voice",
                gender="female"
            )

            refresh_voice_list()

        elif event == "sentence":
            if renderer:
                renderer.send(
                    "tts_sentence",
                    text=data.get("text", "")
                )

        elif event == "word":
            if renderer:
                renderer.send(
                    "tts_word",
                    location=data.get("location", 0),
                    length=data.get("length", 0)
                )

        elif event == "clear":
            if renderer:
                renderer.send("tts_clear")

        elif event == "error":
            messagebox.showerror(
                "Text-to-Speech Error",
                "Could not start pyttsx3. Install it with:\n\n"
                "python -m pip install pyttsx3\n\n"
                + data.get("error", ""),
                parent=root
            )

        elif event == "voice_unavailable":
            if tts_window and tts_window.winfo_exists():
                messagebox.showinfo(
                    "Voice unavailable",
                    "No "
                    + data.get("gender", "selected")
                    + " voice was detected on this computer. "
                    "The system voice will be used.",
                    parent=tts_window
                )

    def refresh_voice_list():
        if (
            not tts_window
            or not tts_window.winfo_exists()
            or tts_voice_choice is None
        ):
            return

        tts_voice_choice["values"] = (
            "Female",
            "Male"
        )

        if not tts_voice_choice.get():
            tts_voice_choice.set("Female")

    def set_tts_voice(_event=None):
        if tts_enabled and tts_voice_choice:
            gender = (
                "male"
                if tts_voice_choice.get().lower() == "male"
                else "female"
            )

            tts_worker.send(
                "voice",
                gender=gender
            )

    def speak_text():
        nonlocal tts_loop_active, last_tts_text

        if not tts_enabled:
            return

        text = tts_text_widget.get(
            "1.0",
            "end-1c"
        ).strip()

        if not text:
            messagebox.showinfo(
                "Nothing to say",
                "Write some text first.",
                parent=tts_window
            )

            return

        set_tts_voice()

        tts_loop_active = True
        last_tts_text = text

        tts_worker.send(
            "speak",
            text=text
        )

    def stop_speaking():
        nonlocal tts_loop_active

        tts_loop_active = False
        tts_worker.send("stop")

    def on_tts_text_changed(_event=None):
        nonlocal tts_edit_job

        if tts_edit_job is not None:
            root.after_cancel(tts_edit_job)

        if tts_loop_active:
            tts_edit_job = root.after(
                600,
                apply_tts_text_change
            )

    def apply_tts_text_change():
        nonlocal tts_edit_job, last_tts_text

        tts_edit_job = None

        if (
            not tts_loop_active
            or not tts_text_widget
            or not tts_text_widget.winfo_exists()
        ):
            return

        text = tts_text_widget.get(
            "1.0",
            "end-1c"
        ).strip()

        if text and text != last_tts_text:
            last_tts_text = text

            set_tts_voice()

            tts_worker.send(
                "update_text",
                text=text
            )

    def change_tts_volume(value):
        tts_worker.send(
            "volume",
            value=float(value)
        )

    def open_tts_window():
        nonlocal tts_window
        nonlocal tts_text_widget
        nonlocal tts_voice_choice
        nonlocal tts_volume_scale

        if tts_window and tts_window.winfo_exists():
            tts_window.deiconify()
            tts_window.lift()
            return

        from tkinter import ttk

        window = tk.Toplevel(root)
        tts_window = window

        window.title("Text-to-Speech (using pyttsx3)")
        window.geometry("410x410")
        window.minsize(340, 280)
        window.attributes("-topmost", True)
        window.configure(bg="#ECE9D8")

        tk.Label(
            window,
            text="Write something for your character to say",
            bg="#ECE9D8",
            fg="#1941A5",
            font=("Tahoma", 10, "bold")
        ).pack(
            anchor="w",
            padx=12,
            pady=(12, 6)
        )

        text_frame = tk.Frame(
            window,
            bg="#ECE9D8"
        )

        text_frame.pack(
            fill="both",
            expand=True,
            padx=12
        )

        text_scroll = tk.Scrollbar(text_frame)
        text_scroll.pack(
            side="right",
            fill="y"
        )

        tts_text_widget = tk.Text(
            text_frame,
            wrap="word",
            height=8,
            yscrollcommand=text_scroll.set,
            font=("Tahoma", 10)
        )

        tts_text_widget.pack(
            side="left",
            fill="both",
            expand=True
        )

        text_scroll.config(
            command=tts_text_widget.yview
        )

        tts_text_widget.bind(
            "<<Modified>>",
            lambda event: (
                tts_text_widget.edit_modified(False),
                on_tts_text_changed(event)
            )
        )

        tts_text_widget.edit_modified(False)

        volume_row = tk.Frame(
            window,
            bg="#ECE9D8"
        )

        volume_row.pack(
            fill="x",
            padx=12,
            pady=(8, 2)
        )

        tk.Label(
            volume_row,
            text="TTS Volume:",
            bg="#ECE9D8",
            font=("Tahoma", 9, "bold")
        ).pack(side="left")

        tts_volume_scale = tk.Scale(
            volume_row,
            from_=0,
            to=100,
            orient="horizontal",
            command=lambda value: change_tts_volume(
                float(value) / 100.0
            ),
            bg="#ECE9D8",
            troughcolor="#A6C8F0",
            highlightthickness=0,
            showvalue=True,
            length=220
        )

        tts_volume_scale.set(100)

        tts_volume_scale.pack(
            side="left",
            fill="x",
            expand=True
        )

        voice_row = tk.Frame(
            window,
            bg="#ECE9D8"
        )

        voice_row.pack(
            fill="x",
            padx=12,
            pady=10
        )

        tk.Label(
            voice_row,
            text="Voice:",
            bg="#ECE9D8",
            font=("Tahoma", 9, "bold")
        ).pack(side="left")

        tts_voice_choice = ttk.Combobox(
            voice_row,
            values=("Female", "Male"),
            state="readonly",
            width=12
        )

        tts_voice_choice.set("Female")

        tts_voice_choice.pack(
            side="left",
            padx=8
        )

        tts_voice_choice.bind(
            "<<ComboboxSelected>>",
            set_tts_voice
        )

        button_row = tk.Frame(
            window,
            bg="#ECE9D8"
        )

        button_row.pack(
            fill="x",
            padx=12,
            pady=(0, 12)
        )

        tk.Button(
            button_row,
            text="Speak",
            command=speak_text,
            width=12,
            bg="#D8E5F5",
            relief="raised"
        ).pack(side="left")

        tk.Button(
            button_row,
            text="Stop",
            command=stop_speaking,
            width=10,
            bg="#F2DADA",
            relief="raised"
        ).pack(
            side="left",
            padx=8
        )

        tk.Button(
            button_row,
            text="Close",
            command=close_tts_window,
            width=10,
            relief="raised"
        ).pack(side="right")

        window.protocol(
            "WM_DELETE_WINDOW",
            close_tts_window
        )

        if tts_voice_names["female"]:
            refresh_voice_list()

    def toggle_tts(enabled):
        nonlocal tts_enabled

        tts_enabled = bool(enabled)

        if tts_enabled:
            open_tts_window()

        else:
            # Unchecking TTS stops all playback.
            tts_worker.send("stop")
            close_tts_window()

    def choose_image():
        if not settings_window:
            return

        path = filedialog.askopenfilename(
            parent=settings_window,
            title="Choose Your Character",
            filetypes=[
                (
                    "Supported images",
                    "*.gif *.png *.jpg *.jpeg *.bmp *.webp"
                ),
                ("All files", "*.*")
            ]
        )

        if path and renderer:
            renderer.send(
                "load",
                path=path
            )

    def reset_image():
        if os.path.exists(DEFAULT_IMAGE):
            renderer.send(
                "load",
                path=DEFAULT_IMAGE
            )

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
        window.geometry(
            f"285x490+{int(x)}+{int(y)}"
        )

        window.resizable(False, False)
        window.attributes("-topmost", True)

        bg = "#ECE9D8"
        blue = "#316AC5"
        dark_blue = "#1941A5"

        window.configure(bg=bg)

        outer = tk.Frame(
            window,
            bg="white",
            bd=2,
            relief="raised"
        )

        outer.pack(
            fill="both",
            expand=True,
            padx=3,
            pady=3
        )

        title_bar = tk.Frame(
            outer,
            bg=blue,
            height=28
        )

        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)

        tk.Label(
            title_bar,
            text="Character Settings",
            bg=blue,
            fg="white",
            font=("Tahoma", 9, "bold")
        ).pack(
            side="left",
            padx=8,
            pady=4
        )

        panel = tk.Frame(
            outer,
            bg=bg,
            padx=12,
            pady=10
        )

        panel.pack(
            fill="both",
            expand=True
        )

        tk.Label(
            panel,
            text="Change character size and playback speed",
            bg=bg,
            fg=dark_blue,
            font=("Tahoma", 7, "bold")
        ).pack(
            anchor="w",
            pady=(2, 5)
        )

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

        size_slider.pack(
            fill="x",
            pady=(0, 8)
        )

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

        speed_slider.pack(
            fill="x",
            pady=(0, 10)
        )

        tk.Label(
            panel,
            text="Character Appearance",
            bg=bg,
            fg=dark_blue,
            font=("Tahoma", 9, "bold")
        ).pack(
            anchor="w",
            pady=(2, 5)
        )

        tk.Button(
            panel,
            text="Choose Image / GIF",
            command=choose_image,
            bg=bg,
            font=("Tahoma", 8),
            relief="raised",
            bd=2
        ).pack(
            fill="x",
            pady=3
        )

        tk.Button(
            panel,
            text="Reset to Default",
            command=reset_image,
            bg=bg,
            font=("Tahoma", 8),
            relief="raised",
            bd=2
        ).pack(
            fill="x",
            pady=3
        )

        tk.Label(
            panel,
            text="Text-to-Speech",
            bg=bg,
            fg=dark_blue,
            font=("Tahoma", 9, "bold")
        ).pack(
            anchor="w",
            pady=(10, 3)
        )

        tts_var = tk.BooleanVar(
            value=tts_enabled
        )

        tk.Checkbutton(
            panel,
            text="Turn TTS on (opens text window)",
            variable=tts_var,
            command=lambda: toggle_tts(
                tts_var.get()
            ),
            bg=bg,
            activebackground=bg,
            font=("Tahoma", 8),
            anchor="w"
        ).pack(
            fill="x",
            pady=(0, 3)
        )

        tk.Button(
            panel,
            text="Open TTS Window",
            command=lambda: (
                tts_var.set(True),
                toggle_tts(True),
                open_tts_window()
            ),
            bg=bg,
            font=("Tahoma", 8),
            relief="raised",
            bd=2
        ).pack(
            fill="x",
            pady=3
        )

        buttons = tk.Frame(
            panel,
            bg=bg
        )

        buttons.pack(
            fill="x",
            pady=(8, 0)
        )

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
        ).pack(
            anchor="w",
            pady=(2, 5)
        )

        tk.Label(
            panel,
            text="KTesktop by @KTo",
            bg=bg,
            fg=dark_blue,
            font=("Tahoma", 5, "bold")
        ).pack(
            anchor="w",
            pady=(2, 5)
        )

        window.protocol(
            "WM_DELETE_WINDOW",
            close_settings
        )

    def handle_message(packet):
        event = packet.get("event")

        if event == "open_settings":
            x = packet.get("x", 100)
            y = packet.get("y", 100)
            width = packet.get("width", 0)

            open_settings(
                x + width + 10,
                y
            )

        elif event == "image_error":
            messagebox.showerror(
                "Image Error",
                packet.get(
                    "error",
                    "Could not load image."
                ),
                parent=settings_window or root
            )

        elif event == "renderer_error":
            messagebox.showerror(
                "Renderer Error",
                packet.get(
                    "error",
                    "The renderer failed."
                ),
                parent=root
            )

            shutdown()

        elif event in (
            "exit_requested",
            "renderer_process_exited"
        ):
            shutdown()

    if not os.path.exists(DEFAULT_IMAGE):
        messagebox.showerror(
            "Missing Default",
            "Please put test.gif next to main.py.",
            parent=root
        )

        root.destroy()
        return

    renderer = RendererController(
        root,
        handle_message
    )

    renderer.start()

    def load_default_when_ready():
        if shutting_down:
            return

        if renderer.authenticated.is_set():
            renderer.send(
                "load",
                path=DEFAULT_IMAGE
            )

            renderer.send(
                "size",
                value=current_size
            )

            renderer.send(
                "speed",
                value=current_speed
            )

        elif (
            renderer.process
            and renderer.process.poll() is None
        ):
            root.after(
                100,
                load_default_when_ready
            )

    root.after(
        100,
        load_default_when_ready
    )

    root.bind(
        "<Escape>",
        lambda _event: shutdown()
    )

    root.protocol(
        "WM_DELETE_WINDOW",
        shutdown
    )

    root.mainloop()


if __name__ == "__main__":
    args = sys.argv[1:]

    if (
        len(args) >= 4
        and args[0] == "--kdesktop-renderer"
    ):
        renderer_process(
            args[1],
            args[2],
            args[3]
        )

    else:
        run_controller()
