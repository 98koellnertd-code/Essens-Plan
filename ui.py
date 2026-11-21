"""Oberflächen-Bausteine: Karten und eckige Buttons mit weichem Schatten, runde Emoji-Icons,
Tabs, schlanke Scrollbars und scrollbare Bereiche. Alle Maße laufen über S() und passen sich
damit der Windows-Skalierung an."""
import base64
import tkinter as tk
import tkinter.font as tkfont
import tkinter.ttk as ttk

import icons
import utils
from utils import C, BTN, F, S, mix, ToolTip

EMOJI_FONT = "Segoe UI Emoji"
_IMG_CACHE = {}


def dark():
    return utils.ACTIVE_THEME == "dark"


def _bg(w):
    try:
        return w.cget("bg")
    except tk.TclError:
        return C["surface"]


def emoji_img(ch, size, circle=None, ring=None):
    """Farbiges Emoji als PhotoImage (gecacht), optional auf rundem Hintergrund. None ohne Pillow."""
    key = (ch, size, circle, ring)
    if key not in _IMG_CACHE:
        pil = icons.emoji(ch, size, circle, ring)
        _IMG_CACHE[key] = None if pil is None else \
            tk.PhotoImage(data=base64.b64encode(icons.png(pil)).decode("ascii"))
    return _IMG_CACHE[key]


def haken_img(an, size=None):
    """Kästchen für Tabellenzeilen (gecacht): angehakt = Akzentfläche mit Haken, sonst leeres Feld.
    None ohne Pillow."""
    size = size or S(18)
    key = ("haken", an, size, utils.ACTIVE_THEME)
    if key not in _IMG_CACHE:
        pil = (icons.checkbox(size, C["accent"], C["accent"], C["on_accent"]) if an
               else icons.checkbox(size, C["surface2"], C["border"]))
        _IMG_CACHE[key] = None if pil is None else             tk.PhotoImage(data=base64.b64encode(icons.png(pil)).decode("ascii"))
    return _IMG_CACHE[key]


def rrect(cv, x0, y0, x1, y1, r, **kw):
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    if r < 1:
        return cv.create_rectangle(x0, y0, x1, y1, **kw)
    pts = (x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
           x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0)
    return cv.create_polygon(pts, smooth=True, **kw)


def draw_shadow(cv, x0, y0, x1, y1, bg, blur=None, dy=None, strength=None, tags="shadow"):
    """Weicher Schlagschatten aus übereinandergelegten, nach außen heller werdenden Ringen."""
    blur = S(8) if blur is None else blur
    dy = S(3) if dy is None else dy
    if strength is None:
        strength = 0.38 if dark() else 0.14
    for i in range(blur, 0, -1):
        a = strength * (1 - (i - 1) / blur) ** 2
        rrect(cv, x0 - i, y0 - i + dy, x1 + i, y1 + i + dy, i,
              fill=mix(bg, C["shadow"], a), outline="", tags=tags)


class Card(tk.Frame):
    """Weiße Box mit feinem Rand und weichem Schatten. Inhalt kommt in .body.

    hover=True: beim Überfahren färbt sich der Rand Richtung Akzent und der Schatten wird
    kräftiger. Neu gezeichnet wird nur beim echten Wechsel (rein/raus), nicht bei Mausbewegung."""
    def __init__(self, parent, pad=14, bg=None, margin=10, padx=None, pady=None, hover=False):
        self.outer = bg or _bg(parent)
        super().__init__(parent, bg=self.outer)
        self.m, self.dy = S(margin), S(3)
        self.bw = max(1, S(1))
        self.cv = tk.Canvas(self, bg=self.outer, highlightthickness=0, bd=0)
        self.cv.place(x=0, y=0, relwidth=1, relheight=1)
        self.box = tk.Frame(self, bg=C["border"])
        self.box.pack(fill="both", expand=True, padx=self.m, pady=(self.m - self.dy, self.m + self.dy))
        self.body = tk.Frame(self.box, bg=C["surface"],
                             padx=S(pad if padx is None else padx), pady=S(pad if pady is None else pady))
        self.body.pack(fill="both", expand=True, padx=self.bw, pady=self.bw)
        self._gezeichnet = None
        self._accent = None          # feste Rahmenfarbe aus set_accent (hat Vorrang vor dem Hover-Rand)
        self._hover = False
        self.bind("<Configure>", self._draw)
        if hover:
            self.bind("<Enter>", self._enter, add="+")
            self.bind("<Leave>", self._leave, add="+")

    def _enter(self, _=None):
        self._set_hover(True)

    def _leave(self, e):
        # Tk meldet <Leave> auch beim Wechsel in ein Kind-Widget – dann ist der Zeiger noch drin.
        try:
            w = self.winfo_containing(e.x_root, e.y_root)
        except (KeyError, tk.TclError):
            w = None
        while w is not None:
            if w is self:
                return
            w = getattr(w, "master", None)
        self._set_hover(False)

    def _set_hover(self, flag):
        if flag == self._hover:
            return
        self._hover = flag
        try:
            if not self._accent:
                self.box.configure(bg=mix(C["border"], C["accent"], 0.45) if flag else C["border"])
        except tk.TclError:
            return
        self._draw()

    def _draw(self, _=None):
        w, h = self.winfo_width(), self.winfo_height()
        if (w, h, self._hover) == self._gezeichnet:      # nur verschoben, nicht in der Größe geändert
            return
        self._gezeichnet = (w, h, self._hover)
        try:
            self.cv.delete("all")
        except tk.TclError:                 # Zeichenfläche schon zerstört – die Karte wird abgebaut
            return
        if w > 2 * self.m and h > 2 * self.m:
            st = (0.75 if self._hover else 0.55) if dark() else (0.22 if self._hover else 0.12)
            draw_shadow(self.cv, self.m, self.m - self.dy, w - self.m, h - self.m - self.dy,
                        self.outer, blur=self.m - 1, dy=self.dy, strength=st)

    def set_margin(self, margin):
        """Rand um die Karte (Platz für den Schatten) ändern – z. B. schmaler, wenn das Fenster niedrig ist."""
        m = S(margin)
        if m == self.m:
            return
        self.m = m
        self.box.pack_configure(padx=m, pady=(max(0, m - self.dy), m + self.dy))
        self._gezeichnet = None
        self._draw()

    def set_accent(self, color=None, width=1):
        bw = max(1, S(width)) if color else self.bw
        self._accent = color
        if color:
            self.box.configure(bg=color)
        else:
            self.box.configure(bg=mix(C["border"], C["accent"], 0.45) if self._hover else C["border"])
        self.body.pack_configure(padx=bw, pady=bw)


class Btn(tk.Canvas):
    """Eckiger Button mit Schatten, optional mit rundem Emoji-Icon. kind: primary, navy, sky, green, light."""
    def __init__(self, parent, text="", command=None, kind="primary", icon=None, bg=None,
                 font=None, padx=14, pady=7, tip=None, minwidth=0):
        self.outer = bg or _bg(parent)
        super().__init__(parent, bg=self.outer, highlightthickness=0, bd=0, cursor="hand2", takefocus=0)
        self.command, self.kind, self.icon = command, kind, icon
        self.font = tkfont.Font(font=font or F["btn"])
        self.padx, self.pady, self.minwidth = padx, pady, minwidth
        self.enabled, self.hover, self.pressed = True, False, False
        self.blur, self.dy, self.lift = S(5), S(2), S(1)   # lift: Schatten rutscht beim Hover etwas tiefer
        self.set_text(text)
        self.bind("<Enter>", lambda e: self._state(hover=True))
        self.bind("<Leave>", lambda e: self._state(hover=False, pressed=False))
        self.bind("<ButtonPress-1>", lambda e: self._state(pressed=True))
        self.bind("<ButtonRelease-1>", self._release)
        self.tooltip = ToolTip(self, tip) if tip else None   # .tooltip.text lässt sich später ändern

    def set_text(self, text):
        self.text = text
        fh = self.font.metrics("linespace")
        self.isz = round(fh * 1.5) if self.icon else 0
        gap = S(8) if self.icon and text else 0
        self.bw = max(S(self.minwidth), S(self.padx) * 2 + self.isz + gap + (self.font.measure(text) if text else 0))
        if self.icon and not text:
            self.bw = max(S(self.minwidth), self.isz + S(self.pady) * 2)
        self.bh = max(fh, self.isz) + S(self.pady) * 2
        self.top = max(0, self.blur - self.dy)
        self.configure(width=self.bw + 2 * self.blur, height=self.top + self.bh + self.blur + self.dy + self.lift)
        self._draw()

    def set_font(self, font=None, pady=None):
        """Schrift und Innenabstand nachträglich ändern – z. B. etwas kleiner, wenn das Fenster niedrig ist."""
        self.font = tkfont.Font(font=font or F["btn"])
        if pady is not None:
            self.pady = pady
        self.set_text(self.text)

    def _state(self, **kw):
        if all(getattr(self, k) == v for k, v in kw.items()):
            return
        for k, v in kw.items():
            setattr(self, k, v)
        self._draw()

    def _release(self, e):
        fire = self.pressed and self.enabled and 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height()
        self._state(pressed=False)
        if fire:
            self.invoke()

    def invoke(self):
        if self.enabled and self.command:
            self.command()

    def set_enabled(self, flag):
        self.enabled = bool(flag)
        self.configure(cursor="hand2" if flag else "arrow")
        self._draw()

    def _draw(self):
        self.delete("all")
        bg, hov, fg = BTN.get(self.kind, BTN["primary"])
        light = self.kind == "light"
        fill = hov if (self.hover and self.enabled) else bg
        if not self.enabled:
            fill, fg = mix(bg, self.outer, 0.45), mix(fg, self.outer, 0.45)
        down = S(2) if (self.pressed and self.enabled) else 0
        x0, y0 = self.blur, self.top + down
        x1, y1 = x0 + self.bw, y0 + self.bh
        lifted = self.hover and self.enabled and not down
        strength = (0.5 if dark() else 0.2) * (0.35 if not self.enabled else 0.55 if down else 1.55 if lifted else 1)
        draw_shadow(self, x0, self.top, x1, self.top + self.bh, self.outer,
                    blur=self.blur - (S(2) if down else 0), dy=self.dy + (self.lift if lifted else 0),
                    strength=strength)
        outline = (C["accent"] if self.hover and self.enabled else C["border"]) if light else mix(fill, "#000000", 0.12)
        self.create_rectangle(x0, y0, x1 - 1, y1 - 1, fill=fill, outline=outline, width=max(1, S(1)))
        if not light:  # feine Lichtkante oben → wirkt plastisch
            self.create_line(x0 + 1, y0 + 1, x1 - 1, y0 + 1, fill=mix(fill, "#ffffff", 0.22))
        cy = (y0 + y1) / 2
        x = x0 + (S(self.padx) if self.text else (self.bw - self.isz) / 2)
        if self.icon:
            circle = (C["accent_soft"] if light else "#ffffff") if self.enabled else mix("#ffffff", fill, 0.5)
            img = emoji_img(self.icon, self.isz, circle)
            if img:
                self.create_image(x + self.isz / 2, cy, image=img)
            else:
                self.create_text(x + self.isz / 2, cy, text=self.icon, fill=fg,
                                 font=(EMOJI_FONT, max(8, int(F["btn"][1] * 1.1))))
            x += self.isz + S(8)
        if self.text:
            self.create_text(x, cy, text=self.text, anchor="w", fill=fg, font=self.font)


class RoundIcon(tk.Label):
    """Rundes Emoji-Icon; .set(icon) tauscht das Symbol."""
    def __init__(self, parent, icon, size=36, circle=None, ring=None, bg=None):
        self.outer = bg or _bg(parent)
        super().__init__(parent, bg=self.outer, bd=0, padx=0, pady=0, highlightthickness=0)
        self.size, self.circle, self.ring = S(size), circle, ring
        self.set(icon)

    def set(self, icon, circle=None):
        if circle:
            self.circle = circle
        img = emoji_img(icon, self.size, self.circle or C["accent_soft"], self.ring)
        if img:
            self.configure(image=img, text="")
        else:
            self.configure(image="", text=icon, fg=C["text"], width=2,
                           font=(EMOJI_FONT, max(8, round(self.size * 0.33))))
        self._img = img


class Tab(tk.Canvas):
    # Platzstufen (Rand, Icon, Abstand Icon–Text, Schrift): 0 = normal, 1 = enger, 2 = knapp –
    # damit alle Reiter auch bei 200 % oder auf kleinen Bildschirmen in eine Zeile passen.
    STUFEN = ((16, 28, 9, "tab"), (10, 24, 7, "btn"), (7, 20, 5, "small_bold"))

    def __init__(self, parent, text, icon, command):
        self.outer = _bg(parent)
        super().__init__(parent, bg=self.outer, highlightthickness=0, bd=0, cursor="hand2")
        self.text, self.icon, self.command = text, icon, command
        self.fonts = [tkfont.Font(font=F[s[3]]) for s in self.STUFEN]
        self.selected = self.hover = False
        self.blur, self.dy = S(7), S(2)
        # Höhe bleibt in jeder Stufe gleich, sonst springt beim Verkleinern alles darunter
        self.bh = max(S(28), self.fonts[0].metrics("linespace")) + S(18)
        self.stufe = None
        self.set_stufe(0)
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False))
        self.bind("<ButtonRelease-1>", lambda e: command())

    def _set(self, **kw):
        if all(getattr(self, k) == v for k, v in kw.items()):
            return
        for k, v in kw.items():
            setattr(self, k, v)
        self._draw()

    def set_selected(self, flag):
        self._set(selected=flag)

    def breite(self, stufe):
        """Platzbedarf in Stufe `stufe` (mit Schattenrand)."""
        pad, isz, gap, _ = self.STUFEN[stufe]
        return S(pad) * 2 + S(isz) + S(gap) + self.fonts[stufe].measure(self.text) + 2 * self.blur

    def set_stufe(self, stufe):
        if stufe == self.stufe:
            return
        self.stufe = stufe
        pad, isz, gap, _ = self.STUFEN[stufe]
        self.pad, self.isz, self.gap, self.font = S(pad), S(isz), S(gap), self.fonts[stufe]
        self.bw = self.pad * 2 + self.isz + self.gap + self.font.measure(self.text)
        self.configure(width=self.bw + 2 * self.blur, height=S(4) + self.bh + self.blur + self.dy)
        if self.winfo_ismapped():
            self._draw()

    def _draw(self):
        self.delete("all")
        x0, y0 = self.blur, S(4)
        x1, y1 = x0 + self.bw, y0 + self.bh
        if self.selected:
            draw_shadow(self, x0, y0, x1, y1, self.outer, blur=self.blur, dy=self.dy)
            self.create_rectangle(x0, y0, x1 - 1, y1 - 1, fill=C["surface"], outline=C["border"])
            self.create_rectangle(x0, y1 - S(4), x1, y1, fill=C["accent"], width=0)
            circle, fg = C["accent_soft"], C["accent"]
        elif self.hover:
            self.create_rectangle(x0, y0, x1 - 1, y1 - 1, fill=C["surface2"],
                                  outline=mix(C["border"], C["accent"], 0.35))
            self.create_rectangle(x0 + 1, y1 - S(3), x1 - 1, y1 - 1, fill=mix(C["border"], C["accent"], 0.5), width=0)
            circle, fg = C["surface"], C["text"]
        else:
            circle, fg = C["surface"], C["subtext"]
        cy = (y0 + y1 - (S(2) if self.selected else 0)) / 2
        x = x0 + self.pad
        img = emoji_img(self.icon, self.isz, circle)
        if img:
            self.create_image(x + self.isz / 2, cy, image=img)
        else:
            self.create_text(x + self.isz / 2, cy, text=self.icon, font=(EMOJI_FONT, 12), fill=fg)
        self.create_text(x + self.isz + self.gap, cy, text=self.text, anchor="w", font=self.font, fill=fg)


class Tabs(tk.Frame):
    """Eigene Registerkarten: Leiste (.bar) mit Tab-Boxen, darunter der Seiteninhalt."""
    def __init__(self, parent, on_change=None, bg=None):
        bg = bg or C["bg"]
        super().__init__(parent, bg=bg)
        self.bar = tk.Frame(self, bg=bg)
        self.bar.pack(fill="x", padx=S(14))
        self.content = tk.Frame(self, bg=bg)
        self.content.pack(fill="both", expand=True)
        self.tabs, self.pages, self.current, self.on_change = [], [], -1, on_change
        self.stufe = 0
        self.bar.bind("<Configure>", lambda e: self._anpassen(), add="+")

    def add(self, text, icon):
        i = len(self.tabs)
        tab = Tab(self.bar, text, icon, lambda: self.select(i))
        tab.set_stufe(self.stufe)
        tab.pack(side="left", padx=(0, S(2)))
        page = tk.Frame(self.content, bg=self.content["bg"])
        self.tabs.append(tab)
        self.pages.append(page)
        tab._draw()
        if self.current < 0:
            self.select(0)
        self._anpassen()
        return page

    def _anpassen(self):
        """Reiter enger setzen, wenn sie nicht nebeneinander passen (kleines Fenster, 200 %). Hängt nur
        von der Breite der Leiste ab – kein Hin und Her, und neu gezeichnet wird nur beim Stufenwechsel."""
        w = self.bar.winfo_width()
        if w <= 1 or not self.tabs:
            return
        stufe = next((s for s in range(len(Tab.STUFEN))
                      if sum(t.breite(s) + S(2) for t in self.tabs) <= w), len(Tab.STUFEN) - 1)
        if stufe != self.stufe:
            self.stufe = stufe
            for t in self.tabs:
                t.set_stufe(stufe)

    def select(self, i):
        if i == self.current:
            return
        if self.current >= 0:
            self.pages[self.current].pack_forget()
            self.tabs[self.current].set_selected(False)
        self.current = i
        self.pages[i].pack(fill="both", expand=True)
        self.tabs[i].set_selected(True)
        if self.on_change:
            self.on_change(i)


class FlatScrollbar(tk.Canvas):
    """Schlanke Scrollbar (runder Griff, ohne Pfeile). Kompatibel mit yscrollcommand/xview."""
    def __init__(self, parent, command, orient="vertical", bg=None):
        self.outer = bg or _bg(parent)
        self.vertical = orient == "vertical"
        self.th = S(11)
        super().__init__(parent, bg=self.outer, highlightthickness=0, bd=0,
                         width=self.th if self.vertical else 1, height=1 if self.vertical else self.th)
        self.command = command
        self.lo, self.hi = 0.0, 1.0
        self.hover, self.drag = False, None
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "drag", None))

    def set(self, lo, hi):
        lo, hi = float(lo), float(hi)
        if (lo, hi) == (self.lo, self.hi):  # Tabellen melden sich bei jedem Neuzeichnen
            return
        self.lo, self.hi = lo, hi
        self._draw()

    def _hover(self, flag):
        self.hover = flag
        self._draw()

    def _geom(self):
        L = self.winfo_height() if self.vertical else self.winfo_width()
        span = self.hi - self.lo
        tl = max(S(32), span * L)
        pos = (L - tl) * self.lo / max(1e-9, 1 - span)
        return L, tl, pos

    def _draw(self):
        self.delete("all")
        if self.lo <= 0.0 and self.hi >= 1.0:
            return
        L, tl, pos = self._geom()
        pad = S(2)
        col = C["accent"] if (self.hover or self.drag) else mix(C["border"], C["subtext"], 0.35)
        r = (self.th - 2 * pad) / 2
        if self.vertical:
            rrect(self, pad, pos + pad, self.th - pad, pos + tl - pad, r, fill=col, outline="")
        else:
            rrect(self, pos + pad, pad, pos + tl - pad, self.th - pad, r, fill=col, outline="")

    def _press(self, e):
        if self.lo <= 0.0 and self.hi >= 1.0:
            return
        p = e.y if self.vertical else e.x
        L, tl, pos = self._geom()
        if pos <= p <= pos + tl:
            self.drag = (p, self.lo)
        else:
            self.command("scroll", -1 if p < pos else 1, "pages")

    def _motion(self, e):
        if not self.drag:
            return
        L, tl, _ = self._geom()
        p0, lo0 = self.drag
        span = self.hi - self.lo
        d = ((e.y if self.vertical else e.x) - p0) / max(1, L - tl) * (1 - span)
        self.command("moveto", max(0.0, min(1.0 - span, lo0 + d)))
        self._draw()


class ScrollArea(tk.Frame):
    """Vertikal scrollbarer Bereich. Inhalt kommt in .inner. fill_height: Inhalt mindestens so hoch wie sichtbar."""
    def __init__(self, parent, bg=None, fill_height=False):
        bg = bg or _bg(parent)
        super().__init__(parent, bg=bg)
        self.fill_height = fill_height
        self.cv = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, yscrollincrement=S(20))
        self.sb = FlatScrollbar(self, self.cv.yview, bg=bg)
        self.cv.configure(yscrollcommand=self.sb.set)
        self.sb.pack(side="right", fill="y", padx=(0, S(4)), pady=S(6))
        self.cv.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.cv, bg=bg)
        self.win = self.cv.create_window(0, 0, window=self.inner, anchor="nw")
        self._stand = None
        self.inner.bind("<Configure>", self._update)
        self.cv.bind("<Configure>", self._update)

    def _update(self, _=None):
        cw, ch = self.cv.winfo_width(), self.cv.winfo_height()
        rh = self.inner.winfo_reqheight()
        h = max(rh, ch) if self.fill_height else rh
        if (cw, ch, h) == self._stand:
            return
        self._stand = (cw, ch, h)
        if self.fill_height:
            self.cv.itemconfigure(self.win, width=cw, height=h)
        else:
            self.cv.itemconfigure(self.win, width=cw)
        self.cv.configure(scrollregion=(0, 0, cw, max(h, ch)))

    def scroll(self, delta):
        n = -int(delta / 120) or (-1 if delta > 0 else 1)
        self.cv.yview_scroll(n * 3, "units")

    def bind_wheel(self, widget):
        """Mausrad über widget scrollt die Seite statt z. B. den Combobox-Wert zu ändern."""
        widget.bind("<MouseWheel>", lambda e: (self.scroll(e.delta), "break")[1])


def install_wheel(root):
    """Mausrad scrollt den ScrollArea unter dem Mauszeiger (Tabellen/Listen scrollen selbst)."""
    def on_wheel(e):
        try:
            w = root.winfo_containing(e.x_root, e.y_root)
        except (KeyError, tk.TclError):
            return
        while w is not None:
            if isinstance(w, (tk.Listbox, ttk.Treeview, tk.Text, ttk.Combobox)):
                return
            if isinstance(w, ScrollArea):
                w.scroll(e.delta)
                return
            w = w.master
    root.bind_all("<MouseWheel>", on_wheel, add="+")


def tree_hover(tv, tag="hover"):
    """Zeilen-Hover für ein ttk.Treeview: die Zeile unter der Maus bekommt den Hintergrund
    C["overlay"]. Andere Tags der Zeile (odd, grp …) bleiben wirksam – Schrift, Font usw.
    bleiben erhalten, nur ihr Hintergrund wird getauscht. Ausgewählte Zeilen behalten die
    Auswahlfarbe. Gerechnet wird nur beim Wechsel der Zeile, nicht bei jeder Mausbewegung.

    Aufruf: einmal nach dem Anlegen der Tags, z. B. `ui.tree_hover(self.tv)`. Mehrfachaufruf ist
    harmlos. Hintergrund: ttk gibt dem zuerst angelegten Tag Vorrang – ein später angelegter
    „hover“-Tag würde von „odd“/„grp“ überdeckt. Darum wird ein Tag mit eigenem Hintergrund beim
    Hover durch eine Kopie „hover~<name>“ ersetzt (gleiche Schrift, Hover-Hintergrund) und beim
    Verlassen zurückgetauscht. Wer Zeilen neu füllt, muss nichts tun."""
    if getattr(tv, "_ep_hover_aktiv", False):
        return
    tv._ep_hover_aktiv = True
    tv._ep_hover = None                   # Zeilen-ID, die gerade hervorgehoben ist
    tv.tag_configure(tag, background=C["overlay"])
    kopien = {}                           # Kopie-Name -> Originalname

    def kopie_von(t):
        """Tag-Name für t im Hover-Zustand (t selbst, wenn t keinen Hintergrund setzt)."""
        name = f"{tag}~{t}"
        if name not in kopien:
            opts = tv.tag_configure(t)
            if not opts.get("background"):
                return t
            tv.tag_configure(name, background=C["overlay"],
                             **{k: v for k, v in opts.items() if v and k != "background"})
            kopien[name] = t
        return name

    def tags_of(row):
        return tv.tk.splitlist(tv.item(row, "tags"))

    def clear():
        row, tv._ep_hover = tv._ep_hover, None
        if row is None:
            return
        try:
            t = tags_of(row)
            if tag in t:
                tv.item(row, tags=[kopien.get(x, x) for x in t if x != tag])
        except tk.TclError:               # Zeile wurde inzwischen gelöscht
            pass

    def show(row):
        if row and row in tv.selection():
            row = ""                      # Auswahl behält ihre Farbe
        if row == (tv._ep_hover or ""):
            if not row:
                return
            try:                          # Tabelle neu gefüllt? Dann fehlt der Tag trotz gleicher ID
                if tag in tags_of(row):
                    return
            except tk.TclError:
                tv._ep_hover = None
                return
        clear()
        if row:
            try:
                t = [kopie_von(x) for x in tags_of(row) if x != tag]
                tv.item(row, tags=t + [tag])
                tv._ep_hover = row
            except tk.TclError:
                tv._ep_hover = None

    def motion(e):
        try:
            show(tv.identify_row(e.y))
        except tk.TclError:
            pass

    def wheel(_):                         # Zeile unter der Maus wechselt auch beim Scrollen
        def nachziehen():
            try:
                x, y = tv.winfo_pointerx() - tv.winfo_rootx(), tv.winfo_pointery() - tv.winfo_rooty()
                inside = 0 <= x < tv.winfo_width() and 0 <= y < tv.winfo_height()
                show(tv.identify_row(y) if inside else "")
            except tk.TclError:
                pass
        tv.after_idle(nachziehen)

    tv.bind("<Motion>", motion, add="+")
    tv.bind("<Leave>", lambda e: clear(), add="+")
    tv.bind("<MouseWheel>", wheel, add="+")
    tv.bind("<<TreeviewSelect>>", lambda e: (tv._ep_hover in tv.selection()) and clear(), add="+")


class Stat(tk.Frame):
    """Kennzahl: rundes Icon, kleine Überschrift, großer Wert."""
    def __init__(self, parent, icon, title, value="–", circle=None, bg=None, size=42):
        bg = bg or _bg(parent)
        super().__init__(parent, bg=bg)
        RoundIcon(self, icon, size, circle, bg=bg).pack(side="left", padx=(0, S(10)))
        box = tk.Frame(self, bg=bg)
        box.pack(side="left", fill="x", expand=True)
        tk.Label(box, text=title.upper(), bg=bg, fg=C["subtext"], font=F["small_bold"],
                 anchor="w", width=1).pack(fill="x")
        self.val = tk.Label(box, text=value, bg=bg, fg=C["text"], font=F["big"], anchor="w", width=1)
        self.val.pack(fill="x")
        self._tip = ToolTip(self.val, "")

    def set(self, value, fg=None):
        self.val.configure(text=value, fg=fg or C["text"])
        self._tip.text = value


class Section(tk.Frame):
    """Überschrift einer Karte: rundes Icon, fetter Titel, optional grauer Untertitel."""
    def __init__(self, parent, icon, title, sub=None, bg=None, size=38):
        bg = bg or _bg(parent)
        super().__init__(parent, bg=bg)
        RoundIcon(self, icon, size, bg=bg).pack(side="left", padx=(0, S(10)))
        box = tk.Frame(self, bg=bg)
        box.pack(side="left", fill="x", expand=True)
        tk.Label(box, text=title, bg=bg, fg=C["text"], font=F["h3"], anchor="w").pack(fill="x")
        if sub:
            self.sub = wrap_label(box, sub, bg=bg, fg=C["subtext"], font=F["small"])
            self.sub.pack(fill="x")


def auto_wrap(lbl, rand=2, mindest=60):
    """Umbruchbreite eines Labels an seine Breite koppeln. Gesetzt wird nur, wenn sie sich
    wirklich ändert – sonst zeichnet Tk das Label bei jeder Größenänderung umsonst neu."""
    stand = [None]

    def fit(e):
        w = max(S(mindest), e.width - S(rand))
        if w != stand[0]:
            stand[0] = w
            lbl.configure(wraplength=w)
    lbl.bind("<Configure>", fit)


def wrap_label(parent, text, **kw):
    """Label, das seinen Text automatisch auf die verfügbare Breite umbricht."""
    lbl = tk.Label(parent, text=text, anchor="w", justify="left", width=1, **kw)
    auto_wrap(lbl)
    return lbl


class Platzhalter:
    """Grauer Beispieltext im leeren Eingabefeld. Verschwindet beim ersten Zeichen; ein Klick darauf
    setzt den Cursor ins Feld, der Hover-Rahmen des Felds bleibt dabei erhalten."""

    def __init__(self, entry, var, text, font=None):
        self.entry, self.var = entry, var
        self.lbl = tk.Label(entry, text=text, bg=C["surface2"], fg=C["subtext"], font=font or F["base"],
                            anchor="w", cursor="xterm", bd=0, padx=0, pady=0)
        self.lbl.bind("<Button-1>", lambda e: entry.focus_set())
        self.lbl.bind("<Enter>", lambda e: self._hover(True))
        self.lbl.bind("<Leave>", lambda e: self._hover(False))
        var.trace_add("write", lambda *_: self.pruefen())
        self.pruefen()

    def _hover(self, an):
        try:
            if an or self.entry.winfo_containing(*self.entry.winfo_pointerxy()) is not self.entry:
                self.entry.state(["hover"] if an else ["!hover"])
        except (tk.TclError, KeyError):
            pass

    def pruefen(self):
        try:
            if self.var.get():
                self.lbl.place_forget()
            else:
                self.lbl.place(x=S(10), rely=0.5, anchor="w", relwidth=1, width=-S(20))
        except tk.TclError:
            pass
