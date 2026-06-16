import tkinter as tk
import customtkinter as ctk

# ─────────────────────────────────────────────────────────────────────────────
#  _InfoBadge — compact ℹ icon with hover tooltip
# ─────────────────────────────────────────────────────────────────────────────

class _InfoBadge:
    """
    Replaces a plain CTkLabel info row with a small ℹ icon.
    The full text is shown in a popup tooltip when the user hovers over the icon.
    API-compatible with CTkLabel: supports .configure(text=...) and .pack(**kw).
    """

    _TIP_BG   = "#1a1a2e"
    _TIP_FG   = "#aaccee"
    _TIP_FONT = ("Helvetica", 10)

    def __init__(self, parent, width: int = 40):
        self._text = ""
        self._tip_win = None
        self._lbl = ctk.CTkLabel(
            parent,
            text="",
            width=width,
            font=ctk.CTkFont(size=11),
            text_color="#4f7bd9",
            cursor="question_arrow",
        )
        self._lbl.bind("<Enter>",  self._on_enter)
        self._lbl.bind("<Leave>",  self._on_leave)
        self._lbl.bind("<Motion>", self._on_motion)

    # ── Public API ──────────────────────────────────────────────────────────────
    def pack(self, **kw):
        self._lbl.pack(**kw)

    def configure(self, text: str = "", **_kw):
        """Update tooltip content.  Shows ℹ when text is non-empty."""
        self._text = text or ""
        self._lbl.configure(text="ℹ" if self._text else "")
        # Refresh live tooltip if already open
        if self._tip_win and self._text:
            self._refresh_tip_text()

    def _on_enter(self, event):
        if self._text:
            self._show_tip(event.x_root, event.y_root)

    def _on_motion(self, event):
        if self._tip_win:
            self._tip_win.wm_geometry(f"+{event.x_root + 14}+{event.y_root + 14}")

    def _on_leave(self, _event):
        self._hide_tip()

    def _show_tip(self, rx: int, ry: int):
        if self._tip_win:
            return
        tw = tk.Toplevel(self._lbl)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{rx + 14}+{ry + 14}")
        tw.configure(bg=self._TIP_BG)
        self._tip_label = tk.Label(
            tw,
            text=self._text,
            justify="left",
            bg=self._TIP_BG,
            fg=self._TIP_FG,
            relief="solid",
            bd=1,
            font=self._TIP_FONT,
            wraplength=560,
            padx=8, pady=5,
        )
        self._tip_label.pack()
        self._tip_win = tw

    def _refresh_tip_text(self):
        try:
            self._tip_label.configure(text=self._text)
        except Exception:
            pass

    def _hide_tip(self):
        if self._tip_win:
            try:
                self._tip_win.destroy()
            except Exception:
                pass
            self._tip_win = None

# ─────────────────────────────────────────────────────────────────────────────
#  CTkChip — Clickable toggle pill for detection criteria
# ─────────────────────────────────────────────────────────────────────────────

class CTkChip(ctk.CTkButton):
    def __init__(self, parent, text, variable=None, **kwargs):
        self.variable = variable
        self.active_color = kwargs.pop("active_color", "#1f538d")
        self.inactive_color = kwargs.pop("inactive_color", "#333333")
        self.active_hover = kwargs.pop("active_hover", "#14375d")
        self.inactive_hover = kwargs.pop("inactive_hover", "#444444")
        
        super().__init__(
            parent, text=text, corner_radius=15,
            width=kwargs.pop("width", 60),
            height=kwargs.pop("height", 28),
            font=kwargs.pop("font", ctk.CTkFont(size=12)),
            fg_color=self.active_color if self.variable and self.variable.get() else self.inactive_color,
            hover_color=self.active_hover if self.variable and self.variable.get() else self.inactive_hover,
            command=self._toggle, **kwargs
        )
        
        if self.variable:
            self.variable.trace_add("write", self._update_state)

    def _toggle(self):
        if self.variable:
            self.variable.set(not self.variable.get())
            
    def _update_state(self, *args):
        is_active = self.variable.get()
        self.configure(
            fg_color=self.active_color if is_active else self.inactive_color,
            hover_color=self.active_hover if is_active else self.inactive_hover
        )


# ─────────────────────────────────────────────────────────────────────────────
#  ToolTip — Tooltip window on hover
# ─────────────────────────────────────────────────────────────────────────────

class ToolTip:
    """
    A simple tooltip for CustomTkinter widgets.
    """
    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tooltip_window = None
        self.id = None
        
        # Bind events
        self.widget.bind("<Enter>", self.schedule_show)
        self.widget.bind("<Leave>", self.hide)
        self.widget.bind("<ButtonPress>", self.hide)
        
    def schedule_show(self, event=None):
        self.id = self.widget.after(self.delay, self.show)

    def show(self, event=None):
        if self.tooltip_window or not self.text:
            return
            
        x, y, cx, cy = self.widget.bbox("insert")
        x = x + self.widget.winfo_rootx() + 25
        y = y + cy + self.widget.winfo_rooty() + 25
        
        self.tooltip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        
        # CustomTkinter styling for the tooltip
        label = ctk.CTkLabel(
            tw, text=self.text,
            corner_radius=4,
            fg_color="#1e1e2e",
            text_color="#cdd6f4",
            font=ctk.CTkFont(size=11),
            padx=8, pady=4
        )
        label.pack()

    def hide(self, event=None):
        if self.id:
            self.widget.after_cancel(self.id)
            self.id = None
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None

