import sys, os, json, time, shutil, ctypes, threading, subprocess
from ctypes import wintypes
from PySide6.QtCore import (Qt, QVariantAnimation, QEasingCurve, QTimer, QRectF, QPointF, QRect, QPropertyAnimation,
                            Signal, QFileInfo, QSize, QUrl, QPoint)
from PySide6.QtGui import QPainter, QColor, QFont, QLinearGradient, QPixmap, QPainterPath, QPen, QIcon, QDesktopServices, QImage, QRadialGradient
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
                               QScrollArea, QFileDialog, QMenu, QInputDialog, QMessageBox, QFrame, QStackedWidget,
                               QFileIconProvider, QGraphicsOpacityEffect, QLineEdit, QSystemTrayIcon)
from PySide6.QtNetwork import QLocalServer, QLocalSocket

APP_KEY = "LightcatLauncher_single_instance"

DATA_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "LightcatLauncher")
COVERS = os.path.join(DATA_DIR, "covers")
DB, SET = os.path.join(DATA_DIR, "games.json"), os.path.join(DATA_DIR, "settings.json")
os.makedirs(COVERS, exist_ok=True)
BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
LOGO = os.path.join(BASE, "logo.png")
COFFEE_URL = "https://buymeacoffee.com/faisaldagoodkid"
X_URL = "https://x.com/faisaldagoodboi?s=11"

THEMES = {
    "dark": dict(bg="#14141c", side="#0f0f16", line="#2a2a38", text="#ffffff", sub="#8a8aa0", menu="#1e1e2a"),
    "light": dict(bg="#f4f4f8", side="#e8e8ef", line="#d2d2de", text="#15151c", sub="#6a6a7c", menu="#ffffff"),
}
ACCENTS = ["#c5c8d2", "#ffd86b", "#6bd6ff", "#ff8fc7", "#7dffa0"]


def jload(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def jsave(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


S = {"theme": "dark", "accent": ACCENTS[0], "anim": True, "minimize": False, "tray": True}
S.update(jload(SET, {}))
if not S.get("v2"):  # one-time: premium gray becomes the default accent
    S["accent"], S["v2"] = ACCENTS[0], True


RUNNING = {}  # id(game) -> start time, for games running right now (not saved)


def T():
    return THEMES.get(S["theme"], THEMES["dark"])


def dur(ms):
    return ms if S["anim"] else 1


def mix(a, b, t):
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


def acc_fg():
    c = QColor(S["accent"])
    return c if S["theme"] == "dark" else c.darker(210)


def fmt_time(s):
    m = int(s // 60)
    if m < 1:
        return "<1m"
    return f"{m // 60}h {m % 60}m" if m >= 60 else f"{m}m"


def fmt_hours(s):
    m = s / 60
    if m < 1:
        return "< 1 minute"
    if m < 60:
        return f"{int(m)} minute" + ("" if int(m) == 1 else "s")
    return f"{s / 3600:.1f} hours"


def fade(w, ms=260):
    if not S["anim"]:
        return
    ef = QGraphicsOpacityEffect(w)
    w.setGraphicsEffect(ef)
    a = QPropertyAnimation(ef, b"opacity", w)
    a.setDuration(ms)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setEasingCurve(QEasingCurve.OutCubic)
    a.finished.connect(lambda: w.setGraphicsEffect(None))
    a.start()
    w._fade_anim = a


_MASKS = {}
_COVERS = {}


def soft_shadow(p, r, radius, strength, dy, layers=6):
    """Layered soft shadow - looks premium, costs almost nothing."""
    p.setPen(Qt.NoPen)
    for i in range(layers):
        p.setBrush(QColor(0, 0, 0, int(strength * (layers - i) / layers / 3)))
        p.drawRoundedRect(r.adjusted(-i, -i + dy, i, i + dy), radius + i, radius + i)


def icon_pm(name, color, size):
    """White icon mask (gear.png / search.png) tinted with any color."""
    m = _MASKS.get((name, size))
    if m is None:
        src = QPixmap(os.path.join(BASE, name + ".png"))
        if src.isNull():
            return None
        m = _MASKS[(name, size)] = src.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    out = QPixmap(m.size())
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.drawPixmap(0, 0, m)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(out.rect(), color)
    p.end()
    return out


def avg_color(pm):
    img = pm.toImage().convertToFormat(QImage.Format_ARGB32).scaled(16, 16, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    r = g = b = a = 0
    for y in range(16):
        for x in range(16):
            c = img.pixelColor(x, y)
            w = c.alpha()
            r, g, b, a = r + c.red() * w, g + c.green() * w, b + c.blue() * w, a + w
    return QColor(r // a, g // a, b // a) if a else QColor(70, 70, 95)


def extract_icon(path):
    try:
        pm = QFileIconProvider().icon(QFileInfo(path)).pixmap(256, 256)
        if pm.isNull():
            return ""
        dest = os.path.join(COVERS, f"icon_{int(time.time() * 1000)}.png")
        pm.save(dest, "PNG")
        return dest
    except Exception:
        return ""


def rounded(path, size, radius):
    src = QPixmap(path).scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(clip)
    p.drawPixmap((size - src.width()) // 2, (size - src.height()) // 2, src)
    p.end()
    return out


# ---------- start a game and get its process handle (for playtime) ----------
class SEI(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]


k32 = ctypes.windll.kernel32
k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
k32.WaitForSingleObject.restype = wintypes.DWORD
k32.CloseHandle.argtypes = [wintypes.HANDLE]
u32 = ctypes.windll.user32
u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.DefWindowProcW.restype = ctypes.c_ssize_t
ctypes.windll.shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SEI)]


def run_game(path):
    sei = SEI()
    sei.cbSize = ctypes.sizeof(SEI)
    sei.fMask = 0x40
    sei.lpVerb, sei.lpFile, sei.lpDirectory, sei.nShow = "open", path, os.path.dirname(path), 1
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        return None
    return sei.hProcess or 0


# ---------- smooth widgets ----------
class Anim:
    def _anim(self, ms, attr, curve=QEasingCurve.OutQuad):
        a = QVariantAnimation(self)
        a._ms = ms
        a.setEasingCurve(curve)
        a.valueChanged.connect(lambda v: (setattr(self, attr, v), self.update()))
        return a

    def _run(self, a, start, end):
        a.stop()
        a.setDuration(dur(a._ms))
        a.setStartValue(start)
        a.setEndValue(end)
        a.start()


class AnimButton(QPushButton, Anim):
    """Pill buttons. Only the shape animates - the text never stretches."""

    def __init__(self, text, kind="ghost", px=15, icon=None, compact=False):
        super().__init__(text)
        self.kind, self.icon_name, self.h, self.pr = kind, icon, 0.0, 0.0
        self.compact = compact
        self.icon_tint = None
        self.setCursor(Qt.PointingHandCursor)
        f = QFont("Segoe UI")
        f.setPixelSize(px)
        f.setWeight(QFont.DemiBold)
        self.setFont(f)
        self.ah, self.ap = self._anim(170, "h", QEasingCurve.OutCubic), self._anim(110, "pr", QEasingCurve.OutCubic)

    def sizeHint(self):
        fm = self.fontMetrics()
        iw = (28 if self.text() else 20) if self.icon_name else 0
        if self.compact:
            return QSize(fm.horizontalAdvance(self.text()) + 34 + iw, fm.height() + 16)
        return QSize(fm.horizontalAdvance(self.text()) + 48 + iw, fm.height() + 26)

    def enterEvent(self, e):
        self._run(self.ah, self.h, 1.0)

    def leaveEvent(self, e):
        self._run(self.ah, self.h, 0.0)

    def mousePressEvent(self, e):
        self._run(self.ap, self.pr, 1.0)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._run(self.ap, self.pr, 0.0)
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        acc, tx, h = QColor(S["accent"]), QColor(T()["text"]), self.h
        g = 2 * h - 2.5 * self.pr
        r = QRectF(self.rect()).adjusted(5 - g, 5 - g, g - 5, g - 5)
        rad = r.height() / 2
        fg = mix(tx, acc_fg(), h)
        p.setPen(Qt.NoPen)
        if self.kind in ("primary", "sel"):
            soft_shadow(p, r, rad, 50 + 40 * h, 2 + 2 * h, 4)
            gr = QLinearGradient(r.topLeft(), r.bottomLeft())
            gr.setColorAt(0, mix(acc, QColor("#ffffff"), 0.22 + 0.15 * h))
            gr.setColorAt(1, acc.darker(108))
            p.setBrush(gr)
            p.drawRoundedRect(r, rad, rad)
            p.setPen(QPen(QColor(255, 255, 255, 80), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
            fg = QColor("#111111")
        elif self.kind == "danger":
            red = QColor("#ff6b6b")
            bg = QColor(red)
            bg.setAlpha(int(25 + 45 * h))
            p.setBrush(bg)
            p.setPen(QPen(QColor(255, 107, 107, 140 + int(100 * h)), 1.2))
            p.drawRoundedRect(r, rad, rad)
            fg = red
        else:  # ghost / outline -> frosted glass
            bg = QColor(tx)
            bg.setAlpha(int((0 if self.kind == "ghost" else 14) + 20 * h))
            edge = QColor(tx)
            edge.setAlpha(int((0 if self.kind == "ghost" else 34) + 40 * h))
            p.setBrush(bg)
            p.setPen(QPen(edge, 1))
            p.drawRoundedRect(r, rad, rad)
        p.setPen(fg)
        p.setFont(self.font())
        tw = self.fontMetrics().horizontalAdvance(self.text())
        iw = (28 if self.text() else 20) if self.icon_name else 0
        x0 = (self.width() - tw - iw) / 2
        if self.icon_name:
            col = fg
            if self.icon_tint:
                col = QColor(self.icon_tint)
                col.setAlpha(int(140 + 90 * h))
            pm = icon_pm(self.icon_name, col, 20)
            if pm:
                p.drawPixmap(int(x0), (self.height() - 20) // 2, pm)
        p.drawText(QRectF(x0 + iw, 0, tw + 4, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())


class SearchBar(QLineEdit, Anim):
    def __init__(self):
        super().__init__()
        self.f, self.hv = 0.0, 0.0
        self.setPlaceholderText("Search your games...")
        self.setFixedHeight(48)
        self.setTextMargins(42, 0, 14, 0)
        self.setAcceptDrops(False)
        self.setStyleSheet("QLineEdit{background:transparent; border:none; font-size:14px;}")
        self.af = self._anim(220, "f", QEasingCurve.OutCubic)
        self.ah = self._anim(160, "hv", QEasingCurve.OutCubic)

    def focusInEvent(self, e):
        self._run(self.af, self.f, 1.0)
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._run(self.af, self.f, 0.0)
        super().focusOutEvent(e)

    def enterEvent(self, e):
        self._run(self.ah, self.hv, 1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._run(self.ah, self.hv, 0.0)
        super().leaveEvent(e)

    def paintEvent(self, e):
        t = T()
        tx, acc = QColor(t["text"]), QColor(S["accent"])
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        rad = r.height() / 2
        if self.f > 0.01:  # soft focus ring
            ring = QColor(acc)
            ring.setAlpha(int(60 * self.f))
            p.setPen(QPen(ring, 3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), rad + 2, rad + 2)
        bg = QColor(tx)
        bg.setAlpha(int(14 + 8 * self.hv + 6 * self.f))
        edge = QColor(acc) if self.f > 0.01 else QColor(tx)
        edge.setAlpha(int(60 + 150 * self.f) if self.f > 0.01 else int(24 + 22 * self.hv))
        p.setBrush(bg)
        p.setPen(QPen(edge, 1.2))
        p.drawRoundedRect(r, rad, rad)
        pm = icon_pm("search", mix(QColor(t["sub"]), tx, self.f), 18)
        if pm:
            p.drawPixmap(20, (self.height() - 18) // 2, pm)
        p.end()
        super().paintEvent(e)


class SmoothArea(QScrollArea):
    def __init__(self):
        super().__init__()
        self.anim = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)

    def wheelEvent(self, e):
        bar = self.verticalScrollBar()
        base = self.anim.endValue() if self.anim.state() == QPropertyAnimation.Running else bar.value()
        target = max(bar.minimum(), min(bar.maximum(), int(base - e.angleDelta().y() * 0.9)))
        self.anim.stop()
        self.anim.setDuration(dur(280))
        self.anim.setStartValue(bar.value())
        self.anim.setEndValue(target)
        self.anim.start()


class ColorDot(QWidget, Anim):
    clicked = Signal()

    def __init__(self, color):
        super().__init__()
        self.c, self.h, self.s = QColor(color), 0.0, 0.0
        self.setFixedSize(44, 44)
        self.setCursor(Qt.PointingHandCursor)
        self.ah, self.as_ = self._anim(160, "h"), self._anim(250, "s", QEasingCurve.OutBack)

    def set_sel(self, v):
        self._run(self.as_, self.s, 1.0 if v else 0.0)

    def enterEvent(self, e):
        self._run(self.ah, self.h, 1.0)

    def leaveEvent(self, e):
        self._run(self.ah, self.h, 0.0)

    def mouseReleaseEvent(self, e):
        self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c, rad = QRectF(self.rect()).center(), 12 + 2 * self.h
        p.setPen(Qt.NoPen)
        p.setBrush(self.c)
        p.drawEllipse(c, rad, rad)
        ring = QColor(T()["text"])
        ring.setAlpha(int(255 * max(0.0, min(1.0, self.s))))
        p.setPen(QPen(ring, 2.5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, rad + 5 * self.s, rad + 5 * self.s)


class Toggle(QWidget, Anim):
    toggled = Signal(bool)

    def __init__(self, on):
        super().__init__()
        self.on, self.k = on, 1.0 if on else 0.0
        self.setFixedSize(48, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.ak = self._anim(220, "k", QEasingCurve.OutCubic)

    def mouseReleaseEvent(self, e):
        self.on = not self.on
        self._run(self.ak, self.k, 1.0 if self.on else 0.0)
        self.toggled.emit(self.on)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(mix(QColor(T()["line"]), QColor(S["accent"]), self.k))
        p.drawRoundedRect(QRectF(0, 3, 48, 24), 12, 12)
        x = 3 + 22 * self.k
        p.setBrush(QColor(0, 0, 0, 55))
        p.drawEllipse(QRectF(x, 6.5, 20, 20))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, 5, 20, 20))


class Card(QWidget, Anim):
    clicked = Signal(object)
    menu_req = Signal(object, object)

    def __init__(self, game, w=150, h=215, delay=0):
        super().__init__()
        self.game, self.hover, self.flash = game, 0.0, 0.0
        self.show_pin = True
        self.appear = 1.0 if (delay is None or not S["anim"]) else 0.0
        self.setFixedSize(w, h)
        self.setCursor(Qt.PointingHandCursor)
        self.cover = QRectF(8, 14, w - 16, h - 52)
        self.dots = QRectF(self.cover.right() - 34, self.cover.top() + 6, 28, 28)
        self.build_cover()
        self.a_hover = self._anim(180, "hover", QEasingCurve.OutCubic)
        self.a_appear = self._anim(450, "appear", QEasingCurve.OutCubic)
        self.a_flash = self._anim(600, "flash")
        self.press = 0.0
        self.a_press = self._anim(120, "press", QEasingCurve.OutCubic)
        if self.appear < 1:
            QTimer.singleShot(delay, lambda: self._run(self.a_appear, self.appear, 1.0))

    def build_cover(self):
        cw, ch = int(self.cover.width()), int(self.cover.height())
        key = (self.game.get("cover"), self.game["name"], cw, ch)
        if key in _COVERS:
            self.base, self.blur = _COVERS[key]
            return
        self.base = QPixmap(cw, ch)
        self.base.fill(QColor(24, 24, 32))  # never leave uninitialized pixels
        q = QPainter(self.base)
        q.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        c = self.game.get("cover")
        pm = QPixmap(c) if c and os.path.exists(c) else QPixmap()
        if not pm.isNull() and not (0.85 < pm.width() / pm.height() < 1.18):  # poster: fill the card
            sc = pm.scaled(cw, ch, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            q.drawPixmap((cw - sc.width()) // 2, (ch - sc.height()) // 2, sc)
        else:
            if pm.isNull():
                hue = sum(map(ord, self.game["name"])) * 37 % 360
                c1, c2 = QColor.fromHsv(hue, 140, 150), QColor.fromHsv((hue + 40) % 360, 170, 70)
            else:
                avg = avg_color(pm)
                c1, c2 = avg.darker(170), avg.darker(320)
            g = QLinearGradient(0, 0, cw, ch)
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            q.fillRect(QRectF(0, 0, cw, ch), g)
            if pm.isNull():
                q.setPen(QColor(255, 255, 255, 190))
                q.setFont(QFont("Segoe UI", 38, QFont.Bold))
                q.drawText(QRectF(0, 0, cw, ch), Qt.AlignCenter, self.game["name"][:1].upper())
            else:
                s = int(cw * 0.62)
                ic = pm.scaled(s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                q.drawPixmap((cw - ic.width()) // 2, (ch - ic.height()) // 2, ic)
        q.end()
        small = self.base.scaled(max(1, cw // 9), max(1, ch // 9), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self.blur = small.scaled(cw, ch, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        _COVERS[key] = (self.base, self.blur)

    def enterEvent(self, e):
        self._run(self.a_hover, self.hover, 1.0)

    def leaveEvent(self, e):
        self._run(self.a_hover, self.hover, 0.0)
        self._run(self.a_press, self.press, 0.0)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self.dots.contains(e.position()):
            self._run(self.a_press, self.press, 1.0)

    def mouseReleaseEvent(self, e):
        self._run(self.a_press, self.press, 0.0)
        if e.button() != Qt.LeftButton or not self.rect().contains(e.position().toPoint()):
            return
        if self.dots.contains(e.position()):
            self.menu_req.emit(self.game, e.globalPosition().toPoint())
        else:
            self._run(self.a_flash, 1.0, 0.0)
            self.clicked.emit(self.game)

    def contextMenuEvent(self, e):
        self.menu_req.emit(self.game, e.globalPos())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        hv, ap = max(0.0, min(1.0, self.hover)), max(0.0, min(1.0, self.appear))
        r, acc = self.cover, QColor(S["accent"])
        c = r.center()
        sc = (0.94 + 0.06 * ap) * (1 + 0.035 * hv - 0.035 * self.press)
        p.setOpacity(ap)
        p.translate(0, -6 * hv + (1 - ap) * 14)
        p.translate(c)
        p.scale(sc, sc)
        p.translate(-c)
        soft_shadow(p, r, 16, 80 + 70 * hv, 4 + 6 * hv)
        if hv > 0:  # soft accent glow
            g = QColor(acc)
            g.setAlpha(int(34 * hv))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(r.adjusted(-3, -3, 3, 3), 18, 18)
        path = QPainterPath()
        path.addRoundedRect(r, 16, 16)
        p.save()
        p.setClipPath(path)
        p.drawPixmap(int(r.x()), int(r.y()), self.base)
        if hv > 0:
            p.setOpacity(ap * hv)
            p.drawPixmap(int(r.x()), int(r.y()), self.blur)
            p.fillRect(r, QColor(0, 0, 0, 70))
            x = r.left() - r.width() + 2.3 * r.width() * hv  # light sweep across the cover
            sh = QLinearGradient(x, r.top(), x + r.width() * 0.7, r.bottom())
            sh.setColorAt(0, QColor(255, 255, 255, 0))
            sh.setColorAt(0.5, QColor(255, 255, 255, 45))
            sh.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillRect(r, sh)
            pill = QRectF(c.x() - 44, r.bottom() - 52 + (1 - hv) * 18, 88, 34)  # Play pill slides up
            soft_shadow(p, pill, 17, 90, 2, 4)
            p.setBrush(acc.lighter(108))
            p.drawRoundedRect(pill, 17, 17)
            p.setPen(QColor("#111111"))
            p.setFont(QFont("Segoe UI", 10, QFont.Bold))
            if id(self.game) in RUNNING:
                p.drawText(pill, Qt.AlignCenter, "In Game")
            else:
                tx0, ty0 = pill.left() + 22, pill.center().y()
                tri = QPainterPath()
                tri.moveTo(tx0, ty0 - 6)
                tri.lineTo(tx0 + 10, ty0)
                tri.lineTo(tx0, ty0 + 6)
                tri.closeSubpath()
                p.setBrush(QColor("#111111"))
                p.drawPath(tri)
                p.drawText(QRectF(tx0 + 16, pill.top(), pill.width() - 38, pill.height()), Qt.AlignVCenter | Qt.AlignLeft, "Play")
            p.setOpacity(ap)
        p.fillRect(r, QColor(255, 255, 255, int(130 * self.flash)))
        p.restore()
        # glass chips
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 90 + int(70 * hv)))
        p.drawEllipse(self.dots)
        p.setBrush(QColor(255, 255, 255, 235))
        d = self.dots.center()
        for i in (-1, 0, 1):
            p.drawEllipse(QPointF(d.x(), d.y() + i * 5.5), 1.9, 1.9)
        pt = self.game.get("playtime", 0)
        if pt > 0:
            val = fmt_hours(pt)
            f1 = QFont("Segoe UI")
            f1.setPixelSize(9)
            f1.setBold(True)
            f1.setLetterSpacing(QFont.AbsoluteSpacing, 0.8)
            f2 = QFont("Segoe UI")
            f2.setPixelSize(12)
            f2.setWeight(QFont.DemiBold)
            p.setFont(f2)
            w2 = p.fontMetrics().horizontalAdvance(val)
            p.setFont(f1)
            w1 = p.fontMetrics().horizontalAdvance("PLAY TIME")
            box = QRectF(r.left() + 7, r.top() + 7, max(w1, w2) + 18, 34)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 125))
            p.drawRoundedRect(box, 10, 10)
            p.setPen(QColor(165, 168, 182))
            p.drawText(QRectF(box.left() + 9, box.top() + 4, box.width(), 12), Qt.AlignLeft | Qt.AlignVCenter, "PLAY TIME")
            p.setFont(f2)
            p.setPen(QColor(238, 238, 244))
            p.drawText(QRectF(box.left() + 9, box.top() + 16, box.width(), 15), Qt.AlignLeft | Qt.AlignVCenter, val)
        if self.game.get("pinned") and self.show_pin and hv < 1:
            p.save()
            p.setOpacity(ap * (1 - hv))
            cx, cy = r.right() - 20, r.bottom() - 20
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 130))
            p.drawEllipse(QPointF(cx, cy), 13, 13)
            p.translate(cx, cy)
            p.rotate(35)
            p.setBrush(acc)
            p.drawRoundedRect(QRectF(-4, -9, 8, 9), 2, 2)
            p.drawRect(QRectF(-6, 0, 12, 2.5))
            p.setPen(QPen(acc, 1.8))
            p.drawLine(0, 2, 0, 9)
            p.restore()
        running = id(self.game) in RUNNING
        if running and hv < 1:  # live "IN GAME" badge (static: no CPU while you play)
            p.save()
            p.setOpacity(ap * (1 - hv))
            ig = QRectF(r.left() + 7, r.bottom() - 30, 80, 22)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(10, 12, 16, 175))
            p.drawRoundedRect(ig, 11, 11)
            p.setBrush(QColor(74, 222, 128, 60))
            p.drawEllipse(QPointF(ig.left() + 13, ig.center().y()), 6, 6)
            p.setBrush(QColor("#4ade80"))
            p.drawEllipse(QPointF(ig.left() + 13, ig.center().y()), 3.5, 3.5)
            f = QFont("Segoe UI")
            f.setPixelSize(10)
            f.setBold(True)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 0.8)
            p.setFont(f)
            p.setPen(QColor(236, 242, 238))
            p.drawText(QRectF(ig.left() + 24, ig.top(), ig.width() - 26, ig.height()), Qt.AlignVCenter | Qt.AlignLeft, "IN GAME")
            p.restore()
        # glass edge + accent border + name
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 16, 16)
        if running:
            p.setPen(QPen(QColor(74, 222, 128, 150), 1.6))
            p.drawRoundedRect(r, 16, 16)
        if hv > 0:
            bc = QColor(acc)
            bc.setAlpha(int(200 * hv))
            p.setPen(QPen(bc, 1.6))
            p.drawRoundedRect(r, 16, 16)
        p.setPen(QColor(T()["text"]))
        p.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
        txt = p.fontMetrics().elidedText(self.game["name"], Qt.ElideRight, self.width() - 10)
        p.drawText(QRectF(0, r.bottom() + 7, self.width(), 24), Qt.AlignCenter, txt)


class AddTile(QWidget, Anim):
    clicked = Signal()

    def __init__(self, delay=0, w=150, h=215):
        super().__init__()
        self.hover = 0.0
        self.appear = 1.0 if (delay is None or not S["anim"]) else 0.0
        self.setFixedSize(w, h)
        self.setCursor(Qt.PointingHandCursor)
        self.cover = QRectF(8, 14, w - 16, h - 52)
        self.a_hover = self._anim(180, "hover", QEasingCurve.OutCubic)
        self.a_appear = self._anim(450, "appear", QEasingCurve.OutCubic)
        if self.appear < 1:
            QTimer.singleShot(delay, lambda: self._run(self.a_appear, self.appear, 1.0))

    def enterEvent(self, e):
        self._run(self.a_hover, self.hover, 1.0)

    def leaveEvent(self, e):
        self._run(self.a_hover, self.hover, 0.0)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self.appear)
        hv = max(0.0, min(1.0, self.hover))
        p.translate(0, -8 * hv + (1 - self.appear) * 16)
        t, r = T(), self.cover
        fill = QColor(t["text"])  # neutral gray hover (no accent color)
        fill.setAlpha(int(16 * hv))
        p.setBrush(fill)
        p.setPen(QPen(mix(QColor(t["line"]), QColor(t["sub"]), hv), 2, Qt.DashLine))
        p.drawRoundedRect(r, 16, 16)
        col, c, L = mix(QColor(t["sub"]), QColor(t["text"]), 0.55 * hv), r.center(), 20 + 4 * hv
        p.setPen(QPen(col, 4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(c.x() - L, c.y()), QPointF(c.x() + L, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - L), QPointF(c.x(), c.y() + L))
        p.setPen(col)
        p.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
        p.drawText(QRectF(0, r.bottom() + 6, self.width(), 24), Qt.AlignCenter, "Add Game")


class NavBar(QWidget, Anim):
    """Sidebar navigation with a springy sliding highlight."""
    changed = Signal(int)
    ITEMS = (("Games", "grid"), ("Settings", "gear"))
    H = 44

    def __init__(self):
        super().__init__()
        self.idx, self.pos, self.hov = 0, 0.0, -1
        self.setFixedHeight(len(self.ITEMS) * self.H)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.ap = self._anim(380, "pos", QEasingCurve.OutBack)

    def set_index(self, i):
        if i != self.idx:
            self.idx = i
            self._run(self.ap, self.pos, float(i))

    def mouseMoveEvent(self, e):
        h = int(e.position().y() // self.H)
        if h != self.hov:
            self.hov = h
            self.update()

    def leaveEvent(self, e):
        self.hov = -1
        self.update()

    def mouseReleaseEvent(self, e):
        i = int(e.position().y() // self.H)
        if 0 <= i < len(self.ITEMS):
            self.changed.emit(i)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = T()
        acc, tx, sub = QColor(S["accent"]), QColor(t["text"]), QColor(t["sub"])
        w = self.width()
        p.setPen(Qt.NoPen)
        if 0 <= self.hov < len(self.ITEMS) and self.hov != self.idx:
            hb = QColor(tx)
            hb.setAlpha(12)
            p.setBrush(hb)
            p.drawRoundedRect(QRectF(4, 4 + self.hov * self.H, w - 8, self.H - 8), 12, 12)
        pill = QRectF(4, 4 + self.pos * self.H, w - 8, self.H - 8)
        pb = QColor(acc)
        pb.setAlpha(46)
        p.setBrush(pb)
        p.drawRoundedRect(pill, 12, 12)
        p.setBrush(acc)
        p.drawRoundedRect(QRectF(4, pill.top() + 10, 3.5, pill.height() - 20), 2, 2)
        for i, (label, icon) in enumerate(self.ITEMS):
            k = max(0.0, 1 - abs(self.pos - i))
            col = mix(sub, tx, k)
            y = i * self.H
            if icon == "grid":
                p.setBrush(col)
                for gx in (0, 9):
                    for gy in (0, 9):
                        p.drawRoundedRect(QRectF(20 + gx, y + 13 + gy, 7.5, 7.5), 2, 2)
            else:
                pm = icon_pm(icon, col, 18)
                if pm:
                    p.drawPixmap(20, y + 13, pm)
            p.setPen(col)
            f = QFont("Segoe UI", 10)
            f.setWeight(QFont.DemiBold if k > 0.5 else QFont.Medium)
            p.setFont(f)
            p.drawText(QRectF(50, y, w - 56, self.H), Qt.AlignVCenter | Qt.AlignLeft, label)
            p.setPen(Qt.NoPen)


class RecentRow(QWidget, Anim):
    """Compact 'recently played' row for the sidebar."""
    clicked = Signal(object)
    menu_req = Signal(object, object)

    def __init__(self, game, delay=0):
        super().__init__()
        self.game, self.h = game, 0.0
        self.appear = 0.0 if S["anim"] else 1.0
        self.setFixedHeight(56)
        self.setCursor(Qt.PointingHandCursor)
        self.thumb = self.make_thumb()
        self.ah = self._anim(160, "h", QEasingCurve.OutCubic)
        self.aa = self._anim(380, "appear", QEasingCurve.OutCubic)
        if self.appear < 1:
            QTimer.singleShot(delay, lambda: self._run(self.aa, self.appear, 1.0))

    def make_thumb(self):
        key = ("thumb", self.game.get("cover"), self.game["name"])
        if key in _COVERS:
            return _COVERS[key]
        s = 40
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        q = QPainter(pm)
        q.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, s, s), 11, 11)
        q.setClipPath(clip)
        c = self.game.get("cover")
        src = QPixmap(c) if c and os.path.exists(c) else QPixmap()
        if src.isNull():
            hue = sum(map(ord, self.game["name"])) * 37 % 360
            q.fillRect(QRectF(0, 0, s, s), QColor.fromHsv(hue, 140, 140))
            q.setPen(QColor(255, 255, 255, 210))
            q.setFont(QFont("Segoe UI", 15, QFont.Bold))
            q.drawText(QRectF(0, 0, s, s), Qt.AlignCenter, self.game["name"][:1].upper())
        elif 0.85 < src.width() / src.height() < 1.18:
            q.fillRect(QRectF(0, 0, s, s), avg_color(src).darker(170))
            ic = src.scaled(30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            q.drawPixmap((s - ic.width()) // 2, (s - ic.height()) // 2, ic)
        else:
            ic = src.scaled(s, s, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            q.drawPixmap((s - ic.width()) // 2, (s - ic.height()) // 2, ic)
        q.end()
        _COVERS[key] = pm
        return pm

    def enterEvent(self, e):
        self._run(self.ah, self.h, 1.0)

    def leaveEvent(self, e):
        self._run(self.ah, self.h, 0.0)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.game)

    def contextMenuEvent(self, e):
        self.menu_req.emit(self.game, e.globalPos())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        t = T()
        tx, acc = QColor(t["text"]), QColor(S["accent"])
        p.setOpacity(max(0.0, min(1.0, self.appear)))
        p.translate((1 - self.appear) * -14, 0)
        r = QRectF(self.rect()).adjusted(2, 3, -2, -3)
        bg = QColor(tx)
        bg.setAlpha(int(16 * self.h))
        if id(self.game) in RUNNING:
            bg = QColor(74, 222, 128, 26 + int(14 * self.h))
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, 12, 12)
        p.drawPixmap(10, 8, self.thumb)
        p.setPen(tx)
        p.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
        name = p.fontMetrics().elidedText(self.game["name"], Qt.ElideRight, self.width() - 92)
        p.drawText(QRectF(60, 9, self.width() - 90, 20), Qt.AlignLeft | Qt.AlignVCenter, name)
        pt = self.game.get("playtime", 0)
        p.setFont(QFont("Segoe UI", 8))
        if id(self.game) in RUNNING:
            mins = int((time.time() - RUNNING[id(self.game)]) // 60)
            p.setPen(QColor("#4ade80"))
            p.drawText(QRectF(60, 28, self.width() - 90, 18), Qt.AlignLeft | Qt.AlignVCenter,
                       "● In game" + (f" · {mins}m" if mins else ""))
            p.setPen(QPen(QColor(T()["side"]), 2))
            p.setBrush(QColor("#4ade80"))
            p.drawEllipse(QPointF(47, 45), 5, 5)
        else:
            p.setPen(QColor(t["sub"]))
            p.drawText(QRectF(60, 28, self.width() - 90, 18), Qt.AlignLeft | Qt.AlignVCenter,
                       f"Play time: {fmt_hours(pt)}" if pt > 0 else "Recently played")
        if self.h > 0:  # play hint
            a = QColor(acc)
            a.setAlpha(int(255 * self.h))
            p.setPen(Qt.NoPen)
            p.setBrush(a)
            cx, cy = self.width() - 22 + (1 - self.h) * 6, self.height() / 2
            tri = QPainterPath()
            tri.moveTo(cx - 4, cy - 6)
            tri.lineTo(cx + 6, cy)
            tri.lineTo(cx - 4, cy + 6)
            tri.closeSubpath()
            p.drawPath(tri)


class Toast(QLabel):
    """Small glass notification that slides up and fades away."""

    def __init__(self, parent):
        super().__init__(parent)
        self.hide()
        self.setAlignment(Qt.AlignCenter)
        self.ef = QGraphicsOpacityEffect(self)
        self.ef.setOpacity(0.0)
        self.setGraphicsEffect(self.ef)
        self.a_op = QPropertyAnimation(self.ef, b"opacity", self)
        self.a_pos = QPropertyAnimation(self, b"pos", self)
        for a in (self.a_op, self.a_pos):
            a.setEasingCurve(QEasingCurve.OutCubic)
        self.a_op.finished.connect(lambda: self.hide() if self.ef.opacity() < 0.05 else None)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.out)

    def show_msg(self, text, left=0):
        t = T()
        self.setText(text)
        self.setStyleSheet(f"background:{t['menu']}; color:{t['text']}; border:1px solid {t['line']}; "
                           f"border-radius:19px; padding:10px 24px; font-size:14px; font-weight:600;")
        self.adjustSize()
        pw = self.parentWidget()
        x = left + (pw.width() - left - self.width()) // 2
        y = pw.height() - self.height() - 72
        self.a_op.stop()
        self.a_pos.stop()
        self.show()
        self.raise_()
        self.a_pos.setDuration(dur(260))
        self.a_pos.setStartValue(QPoint(x, y + 18))
        self.a_pos.setEndValue(QPoint(x, y))
        self.a_op.setDuration(dur(220))
        self.a_op.setStartValue(self.ef.opacity())
        self.a_op.setEndValue(1.0)
        self.a_pos.start()
        self.a_op.start()
        self.timer.start(1800)

    def out(self):
        self.a_op.stop()
        self.a_op.setDuration(dur(300))
        self.a_op.setStartValue(self.ef.opacity())
        self.a_op.setEndValue(0.0)
        self.a_op.start()


def style():
    t, a = T(), S["accent"]
    tx, side = QColor(t["text"]), QColor(t["side"])

    def rgba(c, al):
        return f"rgba({c.red()},{c.green()},{c.blue()},{al})"

    return f"""
QWidget {{ color:{t['text']}; font-family:'Segoe UI'; }}
QWidget#clear, QStackedWidget, QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{ background:transparent; border:none; }}
QLabel {{ background:transparent; }}
QLabel#sub {{ color:{t['sub']}; font-size:13px; }}
QLabel#h1 {{ font-size:30px; font-weight:800; }}
QLabel#brand {{ font-size:19px; font-weight:800; }}
QLabel#section {{ color:{t['sub']}; font-size:11px; font-weight:700; letter-spacing:1.6px; padding-left:6px; }}
QLabel#rowt {{ font-size:15px; font-weight:600; }}
QFrame#side {{ background:{rgba(side, 175)}; border-right:1px solid {rgba(tx, 18)}; }}
QFrame#foot {{ border-top:1px solid {rgba(tx, 16)}; }}
QFrame#row {{ background:{rgba(tx, 10)}; border:1px solid {rgba(tx, 16)}; border-radius:16px; }}
QFrame#row QLabel#sub {{ font-size:12px; }}
QLineEdit {{ selection-background-color:{a}; selection-color:#000; }}
QScrollBar:vertical {{ background:transparent; width:8px; margin:4px 0; }}
QScrollBar::handle:vertical {{ background:{rgba(tx, 40)}; border-radius:4px; min-height:30px; }}
QScrollBar::handle:vertical:hover {{ background:{rgba(tx, 80)}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height:0; background:transparent; }}
QMenu {{ background:{t['menu']}; border:1px solid {rgba(tx, 25)}; border-radius:12px; padding:6px; }}
QMenu::item {{ padding:8px 26px 8px 16px; border-radius:8px; }}
QMenu::item:selected {{ background:{rgba(tx, 22)}; }}
QMenu::separator {{ height:1px; background:{rgba(tx, 20)}; margin:5px 10px; }}
QToolTip {{ background:{t['menu']}; color:{t['text']}; border:1px solid {rgba(tx, 25)}; border-radius:6px; padding:4px 8px; }}
QDialog {{ background:{t['bg']}; }}
QDialog QLineEdit {{ background:{t['menu']}; border:1px solid {rgba(tx, 30)}; border-radius:8px; padding:6px 8px; }}
QDialog QPushButton {{ background:{t['menu']}; border:1px solid {rgba(tx, 30)}; border-radius:8px; padding:6px 18px; min-width:60px; }}
QDialog QPushButton:hover {{ background:{rgba(tx, 30)}; }}
"""


def vbox(w, dy=0):
    b = QVBoxLayout()
    b.setContentsMargins(0, dy, 0, 0)
    b.addWidget(w)
    return b


class Launcher(QWidget):
    played = Signal(object, float)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lightcat Launcher")
        self.setMinimumSize(760, 480)
        self.setAcceptDrops(True)
        scr = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1160, scr.width() - 40), min(720, scr.height() - 40))  # fixed size
        geo = S.get("geom")
        if isinstance(geo, list) and len(geo) == 4:  # restore last position (size stays fixed)
            r = QRect(geo[0], geo[1], self.width(), self.height())
            if any(s.availableGeometry().intersects(r) for s in QApplication.screens()):
                self.setGeometry(r)
        self.games, self.cols, self.cards = jload(DB, []), 0, []
        for g in self.games:
            if not g.get("cover"):
                g["cover"] = extract_icon(g["path"])
        jsave(DB, self.games)
        self.played.connect(self.add_time)
        self._quitting = self._told = False
        self.tray_menu = self.make_menu()
        self.tray_menu.addAction("Open Lightcat Launcher").triggered.connect(self.show_window)
        self.tray_menu.addAction("Quit").triggered.connect(self.quit_app)
        self.tray = QSystemTrayIcon(QIcon(LOGO) if os.path.exists(LOGO) else self.windowIcon(), self)
        self.tray.setToolTip("Lightcat Launcher")
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(lambda r: self.show_window() if r in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        self.tray.setVisible(bool(S["tray"]) and QSystemTrayIcon.isSystemTrayAvailable())

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.side = QFrame(objectName="side")
        self.side.setFixedWidth(232)
        sl = QVBoxLayout(self.side)
        sl.setContentsMargins(14, 20, 14, 14)
        sl.setSpacing(4)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setFixedSize(42, 42)
        if os.path.exists(LOGO):
            logo.setPixmap(rounded(LOGO, 42, 12))
        else:
            logo.setText("🐱")
        brand.addWidget(logo)
        bt = QVBoxLayout()
        bt.setSpacing(0)
        bt.addWidget(QLabel("Lightcat", objectName="brand"))
        bt.addWidget(QLabel("LAUNCHER", objectName="section"))
        brand.addLayout(bt)
        brand.addStretch()
        sl.addLayout(brand)
        sl.addSpacing(22)
        self.nav = NavBar()
        self.nav.changed.connect(self.go)
        sl.addWidget(self.nav)
        sl.addSpacing(20)
        sl.addWidget(QLabel("RECENTLY PLAYED", objectName="section"))
        sl.addSpacing(4)
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(2)
        sl.addLayout(self.recent_box)
        sl.addStretch()
        root.addWidget(self.side)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.make_library())
        self.stack.addWidget(self.make_settings())
        root.addWidget(self.stack, 1)

        self.drop = QLabel("Drop your .exe here to add the game", self)
        self.drop.setAlignment(Qt.AlignCenter)
        self.drop.hide()
        self._toast = Toast(self)
        self.live = QTimer(self)  # refreshes "In game · Xm" twice a minute, only while a game runs
        self.live.setInterval(30000)
        self.live.timeout.connect(self.refresh_live)

        self.apply()
        self.setWindowOpacity(0)
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(dur(500))
        self._fade.setStartValue(0)
        self._fade.setEndValue(1)
        self._fade.start()

    def go(self, i):
        if i == self.stack.currentIndex():
            return
        self.stack.setCurrentIndex(i)
        self.nav.set_index(i)
        w = self.stack.currentWidget()
        fade(w)
        if S["anim"]:
            a = QPropertyAnimation(w, b"pos", w)
            a.setDuration(280)
            a.setStartValue(QPoint(0, 22))
            a.setEndValue(QPoint(0, 0))
            a.setEasingCurve(QEasingCurve.OutCubic)
            a.start()
            w._slide = a

    def make_menu(self):
        m = QMenu(self)
        m.setAttribute(Qt.WA_TranslucentBackground)
        m.setWindowFlags(m.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        return m

    def toast(self, text):
        self._toast.show_msg(text, self.side.width())

    def make_backdrop(self):
        """Static gradient + soft accent 'aurora' glows. Cached -> zero cost while idle."""
        w, h = max(1, self.width()), max(1, self.height())
        dark = S["theme"] == "dark"
        bg, acc = QColor(T()["bg"]), QColor(S["accent"])
        pm = QPixmap(w, h)
        p = QPainter(pm)
        g = QLinearGradient(0, 0, w * 0.4, h)
        g.setColorAt(0, bg.lighter(118) if dark else bg.lighter(102))
        g.setColorAt(1, bg.darker(112) if dark else bg.darker(104))
        p.fillRect(pm.rect(), g)
        big = max(w, h)
        for cx, cy, rad, al in ((w * 0.9, -h * 0.15, big * 0.6, 55 if dark else 40),
                                (w * 0.2, h * 1.1, big * 0.55, 32 if dark else 24)):
            rg = QRadialGradient(cx, cy, rad)
            c0, c1 = QColor(acc), QColor(acc)
            c0.setAlpha(al)
            c1.setAlpha(0)
            rg.setColorAt(0, c0)
            rg.setColorAt(1, c1)
            p.fillRect(pm.rect(), rg)
        p.end()
        return pm

    def paintEvent(self, e):
        if getattr(self, "_bd", None) is None or self._bd.size() != self.size():
            self._bd = self.make_backdrop()
        p = QPainter(self)
        p.drawPixmap(e.rect(), self._bd, e.rect())

    def nativeEvent(self, eventType, message):
        """Block resizing by dragging the window edges (maximize button still works)."""
        try:
            et = eventType.data() if hasattr(eventType, "data") else bytes(eventType)
            if et == b"windows_generic_MSG":
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:  # WM_NCHITTEST
                    hit = u32.DefWindowProcW(msg.hWnd, msg.message, msg.wParam, msg.lParam)
                    if 10 <= hit <= 17:  # any resize edge/corner
                        return True, 18  # HTBORDER = not resizable
        except Exception:
            pass
        return super().nativeEvent(eventType, message)

    # ---------- pages ----------
    def make_library(self):
        page = QWidget(objectName="clear")
        main = QVBoxLayout(page)
        main.setContentsMargins(28, 22, 28, 0)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(QLabel("Games", objectName="h1"))
        self.count_lbl = QLabel("", objectName="sub")
        col.addWidget(self.count_lbl)
        head.addLayout(col)
        head.addSpacing(30)
        self.search = SearchBar()
        self.search.setMinimumWidth(260)
        self.search.textChanged.connect(lambda _: self.populate_library(False))
        b = vbox(self.search, 0)
        head.addLayout(b, 1)
        head.setAlignment(b, Qt.AlignVCenter)
        main.addLayout(head)
        main.addSpacing(14)

        self.lib = QStackedWidget()
        self.scroll = SmoothArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.viewport().setAutoFillBackground(False)
        gw = QWidget(objectName="clear")
        self.grid = QGridLayout(gw)
        self.grid.setSpacing(14)
        self.grid.setContentsMargins(4, 8, 4, 8)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll.setWidget(gw)
        self.lib.addWidget(self.scroll)
        emp = QWidget(objectName="clear")
        ev = QVBoxLayout(emp)
        self.emp_title = QLabel("Your library is empty")
        self.emp_title.setStyleSheet("font-size:26px; font-weight:700;")
        self.emp_btn = AnimButton("Add Game +", "primary", 17)
        self.emp_btn.clicked.connect(lambda *_: self.add_game())
        self.emp_hint = QLabel("or drag & drop .exe file", objectName="sub")
        self.emp_hint.setStyleSheet("font-size:15px;")
        ev.addStretch()
        ev.addWidget(self.emp_title, 0, Qt.AlignCenter)
        ev.addSpacing(14)
        ev.addWidget(self.emp_btn, 0, Qt.AlignCenter)
        ev.addSpacing(6)
        ev.addWidget(self.emp_hint, 0, Qt.AlignCenter)
        ev.addStretch()
        self.lib.addWidget(emp)
        main.addWidget(self.lib, 1)

        foot = QFrame(objectName="foot")
        fl = QHBoxLayout(foot)
        a = QLabel("All Your (Totally Legal) Games in one place")
        a.setStyleSheet("font-size:16px; font-weight:600;")
        fl.addWidget(a)
        fl.addStretch()
        cof = AnimButton("☕ Buy me a coffee", "outline", 13, compact=True)
        cof.clicked.connect(lambda *_: QDesktopServices.openUrl(QUrl("https://buymeacoffee.com/faisaldagoodkid")))
        fl.addWidget(cof)
        fl.addStretch()
        fl.addWidget(QLabel("the simplest Launcher Ever", objectName="sub"))
        main.addWidget(foot)
        return page

    def make_settings(self):
        page = QWidget(objectName="clear")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(28, 22, 28, 14)
        top = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(QLabel("Settings", objectName="h1"))
        col.addWidget(QLabel("Make Lightcat yours", objectName="sub"))
        top.addLayout(col)
        top.addStretch()
        back = AnimButton("←  Back to Games", "outline", 14)
        back.clicked.connect(lambda *_: self.go(0))
        top.addWidget(back)
        outer.addLayout(top)
        outer.addSpacing(10)
        sc = SmoothArea()
        sc.setWidgetResizable(True)
        sc.viewport().setAutoFillBackground(False)
        body = QWidget(objectName="clear")
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 10, 10)
        v.setSpacing(8)
        sc.setWidget(body)
        outer.addWidget(sc, 1)

        def section(title):
            v.addSpacing(10)
            v.addWidget(QLabel(title, objectName="section"))

        def row(label, desc, *widgets):
            f = QFrame(objectName="row")
            l = QHBoxLayout(f)
            l.setContentsMargins(18, 10, 14, 10)
            txt = QVBoxLayout()
            txt.setSpacing(1)
            txt.addWidget(QLabel(label, objectName="rowt"))
            if desc:
                txt.addWidget(QLabel(desc, objectName="sub"))
            l.addLayout(txt)
            l.addStretch()
            for w in widgets:
                l.addWidget(w)
            v.addWidget(f)

        section("APPEARANCE")
        self.theme_btns = {}
        for name in ("dark", "light"):
            b = AnimButton(name.capitalize(), "outline", 14)
            b.clicked.connect(lambda *_, n=name: self.set_opt("theme", n))
            self.theme_btns[name] = b
        row("Theme", "Dark or light look", *self.theme_btns.values())
        self.acc_btns = {}
        for c in ACCENTS:
            d = ColorDot(c)
            d.clicked.connect(lambda c=c: self.set_opt("accent", c))
            self.acc_btns[c] = d
        row("Accent color", "Gray is the default", *self.acc_btns.values())

        section("BEHAVIOR")
        for key, label, desc in (("anim", "Animations", "Smooth motion everywhere"),
                                 ("minimize", "Minimize on launch", "Hide the launcher when a game starts"),
                                 ("tray", "Run in system tray", "Closing keeps Lightcat in the tray")):
            tg = Toggle(S[key])
            tg.toggled.connect(lambda val, k=key: self.set_opt(k, val, repaint=False))
            row(label, desc, tg)

        section("SUPPORT")
        cof = AnimButton("☕  Buy me a coffee", "outline", 14)
        cof.clicked.connect(lambda *_: QDesktopServices.openUrl(QUrl(COFFEE_URL)))
        xb = AnimButton("", "outline", 14, icon="x")
        xb.icon_tint = QColor(150, 150, 165)
        xb.setToolTip("Follow on X")
        xb.clicked.connect(lambda *_: QDesktopServices.openUrl(QUrl(X_URL)))
        row("Support & follow", "Enjoying Lightcat? Say hi", cof, xb)

        section("LIBRARY")
        of = AnimButton("Open folder", "outline", 14)
        of.clicked.connect(lambda *_: os.startfile(DATA_DIR))
        row("Library data", "Where your games list is saved", of)
        cl = AnimButton("Clear library", "danger", 14)
        cl.clicked.connect(lambda *_: self.clear_library())
        row("Remove all games", "Game files stay on your PC", cl)
        v.addStretch()
        v.addSpacing(8)
        v.addWidget(QLabel("Lightcat Launcher 🐱  •  the simplest launcher ever", objectName="sub"), 0, Qt.AlignHCenter)
        return page

    def set_opt(self, key, val, repaint=True):
        S[key] = val
        jsave(SET, S)
        if key == "tray":
            self.tray.setVisible(bool(val) and QSystemTrayIcon.isSystemTrayAvailable())
        if repaint:
            self.apply()

    def sync_settings(self):
        for n, b in self.theme_btns.items():
            b.kind = "sel" if S["theme"] == n else "outline"
            b.update()
        for c, d in self.acc_btns.items():
            d.set_sel(S["accent"] == c)

    def tint_titlebar(self):
        """Windows 11: make the title bar the same color as the launcher."""
        try:
            hwnd = wintypes.HWND(int(self.winId()))

            def put(attr, val):
                v = ctypes.c_int(val)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), 4)

            bg, tx = QColor(T()["bg"]), QColor(T()["text"])
            col = lambda c: c.red() | (c.green() << 8) | (c.blue() << 16)
            put(20, 1 if S["theme"] == "dark" else 0)
            put(35, col(bg))
            put(34, col(bg))
            put(36, col(tx))
        except Exception:
            pass

    def apply(self):
        self._bd = None
        self.update()
        self.setStyleSheet(style())
        bg = QColor(T()["bg"])
        self.drop.setStyleSheet(f"background:rgba({bg.red()},{bg.green()},{bg.blue()},238); border:2px dashed {S['accent']}; "
                                f"border-radius:18px; font-size:24px; font-weight:700; color:{T()['text']};")
        self.populate()
        self.sync_settings()
        self.tint_titlebar()
        fade(self.stack)
        fade(self.side)

    # ---------- library ----------
    def make_card(self, g, delay, small=False):
        c = Card(g, 130, 170, delay) if small else Card(g, 150, 215, delay)
        c.show_pin = not small
        c.clicked.connect(self.launch)
        c.menu_req.connect(self.card_menu)
        return c

    def visible_games(self):
        q = self.search.text().strip().lower()
        gs = [g for g in self.games if q in g["name"].lower()]
        pinned = sorted([g for g in gs if g.get("pinned")], key=lambda g: g["pinned"], reverse=True)
        return pinned + [g for g in gs if not g.get("pinned")]

    def populate(self, anim=True):
        self.populate_library(anim)
        self.populate_recent()

    def populate_library(self, anim=True):
        for c in self.cards:
            self.grid.removeWidget(c)
            c.deleteLater()
        games = self.visible_games()
        self.cards = [self.make_card(g, min(i * 45, 600) if anim else None) for i, g in enumerate(games)]
        if games and not self.search.text().strip():
            tile = AddTile(min(len(games) * 45, 600) if anim else None)
            tile.clicked.connect(self.add_game)
            self.cards.append(tile)
        self.cols = 0
        self.relayout(force=True)
        empty_lib = not self.games
        self.emp_title.setText("Your library is empty" if empty_lib else "No games found")
        self.emp_btn.setVisible(empty_lib)
        self.emp_hint.setVisible(empty_lib)
        self.lib.setCurrentIndex(0 if games else 1)
        n = len(self.games)
        self.count_lbl.setText(f"{n} game" + ("" if n == 1 else "s") + " in your library")

    def recent_n(self):
        return max(1, min(6, (self.height() - 280) // 58))

    def populate_recent(self):
        self._rn = self.recent_n()
        while self.recent_box.count():
            w = self.recent_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        recent = sorted([g for g in self.games if g.get("last_played")],
                        key=lambda g: g["last_played"], reverse=True)[:self._rn]
        if not recent:
            n = QLabel("Nothing played yet", objectName="sub")
            n.setStyleSheet("padding-left:8px;")
            self.recent_box.addWidget(n)
        for i, g in enumerate(recent):
            row = RecentRow(g, 80 + i * 60)
            row.clicked.connect(self.launch)
            row.menu_req.connect(self.card_menu)
            self.recent_box.addWidget(row)

    def relayout(self, force=False):
        cols = max(1, (self.scroll.viewport().width() - 10) // 164)
        if cols == self.cols and not force:
            return
        self.cols = cols
        for c in self.cards:
            self.grid.removeWidget(c)
        for i, c in enumerate(self.cards):
            self.grid.addWidget(c, i // cols, i % cols)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "scroll"):
            self.relayout()
            if self.recent_n() != getattr(self, "_rn", None):
                self.populate_recent()

    def show_window(self, *_):
        if self.isMinimized() or not self.isVisible():
            self.showMaximized() if S.get("max") else self.showNormal()
        self.raise_()
        self.activateWindow()
        try:  # Windows sometimes refuses to focus; force it to the front
            hwnd = int(self.winId())
            u32.ShowWindow(hwnd, 9)
            u32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def save_state(self):
        g = self.normalGeometry()
        S["geom"] = [g.x(), g.y(), g.width(), g.height()]
        S["max"] = self.isMaximized()
        jsave(SET, S)

    def quit_app(self, *_):
        self.save_state()
        self.tray.hide()
        QApplication.quit()

    def closeEvent(self, e):
        self.save_state()
        if S["tray"] and self.tray.isVisible():  # keep running in the tray
            e.ignore()
            self.hide()
            if not self._told:
                self._told = True
                self.tray.showMessage("Lightcat Launcher", "Still running in the tray. Right-click the icon to quit.",
                                      QSystemTrayIcon.Information, 2500)
            return
        self.quit_app()
        e.accept()

    # ---------- drag & drop ----------
    def dragEnterEvent(self, e):
        if any(u.toLocalFile().lower().endswith(".exe") for u in e.mimeData().urls()):
            e.acceptProposedAction()
            self.drop.setGeometry(self.stack.geometry().adjusted(14, 14, -14, -14))
            self.drop.show()
            self.drop.raise_()
            fade(self.drop, 200)

    def dragLeaveEvent(self, e):
        self.drop.hide()

    def dropEvent(self, e):
        self.drop.hide()
        for u in e.mimeData().urls():
            if u.toLocalFile().lower().endswith(".exe"):
                self.add_path(u.toLocalFile())

    # ---------- actions ----------
    def add_game(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose the game .exe", "", "Programs (*.exe);;All files (*)")
        if path:
            self.add_path(path)

    def add_path(self, path):
        path = os.path.normpath(path)
        if any(g["path"] == path for g in self.games):
            self.toast("Already in your library")
            return
        name = os.path.splitext(os.path.basename(path))[0].replace("_", " ")
        self.games.append({"name": name, "path": path, "cover": extract_icon(path), "last_played": 0, "playtime": 0})
        jsave(DB, self.games)
        self.populate()
        self.toast(f"Added {name}")

    def refresh_live(self):
        for c in self.cards:
            c.update()
        for i in range(self.recent_box.count()):
            w = self.recent_box.itemAt(i).widget()
            if w:
                w.update()

    def launch(self, g):
        if id(g) in RUNNING:
            self.toast(f"{g['name']} is already running")
            return
        if not os.path.exists(g["path"]):
            QMessageBox.warning(self, "Lightcat", "Game file not found. Was it moved or deleted?")
            return
        h = run_game(g["path"])
        if h is None:
            QMessageBox.warning(self, "Lightcat", "Couldn't start the game.")
            return
        g["last_played"] = time.time()
        jsave(DB, self.games)
        self.toast(f"Launching {g['name']}…")
        if h:
            RUNNING[id(g)] = time.time()
            self.live.start()
            threading.Thread(target=self.wait_game, args=(g, h), daemon=True).start()
        if S["minimize"]:
            self.showMinimized()
        QTimer.singleShot(700, lambda: self.populate(False))

    def wait_game(self, g, h):
        t0 = time.time()
        k32.WaitForSingleObject(h, 0xFFFFFFFF)
        k32.CloseHandle(h)
        self.played.emit(g, time.time() - t0)

    def add_time(self, g, secs):
        RUNNING.pop(id(g), None)
        if not RUNNING:
            self.live.stop()
        if g in self.games:
            self.toast(f"{g['name']} closed  ·  {fmt_hours(secs)}")
            g["playtime"] = g.get("playtime", 0) + secs
            g["last_played"] = time.time()
            jsave(DB, self.games)
            self.populate(False)

    def card_menu(self, g, pos):
        m = self.make_menu()
        a_pin = m.addAction("Unpin" if g.get("pinned") else "Pin")
        a_loc = m.addAction("File location")
        m.addSeparator()
        a1, a2, a3 = m.addAction("Change cover"), m.addAction("Rename"), m.addAction("Delete game")
        act = m.exec(pos)
        if act == a_loc:
            path = os.path.normpath(g["path"])
            if os.path.exists(path):
                subprocess.Popen(f'explorer /select,"{path}"')
            else:
                os.startfile(os.path.dirname(path)) if os.path.isdir(os.path.dirname(path)) else None
            return
        if act == a_pin:
            if g.get("pinned"):
                g.pop("pinned")
            else:
                g["pinned"] = time.time()
        elif act == a1:
            p, _ = QFileDialog.getOpenFileName(self, "Choose a cover image", "", "Images (*.png *.jpg *.jpeg *.webp)")
            if not p:
                return
            dest = os.path.join(COVERS, f"{int(time.time() * 1000)}{os.path.splitext(p)[1]}")
            shutil.copy(p, dest)
            g["cover"] = dest
        elif act == a2:
            n, ok = QInputDialog.getText(self, "Rename", "Game name:", text=g["name"])
            if not (ok and n.strip()):
                return
            g["name"] = n.strip()
        elif act == a3:
            q = QMessageBox.question(self, "Delete game", f"Remove '{g['name']}' from the launcher?\n(The game files stay on your PC.)")
            if q != QMessageBox.Yes:
                return
            self.games.remove(g)
        else:
            return
        jsave(DB, self.games)
        self.populate(False)

    def clear_library(self):
        if QMessageBox.question(self, "Clear library", "Remove ALL games from the launcher?\n(Game files stay on your PC.)") == QMessageBox.Yes:
            self.games.clear()
            jsave(DB, self.games)
            self.populate()


def already_running():
    """If Lightcat is already open (or in the tray), ask it to show itself and return True."""
    sock = QLocalSocket()
    sock.connectToServer(APP_KEY)
    if sock.waitForConnected(500):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
        return True
    return False


if __name__ == "__main__":
    app = QApplication(sys.argv)
    if already_running():  # only one Lightcat at a time
        sys.exit(0)
    server = QLocalServer()
    QLocalServer.removeServer(APP_KEY)
    server.listen(APP_KEY)
    if os.path.exists(LOGO):
        app.setWindowIcon(QIcon(LOGO))
    app.setQuitOnLastWindowClosed(False)
    w = Launcher()

    def on_new_instance():
        c = server.nextPendingConnection()
        if c:
            c.readyRead.connect(c.readAll)
            c.disconnected.connect(c.deleteLater)
        w.show_window()

    server.newConnection.connect(on_new_instance)
    w.showMaximized() if S.get("max") else w.show()
    w.tint_titlebar()
    sys.exit(app.exec())
