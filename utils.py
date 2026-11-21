"""Gemeinsame Pfade, Farben, Schriften, DPI-Skalierung, Theme und JSON-Helfer."""
import os
import sys
import json
import base64
import tkinter as tk

# ─── Pfade (funktioniert als .py und als .exe) ────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR    = os.path.dirname(sys.executable)
    _BUNDLE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
else:
    BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
    _BUNDLE_DIR = BASE_DIR

APP_DIR_NAME = "Essens-Plan"


def _usable(d):
    """True, wenn in den Ordner geschrieben werden darf (legt ihn dabei an)."""
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".schreibtest")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def _data_dir():
    """Wohin Einstellungen, Wochen und eigene Rezepte kommen.
    .py: neben dem Skript · .exe: neben der EXE (portabel), sonst %APPDATA%\\Essens-Plan."""
    forced = os.environ.get("ESSENSPLAN_DATA")
    if forced:
        return os.path.abspath(forced)
    side = os.path.join(BASE_DIR, "res")
    if not getattr(sys, "frozen", False):
        return side
    if os.path.exists(os.path.join(BASE_DIR, "portable.txt")) or _usable(side):
        return side
    return os.path.join(os.environ.get("APPDATA") or BASE_DIR, APP_DIR_NAME)


DATA_DIR     = _data_dir()
RES_DIR      = DATA_DIR                                          # Altname
CONFIG_FILE  = os.path.join(DATA_DIR, "config.json")
WEEKS_DIR    = os.path.join(DATA_DIR, "wochen")
RECIPES_USER = os.path.join(DATA_DIR, "meine_rezepte.json")      # eigene Änderungen
RECIPES_BASE = os.path.join(_BUNDLE_DIR, "res", "rezepte.json")  # gebündelte Grunddatenbank
RECIPES_OLD  = os.path.join(DATA_DIR, "rezepte.json")            # Format vor v1.2
RECIPES_DEF  = RECIPES_BASE                                      # Altname
ICON_FILE    = os.path.join(_BUNDLE_DIR, "res", "icon.ico")

DEFAULT_CONFIG = {"ui_theme": "dark", "ui_scale": 0, "plz": "", "personen": 2,
                  "haendler": [], "vegetarisch": False, "max_laeden": 2, "programme": [],
                  "pdf_rezepte": True, "abwechslung": True, "artikel_fragen": True,
                  "rabatt_filter": False, "min_rabatt": 20,
                  "update_repo": "", "update_auto": True}


def load_json(path, default):
    """Liest eine JSON-Datei. Fehlt sie, ist sie kaputt oder von der falschen Art (Liste statt
    Objekt – etwa nach einem Eingriff von Hand), gibt es die Vorgabe statt eines Absturzes.
    utf-8-sig: der Windows-Editor speichert gern mit BOM, das darf die Datei nicht entwerten."""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if not isinstance(default, (dict, list)) or isinstance(data, type(default)):
                return data
        except Exception:
            pass
    return default.copy() if isinstance(default, (dict, list)) else default


def save_json(path, data, kompakt=False):
    """Schreibt erst in eine Nachbardatei und tauscht dann – bricht das Programm mittendrin ab
    (Neustart, Absturz, Strom weg), bleibt die alte Datei heil statt halb geschrieben.

    kompakt=True ist für die großen Wochendateien: ohne Einrückung schreibt der schnelle
    C-Encoder, das ist bei über 1 MB der Unterschied zwischen spürbarem Hänger und nichts."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if kompakt:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    else:
        text = json.dumps(data, indent=2, ensure_ascii=False)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# ─── Kindprozesse (Neustart, Update-Helfer) ───────────────────────────────────
def saubere_umgebung():
    """Umgebung für einen Prozess, der das laufende Programm überleben soll.

    Als onefile-EXE entpackt PyInstaller das Programm nach %TEMP%\\_MEIxxxxx und merkt sich den
    Ordner in Umgebungsvariablen (_PYI_…). Erbt eine neu gestartete Kopie derselben EXE diese
    Variablen, hält sie sich für einen Unterprozess: sie entpackt NICHT selbst, sondern läuft
    aus dem Ordner des alten Programms. Das räumt beim Beenden seinen Ordner weg, soweit es
    kann – übrig bleiben die gesperrten DLLs, die Warnung „Failed to remove temporary
    directory“ und ein Programm, dem die Dateien fehlen (Absturz beim nächsten Neustart).
    Darum: PyInstaller-Variablen entfernen und ausdrücklich einen frischen Start verlangen."""
    env = dict(os.environ)
    if not getattr(sys, "frozen", False):
        return env
    mei = os.path.normcase(os.path.abspath(getattr(sys, "_MEIPASS", "") or BASE_DIR))
    eigen = mei != os.path.normcase(os.path.abspath(BASE_DIR))    # nur bei onefile ein Temp-Ordner

    def drin(pfad):
        p = os.path.normcase(os.path.abspath(pfad.strip('"'))) if pfad.strip('"') else ""
        return bool(p) and (p == mei or p.startswith(mei + os.sep))

    for name, wert in list(env.items()):
        gross = name.upper()
        if gross.startswith("_PYI_") or gross == "_MEIPASS2":
            del env[name]
        elif eigen and gross == "PATH":
            env[name] = os.pathsep.join(t for t in wert.split(os.pathsep) if t and not drin(t))
        elif eigen and os.pathsep not in wert and drin(wert):
            del env[name]                      # z. B. TCL_LIBRARY/TK_LIBRARY aus dem Tk-Hook
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"    # ab PyInstaller 6.9: „bin ein neues Programm“
    return env


def starte_unabhaengig(args, **kw):
    """subprocess.Popen für Neustart und Update-Helfer – siehe saubere_umgebung().

    Zusätzlich wird der DLL-Suchpfad kurz zurückgesetzt: der Bootloader stellt ihn auf den
    Temp-Ordner, und Kindprozesse erben ihn (sie würden sonst DLLs daraus laden und sperren)."""
    import subprocess
    kw.setdefault("env", saubere_umgebung())
    k32 = None
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.SetDllDirectoryW(None)
        except Exception:
            k32 = None
    try:
        return subprocess.Popen(args, **kw)
    finally:
        if k32 is not None and getattr(sys, "_MEIPASS", None):
            try:
                k32.SetDllDirectoryW(sys._MEIPASS)   # falls der Start scheitert, läuft es hier weiter
            except Exception:
                pass


def oeffne_datei(pfad):
    """os.startfile für PDF und Datenordner – aus demselben Grund wie starte_unabhaengig().

    Das gestartete Programm (z. B. Acrobat) erbt sonst PATH und DLL-Suchpfad, lädt
    VCRUNTIME140.dll aus %TEMP%\\_MEIxxxxx und sperrt sie. Bleibt es offen, während Essens-Plan
    endet oder neu startet, meldet der Bootloader „Failed to remove temporary directory“."""
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        return os.startfile(pfad)
    import ctypes
    k32 = ctypes.windll.kernel32
    alt = dict(os.environ)
    sauber = saubere_umgebung()
    try:
        for name in alt:
            if name not in sauber:
                del os.environ[name]
            elif sauber[name] != alt[name]:
                os.environ[name] = sauber[name]
        k32.SetDllDirectoryW(None)
        os.startfile(pfad)
    finally:
        for name, wert in alt.items():
            if os.environ.get(name) != wert:
                os.environ[name] = wert
        if getattr(sys, "_MEIPASS", None):
            try:
                k32.SetDllDirectoryW(sys._MEIPASS)
            except Exception:
                pass


# ─── Farben (neutrales Grau; Grün/Rot/Orange/Gelb tragen Bedeutung und bleiben bunt) ──
# on_accent = Schriftfarbe auf einer Fläche in Akzentfarbe (hell: weiß, dunkel: fast schwarz).
C_LIGHT = {
    "bg": "#eef0f3", "surface": "#ffffff", "surface2": "#f6f7f9", "border": "#dde1e7",
    "overlay": "#e8ebef", "text": "#1f2328", "subtext": "#6b7079", "accent": "#374151",
    "accent_soft": "#e5e7eb", "on_accent": "#ffffff",
    "green": "#16935f", "green_soft": "#e0f4ea", "red": "#d14545",
    "orange": "#dc8428", "yellow": "#c99a17", "header": "#2b2f36", "header2": "#40454e",
    "header_text": "#ffffff", "header_sub": "#c9ced6", "row_stripe": "#f8f9fb",
    "select": "#dfe3e8", "shadow": "#1a1d21",
}
C_DARK = {
    "bg": "#18191c", "surface": "#222428", "surface2": "#2a2d32", "border": "#383c43",
    "overlay": "#30333a", "text": "#e8eaed", "subtext": "#9ba1ab", "accent": "#d1d5db",
    "accent_soft": "#363a41", "on_accent": "#18191c",
    "green": "#4cc995", "green_soft": "#1d3a33", "red": "#ef7373",
    "orange": "#f0a458", "yellow": "#e3c35a", "header": "#2a2d32", "header2": "#3a3e45",
    "header_text": "#ffffff", "header_sub": "#b4bac4", "row_stripe": "#1e2024",
    "select": "#3d424a", "shadow": "#000000",
}
# Buttons: Art -> (Hintergrund, Hover, Schrift)
BTN_LIGHT = {
    "primary": ("#374151", "#1f2937", "#ffffff"), "navy": ("#2b2f36", "#1a1d22", "#ffffff"),
    "sky": ("#4b5563", "#374151", "#ffffff"), "green": ("#1e9a68", "#19875b", "#ffffff"),
    "light": ("#ffffff", "#f1f3f6", "#374151"),
}
BTN_DARK = {
    "primary": ("#4b5563", "#5f6b7a", "#ffffff"), "navy": ("#3a3e45", "#4a4f58", "#ffffff"),
    "sky": ("#5b6472", "#6e7888", "#ffffff"), "green": ("#22a06d", "#2fb37d", "#ffffff"),
    "light": ("#2a2d32", "#353940", "#e5e7eb"),
}

CONFIG: dict = {**DEFAULT_CONFIG, **load_json(CONFIG_FILE, {})}
ACTIVE_THEME: str = "dark" if CONFIG.get("ui_theme") == "dark" else "light"
C: dict = (C_DARK if ACTIVE_THEME == "dark" else C_LIGHT).copy()
BTN: dict = (BTN_DARK if ACTIVE_THEME == "dark" else BTN_LIGHT).copy()

# ─── Schriften (in Punkt → wachsen mit der Windows-Skalierung automatisch mit) ──
UI_FONT = "Segoe UI"
F = {
    "base": (UI_FONT, 10), "small": (UI_FONT, 9), "small_bold": (UI_FONT, 9, "bold"),
    "bold": (UI_FONT, 10, "bold"), "btn": (UI_FONT, 10, "bold"), "tab": (UI_FONT, 11, "bold"),
    "h1": ("Segoe UI Black", 18), "h3": (UI_FONT, 12, "bold"), "big": (UI_FONT, 14, "bold"),
    "combo": (UI_FONT, 11, "bold"), "liste": (UI_FONT, 11),
}


def mix(a, b, t):
    """Farbe a um den Anteil t (0..1) in Richtung b mischen."""
    a, b = a.lstrip("#"), b.lstrip("#")
    return "#" + "".join(f"{round(int(a[i:i + 2], 16) + (int(b[i:i + 2], 16) - int(a[i:i + 2], 16)) * t):02x}"
                         for i in (0, 2, 4))


# ─── DPI / Windows-Skalierung ─────────────────────────────────────────────────
SCALE = 1.0


def enable_dpi_awareness():
    """Scharfe Darstellung bei 125 %/150 %/200 % statt unscharf hochgezogener Bitmap.
    Muss vor dem Erzeugen des Tk-Fensters aufgerufen werden."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)    # ab Windows 8.1
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()         # Windows 7/8
    except Exception:
        pass


def gewuenschte_skalierung():
    """Eigene Größen-Einstellung als Faktor, 0 heißt „automatisch“ (Bildschirm-DPI).
    ESSENSPLAN_SCALE hat Vorrang und ist zum Testen da."""
    wunsch = os.environ.get("ESSENSPLAN_SCALE") or CONFIG.get("ui_scale") or 0
    try:
        wunsch = float(wunsch)
    except (TypeError, ValueError):
        return 0.0
    return max(0.75, min(4.0, wunsch)) if wunsch else 0.0


def init_scaling(root):
    """Skalierungsfaktor bestimmen (96 DPI = 100 %). Eigene Einstellung schlägt die DPI.

    Gesetzt wird „tk scaling“, nicht nur SCALE: die Schriften sind in Punkt angegeben und
    wachsen nur darüber mit – sonst bliebe auf einem 4K-Schirm die Schrift winzig."""
    global SCALE
    wunsch = gewuenschte_skalierung()
    if wunsch:
        try:
            root.tk.call("tk", "scaling", wunsch * 96 / 72)
        except tk.TclError:
            pass
    SCALE = max(0.75, min(4.0, root.winfo_fpixels("1i") / 96))
    return SCALE


def S(px):
    """Pixelmaß für die aktuelle Skalierung."""
    return int(round(px * SCALE))


def init_fonts(root):
    """Auf fremden PCs fehlende Schriften ersetzen (z. B. „Segoe UI Black“ vor Windows 8)."""
    global UI_FONT
    import tkinter.font as tkfont
    try:
        fams = {f.lower() for f in tkfont.families(root)}
    except tk.TclError:
        return
    ui = next((f for f in (UI_FONT, "Tahoma", "Verdana", "DejaVu Sans", "Arial")
               if f.lower() in fams), None)
    if ui and ui != UI_FONT:
        for k, v in F.items():
            if v[0] == UI_FONT:
                F[k] = (ui,) + tuple(v[1:])
        UI_FONT = ui
    heavy = next((f for f in ("Segoe UI Black", "Arial Black", "Segoe UI Semibold")
                  if f.lower() in fams), None)
    F["h1"] = (heavy, 18) if heavy else (UI_FONT, 18, "bold")


class ToolTip:
    """Einfacher Hover-Tooltip für beliebige tk/ttk-Widgets."""
    def __init__(self, widget, text, delay=450):
        self.widget, self.text, self.delay = widget, text, delay
        self._id = self._win = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._cancel, add="+")
        widget.bind("<Button>", self._cancel, add="+")

    def _schedule(self, _=None):
        self._cancel()
        self._id = self.widget.after(self.delay, self._show)

    def _cancel(self, _=None):
        try:
            if self._id:
                self.widget.after_cancel(self._id)
            if self._win:
                self._win.destroy()
        except tk.TclError:                     # Fenster wird gerade geschlossen
            pass
        self._id = self._win = None

    def _show(self):
        self._id = None
        if not self.text:
            return
        try:
            if not self.widget.winfo_exists():
                return
            px, py = self.widget.winfo_pointerxy()
            self._win = tw = tk.Toplevel(self.widget)
        except tk.TclError:
            return
        tw.wm_overrideredirect(True)
        # Hell: weiße Sprechblase, dunkel: hellere Fläche als die Karten – damit sie sich vom
        # Untergrund abhebt; Rand deutlich dunkler/heller als der Kartenrand.
        dunkel = ACTIVE_THEME == "dark"
        tw.configure(bg=mix(C["border"], C["text"], 0.45 if not dunkel else 0.25))
        tk.Label(tw, text=self.text, bg=C["overlay"] if dunkel else C["surface"], fg=C["text"],
                 font=F["small"], wraplength=S(340), justify="left",
                 padx=S(10), pady=S(6)).pack(padx=max(1, S(1)), pady=max(1, S(1)))
        tw.update_idletasks()
        # An der Maus, am Bildschirmrand begrenzt; passt sie unten nicht mehr hin, kommt sie darüber.
        w, h = tw.winfo_reqwidth(), tw.winfo_reqheight()
        sw, sh = tw.winfo_screenwidth(), tw.winfo_screenheight()
        x = min(px + S(12), sw - w - S(8))
        y = py + S(20)
        if y + h > sh - S(8):
            y = py - h - S(10)
        try:
            tw.attributes("-topmost", True)     # vor der Position: danach springt das Fenster nach +0+0
        except tk.TclError:
            pass
        tw.wm_geometry(f"+{max(0, int(x))}+{max(0, int(y))}")


def apply_theme(root):
    """ttk-Design auf Basis von „clam“ (vektorbasiert, skaliert sauber) plus eigene, per S()
    skalierte Grafik-Elemente für Felder, Checkboxen, Pfeile und Tabellenköpfe."""
    import tkinter.ttk as ttk
    import tkinter.font as tkfont
    import icons

    st = ttk.Style(root)
    st.theme_use("clam")
    root._theme_imgs = imgs = []

    def img(pil):
        ph = tk.PhotoImage(master=root, data=base64.b64encode(icons.png(pil)).decode("ascii"))
        imgs.append(ph)
        return ph

    def element(name, *args, **kw):
        try:
            st.element_create(name, "image", *args, **kw)
        except tk.TclError:  # existiert schon
            pass

    root.tk.call("tk_setPalette", "background", C["surface"], "foreground", C["text"],
                 "highlightColor", C["accent"], "selectBackground", C["select"],
                 "selectForeground", C["text"], "activeBackground", C["overlay"],
                 "activeForeground", C["text"], "insertBackground", C["text"])
    st.configure(".", background=C["surface"], foreground=C["text"], font=F["base"],
                 selectbackground=C["select"], selectforeground=C["text"], troughcolor=C["overlay"],
                 fieldbackground=C["surface2"], insertcolor=C["text"], bordercolor=C["border"],
                 focuscolor=C["accent"], lightcolor=C["surface"])
    st.configure("TFrame", background=C["surface"])
    st.configure("TLabel", background=C["surface"], foreground=C["text"])

    field = C["surface2"]
    for s in ("TEntry", "TCombobox", "TSpinbox"):
        st.configure(s, padding=(S(8), S(5)), foreground=C["text"], fieldbackground=field,
                     selectbackground=C["select"], selectforeground=C["text"])
    st.map("TCombobox", selectbackground=[("readonly", field)],
           selectforeground=[("readonly", C["text"])], foreground=[("disabled", C["subtext"])])
    st.configure("TCheckbutton", background=C["surface"], foreground=C["text"], padding=(0, S(3)))
    st.configure("Bg.TCheckbutton", background=C["bg"])        # für Kästchen direkt auf dem Fenstergrund
    st.configure("Leer.TCheckbutton", foreground=C["subtext"])  # Händler ohne Angebote diese Woche
    # clam färbt Kästchen beim Drüberfahren hellgrau – im dunklen Design dann kaum lesbar. Der Grund
    # bleibt, als Hover-Zeichen reicht der farbige Rand des Kästchens.
    st.map("TCheckbutton", background=[("active", C["surface"])])
    st.map("Bg.TCheckbutton", background=[("active", C["bg"])])
    st.configure("TProgressbar", background=C["accent"], troughcolor=C["overlay"],
                 borderwidth=0, thickness=S(8))

    f = tkfont.Font(root=root, font=F["base"])
    st.configure("Treeview", background=C["surface"], fieldbackground=C["surface"],
                 foreground=C["text"], font=F["base"], borderwidth=0, indent=S(20),
                 rowheight=f.metrics("linespace") + S(10))
    st.map("Treeview", background=[("selected", C["select"])], foreground=[("selected", C["text"])])
    st.configure("Treeview.Heading", background=C["surface2"], foreground=C["subtext"],
                 font=F["small_bold"], padding=(S(8), S(7)), relief="flat")
    # Größere Tabelle (Reiter „Angebot raussuchen“): erbt Farben, Layout und Kopf von „Treeview“
    fg = tkfont.Font(root=root, font=F["liste"])
    st.configure("Gross.Treeview", font=F["liste"], rowheight=fg.metrics("linespace") + S(12))
    st.configure("Gross.Treeview.Heading", font=F["bold"])

    if icons.HAS_PIL:
        # ttk streckt die Mitte einer 9-Slice-Vorlage nicht, es kachelt sie. Eine Vorlage mit
        # 2 px breiter Mitte heißt deshalb: über tausend Einzelbilder je Tabellenkopf, bei jedem
        # Neuzeichnen – das machte Größenänderungen sekundenlang. Darum die Mitte so groß, dass
        # ein Feld mit ein, zwei Bildern auskommt. width/height halten die Mindestgröße des
        # Elements klein – sonst würde jedes Feld so groß wie seine Vorlage.
        mitte_b, mitte_h = 640, 96
        # Felder: eckig, 1 px Rand, bei Fokus 2 px in Akzentfarbe
        bw1, bw2 = max(1, S(1)), max(2, S(2))
        fb = bw2 + 1
        fw, fh = 2 * fb + mitte_b, 2 * fb + mitte_h
        element("EP.field", img(icons.field(fw, field, C["border"], bw1, fh)),
                ("disabled", img(icons.field(fw, C["bg"], C["border"], bw1, fh))),
                ("focus", img(icons.field(fw, field, C["accent"], bw2, fh))),
                ("hover", img(icons.field(fw, field, mix(C["border"], C["accent"], 0.55), bw1, fh))),
                border=fb, sticky="nsew", width=fb * 3, height=fb * 3)
        st.layout("TEntry", [("EP.field", {"sticky": "nswe", "children": [
            ("Entry.padding", {"sticky": "nswe", "children": [("Entry.textarea", {"sticky": "nswe"})]})]})])

        chev = img(icons.chevron(S(12), C["subtext"]))
        chev_on = img(icons.chevron(S(12), C["accent"]))
        element("EP.Combobox.downarrow", chev, ("pressed", chev_on), ("hover", chev_on),
                width=S(28), sticky="")
        st.layout("TCombobox", [("EP.field", {"sticky": "nswe", "children": [
            ("EP.Combobox.downarrow", {"side": "right", "sticky": "ns"}),
            ("Combobox.padding", {"expand": "1", "sticky": "nswe", "children": [
                ("Combobox.textarea", {"sticky": "nswe"})]})]})])

        up, dn = img(icons.chevron(S(10), C["subtext"], up=True)), img(icons.chevron(S(10), C["subtext"]))
        element("EP.Spinbox.uparrow", up, width=S(24), height=S(13), sticky="")
        element("EP.Spinbox.downarrow", dn, width=S(24), height=S(13), sticky="")
        st.layout("TSpinbox", [("EP.field", {"side": "top", "sticky": "we", "children": [
            ("null", {"side": "right", "sticky": "", "children": [
                ("EP.Spinbox.uparrow", {"side": "top", "sticky": "e"}),
                ("EP.Spinbox.downarrow", {"side": "bottom", "sticky": "e"})]}),
            ("Spinbox.padding", {"sticky": "nswe", "children": [("Spinbox.textarea", {"sticky": "nswe"})]})]})])

        n = S(18)
        element("EP.Checkbutton.indicator", img(icons.checkbox(n, field, C["border"])),
                ("selected", img(icons.checkbox(n, C["accent"], C["accent"], C["on_accent"]))),
                ("hover", img(icons.checkbox(n, field, C["accent"]))),
                width=n + S(9), sticky="w")
        st.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nswe", "children": [
            ("EP.Checkbutton.indicator", {"side": "left", "sticky": ""}),
            ("Checkbutton.label", {"side": "left", "sticky": "nswe"})]})])

        # Tabelle ohne Rahmen (die Box drumherum liefert die Karte), flacher Kopf
        st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        lw, inset = max(2, S(2)), S(7)
        hh = inset * 2 + lw + mitte_h
        element("EP.Treeheading.cell", img(icons.heading(2 + mitte_b, hh, C["surface2"], C["border"],
                                                          C["border"], lw, inset)),
                border=(1, inset, 1, inset + lw), sticky="nsew", width=4, height=inset * 2 + lw + 3)
        st.layout("Treeview.Heading", [
            ("EP.Treeheading.cell", {"sticky": "nswe"}),
            ("Treeheading.padding", {"sticky": "nswe", "children": [
                ("Treeheading.image", {"side": "right", "sticky": ""}),
                ("Treeheading.text", {"sticky": "we"})]})])
        down = icons.chevron(S(12), C["subtext"])
        element("EP.Treeitem.indicator", img(down.rotate(90)),
                ("user2", img(icons.field(S(12), (0, 0, 0, 0), (0, 0, 0, 0), 0))),
                ("user1", img(down)), width=S(24), sticky="")
        st.layout("Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [
            ("EP.Treeitem.indicator", {"side": "left", "sticky": ""}),
            ("Treeitem.image", {"side": "left", "sticky": ""}),
            ("Treeitem.text", {"side": "left", "sticky": ""})]})])

    for pat, val in (("*Listbox.background", C["surface"]), ("*Listbox.foreground", C["text"]),
                     ("*Listbox.selectBackground", C["select"]), ("*Listbox.selectForeground", C["text"]),
                     ("*Listbox.font", F["base"]),
                     ("*TCombobox*Listbox.background", C["surface"]),
                     ("*TCombobox*Listbox.selectBackground", C["accent"]),
                     ("*TCombobox*Listbox.selectForeground", C["on_accent"]),
                     ("*TCombobox*Listbox.font", F["base"])):
        root.option_add(pat, val)
