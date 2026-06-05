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


