# py -m PyInstaller --onefile --noconsole main.py


import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import os
import sys
import ctypes


if getattr(sys, "frozen", False):
    app_folder = os.path.dirname(sys.executable)
else:
    app_folder = os.path.dirname(os.path.abspath(__file__))

default_gif_path = os.path.join(app_folder, "test.gif")
icon_path = os.path.join(app_folder, "buddy.ico")

root = tk.Tk()
root.overrideredirect(True)
root.attributes("-transparentcolor", "white")
root.attributes("-topmost", True)

if os.path.exists(icon_path):
    root.iconbitmap(icon_path)

root.update_idletasks()

if sys.platform == "win32":
    user32 = ctypes.windll.user32
    hwnd = user32.GetParent(root.winfo_id())

    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_APPWINDOW = 0x00040000

    styles = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    styles = styles & ~WS_EX_TOOLWINDOW
    styles = styles | WS_EX_APPWINDOW

    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, styles)

    user32.SetWindowPos(
        hwnd,
        0,
        0, 0, 0, 0,
        0x0027
    )

original_frames = []
frame_durations = []
frames = []

current_frame = 0
size_scale = 1.0
speed = 1.0
animation_job = None
settings_window = None

label = tk.Label(
    root,
    bg="white",
    borderwidth=0
)
label.pack()


def resize_frames():
    global frames

    frames = []

    for frame in original_frames:
        width = max(1, int(frame.width * size_scale))
        height = max(1, int(frame.height * size_scale))

        resized = frame.resize(
            (width, height),
            Image.Resampling.LANCZOS
        )

        frames.append(ImageTk.PhotoImage(resized))


def animate():
    global current_frame
    global animation_job

    if not frames:
        animation_job = None
        return

    label.config(image=frames[current_frame])

    if len(frames) == 1:
        animation_job = None
        return

    duration = frame_durations[current_frame]
    current_frame = (current_frame + 1) % len(frames)

    adjusted_duration = max(
        10,
        int(duration / speed)
    )

    animation_job = root.after(
        adjusted_duration,
        animate
    )


def load_character(image_path):
    global original_frames
    global frame_durations
    global current_frame
    global animation_job

    try:
        image = Image.open(image_path)

        new_frames = []
        new_durations = []

        frame_count = getattr(image, "n_frames", 1)

        for i in range(frame_count):
            image.seek(i)

            frame = image.convert("RGBA").copy()
            new_frames.append(frame)

            duration = image.info.get("duration", 100)
            new_durations.append(max(20, int(duration or 100)))

        if not new_frames:
            raise ValueError("No image frames found.")

        if animation_job is not None:
            root.after_cancel(animation_job)
            animation_job = None

        original_frames = new_frames
        frame_durations = new_durations
        current_frame = 0

        resize_frames()

        label.config(image=frames[0])

        animate()

        return True

    except Exception as error:
        messagebox.showerror(
            "Image Error",
            f"Could not load image:\n\n{error}",
            parent=root
        )
        return False


def change_size(value):
    global size_scale

    size_scale = float(value)

    resize_frames()

    if frames:
        label.config(image=frames[current_frame])


def change_speed(value):
    global speed, animation_job

    speed = float(value)

    if animation_job is not None:
        root.after_cancel(animation_job)
        animation_job = None
        animate()


def choose_image():
    file_path = filedialog.askopenfilename(
        parent=settings_window,
        title="Choose Your Buddy",
        filetypes=[
            ("Supported images", "*.gif *.png *.jpg *.jpeg *.bmp *.webp"),
            ("GIF files", "*.gif"),
            ("PNG files", "*.png"),
            ("JPEG files", "*.jpg *.jpeg"),
            ("All files", "*.*")
        ]
    )

    if file_path:
        load_character(file_path)


def reset_character():
    if os.path.exists(default_gif_path):
        load_character(default_gif_path)
    else:
        messagebox.showerror(
            "Missing Default",
            "Could not find test.gif next to the application.",
            parent=settings_window
        )


def start_drag(event):
    root.x = event.x
    root.y = event.y


def drag(event):
    x = root.winfo_pointerx() - root.x
    y = root.winfo_pointery() - root.y

    root.geometry(f"+{x}+{y}")


label.bind("<Button-1>", start_drag)
label.bind("<B1-Motion>", drag)


def close_settings():
    global settings_window

    if settings_window is not None:
        try:
            settings_window.destroy()
        except tk.TclError:
            pass

        settings_window = None


def open_settings(event=None):
    global settings_window

    if settings_window is not None:
        try:
            if settings_window.winfo_exists():
                close_settings()
                return
        except tk.TclError:
            settings_window = None

    settings_window = tk.Toplevel(root)
    settings_window.title("Settings")
    settings_window.geometry("255x390")
    settings_window.resizable(False, False)
    settings_window.attributes("-topmost", True)

    root.update_idletasks()

    x = root.winfo_x() + root.winfo_width() + 10
    y = root.winfo_y()

    settings_window.geometry(f"+{x}+{y}")

    bg = "#ECE9D8"
    blue = "#316AC5"
    dark_blue = "#1941A5"
    text_color = "#222222"

    settings_window.configure(bg=bg)

    outer = tk.Frame(
        settings_window,
        bg="#FFFFFF",
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
        fg=text_color,
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
        fg=text_color,
        troughcolor="#A6C8F0",
        activebackground=blue,
        highlightthickness=0,
        bd=1,
        relief="sunken",
        font=("Tahoma", 8),
        showvalue=True,
        sliderlength=18
    )
    size_slider.set(size_scale)
    size_slider.pack(
        fill="x",
        pady=(0, 8)
    )

    tk.Label(
        panel,
        text="GIF Playback Speed",
        bg=bg,
        fg=text_color,
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
        fg=text_color,
        troughcolor="#A6C8F0",
        activebackground=blue,
        highlightthickness=0,
        bd=1,
        relief="sunken",
        font=("Tahoma", 8),
        showvalue=True,
        sliderlength=18
    )
    speed_slider.set(speed)
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
        fg=text_color,
        font=("Tahoma", 8),
        relief="raised",
        bd=2,
        activebackground="#D6E8FF"
    ).pack(
        fill="x",
        pady=3
    )

    tk.Button(
        panel,
        text="Reset to Default",
        command=reset_character,
        bg=bg,
        fg=text_color,
        font=("Tahoma", 8),
        relief="raised",
        bd=2,
        activebackground="#D6E8FF"
    ).pack(
        fill="x",
        pady=3
    )

    button_frame = tk.Frame(
        panel,
        bg=bg
    )
    button_frame.pack(
        fill="x",
        pady=(8, 0)
    )

    tk.Button(
        button_frame,
        text="OK",
        width=9,
        command=close_settings,
        bg=bg,
        fg=text_color,
        font=("Tahoma", 8),
        relief="raised",
        bd=2,
        activebackground="#D6E8FF"
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

    settings_window.protocol(
        "WM_DELETE_WINDOW",
        close_settings
    )

label.bind("<Button-3>", open_settings)

root.bind(
    "<Escape>",
    lambda event: root.destroy()
)

if not os.path.exists(default_gif_path):
    messagebox.showerror(
        "Missing Default",
        "Please put test.gif next to the application.",
        parent=root
    )
    root.destroy()
    raise SystemExit

load_character(default_gif_path)

root.mainloop()
