import Quartz
import LaunchServices
import Quartz.CoreGraphics as CG
import datetime
import sys
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, colorchooser
from PIL import Image, ImageTk, ImageDraw, ImageFilter
import traceback
import io

# For copying to clipboard (macOS only)
try:
    from AppKit import NSPasteboard, NSImage
    from Foundation import NSData
except ImportError:
    NSPasteboard = None
    NSImage = None
    NSData = None

# ====================== Updated Style Constants ======================
DARK_BG = "#0A0A0A"  # Darker background
DARK_FG = "#F5F5F5"  # Brighter text
ACCENT_COLOR = "#30C2FF"  # Modern accent color
SLIDER_TROUGH = "#303030"
FONT_NAME = "SF Pro Display"  # Apple's system font
TOOLTIP_BG = "#252525"
SHADOW_COLOR = (0, 0, 0, 100)  # Base shadow color with alpha

# ====================== Icon Paths ======================
ICONS = {
    "camera": "icons/camera.png",
    "crop": "icons/crop.png",
    "undo": "icons/undo.png",
    "redo": "icons/redo.png",
    "color": "icons/palette.png",
    "image": "icons/image.png",
    "save": "icons/save.png",
    "copy": "icons/copy.png",
    "shadow": "icons/shadow.png"  # New shadow icon
}

# ====================== Global Hotkey (Cmd+8) ======================
COMMAND_FLAG_MASK = 1 << 20
DIGIT_8_KEY_CODE = 28

def _tap_callback(proxy, event_type, event, refcon):
    if event_type == Quartz.kCGEventKeyDown:
        flags = Quartz.CGEventGetFlags(event)
        keyCode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        is_command_down = bool(flags & COMMAND_FLAG_MASK)
        if is_command_down and keyCode == DIGIT_8_KEY_CODE:
            if refcon and hasattr(refcon, "on_global_hotkey"):
                refcon.on_global_hotkey()
    return event

class GlobalHotkeyListener:
    def __init__(self, owner):
        self.owner = owner
        self.eventTap = None

    def start(self):
        event_mask = Quartz.kCGEventMaskForAllEvents
        self.eventTap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            event_mask,
            _tap_callback,
            self.owner
        )
        if not self.eventTap:
            print("ERROR: Could not create event tap. Check Accessibility perms.")
            sys.exit(1)

        runLoopSource = Quartz.CFMachPortCreateRunLoopSource(None, self.eventTap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(),
            runLoopSource,
            Quartz.kCFRunLoopCommonModes
        )
        Quartz.CGEventTapEnable(self.eventTap, True)

    def stop(self):
        if self.eventTap:
            Quartz.CGEventTapEnable(self.eventTap, False)
            self.eventTap = None

# ====================== Modern UI Components ======================
class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        self.widget.bind("<Enter>", self.show_tip)
        self.widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tip_window or not self.text:
            return
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, background=TOOLTIP_BG,
                         foreground=DARK_FG, relief=tk.SOLID, borderwidth=1,
                         font=(FONT_NAME, 10))
        label.pack()

    def hide_tip(self, event=None):
        tw = self.tip_window
        self.tip_window = None
        if tw:
            tw.destroy()

class ModernSlider(ttk.Frame):
    def __init__(self, parent, label, from_, to, command):
        super().__init__(parent)
        self.command = command
        self.label = ttk.Label(self, text=label, font=(FONT_NAME, 9))
        self.label.pack(anchor="w")
        
        self.slider = ttk.Scale(self, from_=from_, to=to, command=self._update_value)
        self.slider.pack(fill=tk.X)
        
        self.value_label = ttk.Label(self, text="0", font=(FONT_NAME, 9))
        self.value_label.pack(anchor="e")
    
    def _update_value(self, value):
        self.value_label.config(text=f"{int(float(value))}")
        self.command(int(float(value)))
    
    def set(self, value):
        self.slider.set(value)
        self.value_label.config(text=str(int(value)))

class ShadowControls(ttk.LabelFrame):
    def __init__(self, parent, command):
        super().__init__(parent, text="Shadow", padding=10)
        self.command = command
        
        self.toggle_var = tk.BooleanVar(value=True)
        self.toggle_btn = ttk.Checkbutton(
            self, 
            image=app.icons['shadow'],
            variable=self.toggle_var,
            command=self._update
        )
        self.toggle_btn.grid(row=0, column=0, padx=5)
        ToolTip(self.toggle_btn, "Toggle Shadow")
        
        self.slider = ModernSlider(self, "Opacity:", 0, 100, self._update)
        self.slider.set(30)
        self.slider.grid(row=0, column=1, padx=5, sticky="ew")
    
    def _update(self, value=None):
        self.command(
            self.toggle_var.get(),
            self.slider.slider.get()
        )

# ====================== Image Processing Functions ======================
def capture_screenshot(filename="temp_screenshot.png"):
    display_id = CG.CGMainDisplayID()
    rect = CG.CGDisplayBounds(display_id)
    img = CG.CGWindowListCreateImage(
        rect,
        CG.kCGWindowListOptionOnScreenOnly,
        CG.kCGNullWindowID,
        CG.kCGWindowImageDefault
    )
    dest = Quartz.CGImageDestinationCreateWithURL(
        Quartz.CFURLCreateWithFileSystemPath(None, filename, Quartz.kCFURLPOSIXPathStyle, False),
        LaunchServices.kUTTypePNG,
        1,
        None
    )
    Quartz.CGImageDestinationAddImage(dest, img, None)
    Quartz.CGImageDestinationFinalize(dest)
    return filename

def round_image(pil_image, corner_radius=20):
    if corner_radius <= 0:
        return pil_image
    w, h = pil_image.size
    mask = Image.new('L', (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, w, h], corner_radius, fill=255)
    out = pil_image.copy()
    out.putalpha(mask)
    return out

def add_background(fg_image, bg_mode="color", color=(255, 255, 255, 255),
                   bg_image=None, padding=20, shadow_enabled=True,
                   shadow_opacity=30, shadow_offset=(8, 8)):
    # Create shadow if enabled
    shadow_layer = None
    if shadow_enabled:
        shadow = Image.new("RGBA", fg_image.size, (0, 0, 0, shadow_opacity))
        shadow_blur = shadow.filter(ImageFilter.GaussianBlur(radius=10))
        
        # Create shadow canvas
        shadow_w = fg_image.width + 2 * padding + shadow_offset[0]
        shadow_h = fg_image.height + 2 * padding + shadow_offset[1]
        shadow_canvas = Image.new("RGBA", (shadow_w, shadow_h), (0, 0, 0, 0))
        shadow_canvas.paste(shadow_blur, (padding + shadow_offset[0], 
                                        padding + shadow_offset[1]))
    
    # Create background canvas
    w_fg, h_fg = fg_image.size
    new_w = w_fg + 2 * padding
    new_h = h_fg + 2 * padding
    
    if bg_mode == "image" and bg_image:
        back = bg_image.resize((new_w, new_h), Image.LANCZOS).convert("RGBA")
    else:
        back = Image.new("RGBA", (new_w, new_h), color)
    
    # Composite elements
    if shadow_enabled:
        back = Image.alpha_composite(
            Image.alpha_composite(back, shadow_canvas), 
            add_background(fg_image, "color", (0, 0, 0, 0), padding=padding)
        )
    
    back.paste(fg_image, (padding, padding), fg_image)
    return back

# ====================== Screenshot Editor ======================
class ScreenshotEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("ShutterPy Pro")
        self._configure_styles()
        self._create_ui()
        self._setup_state()
        self.root.after(100, self.take_screenshot)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        if hasattr(self, 'hotkey_listener'):
            self.hotkey_listener.stop()
        self.root.destroy()

    def _configure_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure('.',
                             background=DARK_BG,
                             foreground=DARK_FG,
                             font=(FONT_NAME, 11))
        self.style.configure('TButton',
                             background=DARK_BG,
                             borderwidth=0,
                             focusthickness=0,
                             focuscolor=DARK_BG,
                             padding=6,
                             anchor="center")
        self.style.map('TButton',
                       background=[('active', '#2A2A2A'), ('!disabled', DARK_BG)],
                       relief=[('pressed', 'sunken'), ('!pressed', 'flat')])
        self.style.configure("Horizontal.TScale",
                             troughcolor=SLIDER_TROUGH,
                             sliderthickness=12,
                             sliderrelief="flat")
        self.style.configure('TCombobox',
                             fieldbackground=DARK_BG,
                             background=DARK_BG,
                             arrowcolor=DARK_FG,
                             bordercolor="#404040")

    def _create_ui(self):
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self.root, bg=DARK_BG, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        controls = ttk.Frame(self.root, padding=10)
        controls.grid(row=0, column=1, sticky="ns", padx=(0, 20), pady=20)
        
        self.icons = {}
        for name, path in ICONS.items():
            try:
                img = Image.open(path).resize((24, 24))
                self.icons[name] = ImageTk.PhotoImage(img)
            except Exception as e:
                print(f"Error loading icon {path}: {e}")
                self.icons[name] = None

        # UI Elements
        self.capture_btn = ttk.Button(controls, image=self.icons['camera'],
                                      command=self.take_screenshot)
        self.capture_btn.grid(row=0, column=0, pady=5)
        ToolTip(self.capture_btn, "Take Screenshot (Cmd+8)")
        
        self.crop_btn = ttk.Button(controls, image=self.icons['crop'],
                                   command=self.toggle_crop)
        self.crop_btn.grid(row=1, column=0, pady=5)
        ToolTip(self.crop_btn, "Crop")
        
        self.radius_slider = ModernSlider(controls, "Corner Radius:", 0, 200,
                                          self.on_radius_changed)
        self.radius_slider.grid(row=2, column=0, pady=10, sticky="ew")
        
        self.padding_slider = ModernSlider(controls, "Padding:", 0, 200,
                                           self.on_padding_changed)
        self.padding_slider.grid(row=3, column=0, pady=10, sticky="ew")
        
        bg_frame = ttk.LabelFrame(controls, text="Background", padding=10)
        bg_frame.grid(row=4, column=0, pady=10, sticky="ew")
        
        self.color_btn = ttk.Button(bg_frame, image=self.icons['color'],
                                    command=self.pick_bg_color)
        self.color_btn.grid(row=0, column=0, padx=5)
        ToolTip(self.color_btn, "Background Color")
        
        self.image_btn = ttk.Button(bg_frame, image=self.icons['image'],
                                    command=self.pick_bg_image)
        self.image_btn.grid(row=0, column=1, padx=5)
        ToolTip(self.image_btn, "Background Image")
        
        # Shadow controls
        self.shadow_controls = ShadowControls(controls, self.on_shadow_changed)
        self.shadow_controls.grid(row=5, column=0, pady=10, sticky="ew")
        
        undo_frame = ttk.Frame(controls)
        undo_frame.grid(row=6, column=0, pady=10)
        
        self.undo_btn = ttk.Button(undo_frame, image=self.icons['undo'],
                                   command=self.undo)
        self.undo_btn.grid(row=0, column=0, padx=5)
        ToolTip(self.undo_btn, "Undo (Cmd+Z)")
        
        self.redo_btn = ttk.Button(undo_frame, image=self.icons['redo'],
                                   command=self.redo)
        self.redo_btn.grid(row=0, column=1, padx=5)
        ToolTip(self.redo_btn, "Redo (Cmd+Shift+Z)")
        
        self.save_btn = ttk.Button(controls, image=self.icons['save'],
                                   command=self.save_image)
        self.save_btn.grid(row=7, column=0, pady=5)
        ToolTip(self.save_btn, "Save Image")
        
        self.copy_btn = ttk.Button(controls, image=self.icons['copy'],
                                   command=self.copy_final_to_clipboard)
        self.copy_btn.grid(row=8, column=0, pady=5)
        ToolTip(self.copy_btn, "Copy to Clipboard")

        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)

    def _setup_state(self):
        self.corner_radius = 30
        self.padding = 50
        self.bg_mode = "color"
        self.bg_color = (255, 255, 255, 255)
        self.bg_image = None
        self.original_image = None
        self.final_image = None
        self.is_cropping = False
        self.undo_stack = []
        self.redo_stack = []
        self.start_x = None
        self.start_y = None
        self.crop_rect_id = None
        self.canvas_scale_ratio = 1.0
        self.image_draw_offset = (0, 0)
        self.shadow_enabled = True
        self.shadow_opacity = 30
        
        self.radius_slider.set(self.corner_radius)
        self.padding_slider.set(self.padding)
        
        self.root.bind_all("<Command-z>", self.on_cmd_z_undo)
        self.root.bind_all("<Command-Shift-z>", self.on_cmd_shift_z_redo)
        
        self.menu = tk.Menu(self.root, tearoff=0, bg=TOOLTIP_BG, fg=DARK_FG)
        self.menu.add_command(label="Copy Image", command=self.copy_final_to_clipboard)
        self.canvas.bind("<Button-2>", self.on_right_click)
        self.canvas.bind("<Button-3>", self.on_right_click)

    def take_screenshot(self):
        if self.original_image:
            self.push_undo()
            self.redo_stack.clear()
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"screenshot_{ts}.png"
        capture_screenshot(fname)
        self.original_image = Image.open(fname).convert("RGBA")
        self.apply_effects()

    def apply_effects(self):
        if not self.original_image:
            return
        sc_rounded = round_image(self.original_image, self.corner_radius)
        with_bg = add_background(
            sc_rounded, 
            self.bg_mode, 
            self.bg_color, 
            self.bg_image, 
            self.padding,
            shadow_enabled=self.shadow_enabled,
            shadow_opacity=self.shadow_opacity
        )
        final = round_image(with_bg, self.corner_radius)
        self.final_image = final
        self.show_in