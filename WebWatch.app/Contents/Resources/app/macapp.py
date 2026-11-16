#!/usr/bin/env python3
"""
WebWatch - app nativa de macOS.
  · Ventana propia con el panel (WKWebView)
  · Icono en la barra de menús con las últimas alertas
  · Icono en el Dock con contador de alertas y menú (clic derecho)
  · Menús superiores: WebWatch, Archivo, Edición, Visualización, Ventana, Ayuda
Al cerrar la ventana la app sigue en la barra de menús (y desaparece del Dock).
"""
import fcntl
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import webwatch as ww  # noqa: E402

import objc  # noqa: E402
from AppKit import (  # noqa: E402
    NSApplication, NSApplicationActivationPolicyAccessory, NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered, NSImage, NSMenu, NSMenuItem, NSStatusBar, NSVariableStatusItemLength, NSWindow,
    NSWorkspace,
)
from Foundation import NSBundle, NSMakeRect, NSMakeSize, NSObject, NSTimer, NSURL, NSURLRequest  # noqa: E402
from PyObjCTools import AppHelper  # noqa: E402
from WebKit import WKWebView, WKWebViewConfiguration  # noqa: E402

URL = f"http://127.0.0.1:{ww.PORT}/?app=1"
CMD, SHIFT, OPT = 1 << 20, 1 << 17, 1 << 19
DELEGATE = None


def app():
    return NSApplication.sharedApplication()


def short(s, n=44):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def ago(t):
    try:
        d = time.time() - ww.ts(t)
    except Exception:  # noqa: BLE001
        return "nunca"
    if d < 60:
        return "ahora mismo"
    if d < 3600:
        return f"hace {int(d // 60)} min"
    if d < 86400:
        return f"hace {int(d // 3600)} h"
    return f"hace {int(d // 86400)} d"


def start_server():
    if ww.ping():
        return
    threading.Thread(target=ww.serve_forever, kwargs={"idle": False}, daemon=True).start()
    for _ in range(50):
        if ww.ping():
            return
        time.sleep(0.1)


class AppDelegate(NSObject):

    # ------------------------------------------------------------ ciclo de vida
    def applicationDidFinishLaunching_(self, note):
        self.win = None
        self.web = None
        self.running = False
        self.unseen = 0
        start_server()
        icon = NSImage.alloc().initWithContentsOfFile_(str(ww.BASE / "icon.icns"))
        if icon is not None:
            app().setApplicationIconImage_(icon)
        self.build_main_menu()
        self.status = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self.status_menu = NSMenu.alloc().init()
        self.status_menu.setAutoenablesItems_(False)
        self.status.setMenu_(self.status_menu)
        self.dock_menu = NSMenu.alloc().init()
        self.dock_menu.setAutoenablesItems_(False)
        self.refresh_(None)
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            15.0, self, "refresh:", None, True)
        if "--background" not in sys.argv:
            self.showWindow_(None)

    def applicationShouldHandleReopen_hasVisibleWindows_(self, sender, flag):
        self.showWindow_(None)
        return True

    def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
        return False

    def applicationDockMenu_(self, sender):
        return self.dock_menu

    def windowWillClose_(self, note):
        app().setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    # ------------------------------------------------------------ utilidades
    @objc.python_method
    def mi(self, title, action=None, key="", mods=None, target=None, chain=False, enabled=True, obj=None):
        it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
        if action and not chain:
            it.setTarget_(target if target is not None else self)
        if mods is not None:
            it.setKeyEquivalentModifierMask_(mods)
        if obj is not None:
            it.setRepresentedObject_(obj)
        it.setEnabled_(enabled)
        return it

    @objc.python_method
    def js(self, code):
        if self.web is not None:
            self.web.evaluateJavaScript_completionHandler_(code, None)

    @objc.python_method
    def show(self, tab=None):
        """Muestra la ventana (y el icono del Dock). tab: webs|hist|set|add"""
        A = app()
        A.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        if self.win is None:
            self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, 1180, 780), 1 | 2 | 4 | 8, NSBackingStoreBuffered, False)
            self.win.setTitle_("WebWatch")
            self.win.setReleasedWhenClosed_(False)
            self.win.setMinSize_(NSMakeSize(760, 540))
            self.win.setDelegate_(self)
            self.win.center()
            self.win.setFrameAutosaveName_("WebWatchMain")
            conf = WKWebViewConfiguration.alloc().init()
            self.web = WKWebView.alloc().initWithFrame_configuration_(self.win.contentView().bounds(), conf)
            self.web.setAutoresizingMask_(2 | 16)
            self.win.contentView().addSubview_(self.web)
            self.web.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(URL + ("#" + tab if tab else ""))))
        elif tab == "add":
            self.js("window.openDlg&&openDlg()")
        elif tab:
            self.js(f"window.gotoTab&&gotoTab('{tab}')")
        self.win.makeKeyAndOrderFront_(None)
        A.activateIgnoringOtherApps_(True)

    @objc.python_method
    def set_status_icon(self):
        btn = self.status.button()
        alert = self.unseen > 0
        img = None
        if hasattr(NSImage, "imageWithSystemSymbolName_accessibilityDescription_"):
            for name in (["eye.trianglebadge.exclamationmark", "exclamationmark.circle"] if alert else ["eye"]):
                img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, "WebWatch")
                if img is not None:
                    break
        count = f" {self.unseen}" if alert else ""
        if img is not None:
            img.setTemplate_(True)
            btn.setImage_(img)
            btn.setImagePosition_(2)  # imagen a la izquierda del texto
            btn.setTitle_(count)
        else:
            btn.setTitle_("👁" + count)
        btn.setToolTip_(f"WebWatch · {self.unseen} alertas sin ver" if alert else "WebWatch")

    @objc.python_method
    def build_main_menu(self):
        A = app()
        main = NSMenu.alloc().init()

        def sub(title):
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            m = NSMenu.alloc().initWithTitle_(title)
            item.setSubmenu_(m)
            main.addItem_(item)
            return m

        sep = NSMenuItem.separatorItem
        m = sub("WebWatch")
        m.addItem_(self.mi("Acerca de WebWatch", "orderFrontStandardAboutPanel:", target=A))
        m.addItem_(sep())
        m.addItem_(self.mi("Ajustes…", "openSettings:", ","))
        m.addItem_(sep())
        m.addItem_(self.mi("Ocultar WebWatch", "hide:", "h", target=A))
        m.addItem_(self.mi("Ocultar otros", "hideOtherApplications:", "h", mods=CMD | OPT, target=A))
        m.addItem_(self.mi("Mostrar todo", "unhideAllApplications:", target=A))
        m.addItem_(sep())
        m.addItem_(self.mi("Salir de WebWatch", "terminate:", "q", target=A))

        m = sub("Archivo")
        m.addItem_(self.mi("Añadir web…", "addWatch:", "n"))
        m.addItem_(self.mi("Revisar ahora", "runNow:", "r"))
        m.addItem_(sep())
        m.addItem_(self.mi("Abrir CSV de observaciones", "openCSV:"))
        m.addItem_(self.mi("Abrir Excel", "openExcel:"))
        m.addItem_(self.mi("Abrir carpeta de datos", "openFolder:"))
        m.addItem_(sep())
        m.addItem_(self.mi("Cerrar ventana", "performClose:", "w", chain=True))

        m = sub("Edición")  # necesario para copiar/pegar en los campos del panel
        m.addItem_(self.mi("Deshacer", "undo:", "z", chain=True))
        m.addItem_(self.mi("Rehacer", "redo:", "Z", chain=True))
        m.addItem_(sep())
        m.addItem_(self.mi("Cortar", "cut:", "x", chain=True))
        m.addItem_(self.mi("Copiar", "copy:", "c", chain=True))
        m.addItem_(self.mi("Pegar", "paste:", "v", chain=True))
        m.addItem_(self.mi("Seleccionar todo", "selectAll:", "a", chain=True))

        m = sub("Visualización")
        m.addItem_(self.mi("Webs", "showWebs:", "1"))
        m.addItem_(self.mi("Historial", "showHistory:", "2"))
        m.addItem_(self.mi("Ajustes", "openSettings:", "3"))
        m.addItem_(sep())
        m.addItem_(self.mi("Recargar panel", "reloadPanel:", "r", mods=CMD | SHIFT))

        m = sub("Ventana")
        m.addItem_(self.mi("Minimizar", "performMiniaturize:", "m", chain=True))
        m.addItem_(self.mi("Zoom", "performZoom:", chain=True))
        m.addItem_(sep())
        m.addItem_(self.mi("Traer todo al frente", "arrangeInFront:", target=A))
        A.setWindowsMenu_(m)

        m = sub("Ayuda")
        m.addItem_(self.mi("Ayuda de WebWatch", "openHelp:", "?"))
        m.addItem_(self.mi("Ver registro técnico", "openLog:"))
        A.setHelpMenu_(m)
        A.setMainMenu_(main)

    # ------------------------------------------------------------ acciones (selectores)
    def showWindow_(self, sender):
        self.show()

    def showWebs_(self, sender):
        self.show("webs")

    def showHistory_(self, sender):
        self.show("hist")

    def openSettings_(self, sender):
        self.show("set")

    def addWatch_(self, sender):
        self.show("add")

    def reloadPanel_(self, sender):
        if self.web is not None:
            self.web.reload_(None)

    def openURL_(self, sender):
        url = sender.representedObject()
        if url:
            NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(url))

    def openExcel_(self, sender):
        ww.open_path(ww.ensure_excel(ww.load_config()))

    def openCSV_(self, sender):
        p = ww.csv_path(ww.load_config())
        ww.open_path(p if p.exists() else ww.DATA)

    def openFolder_(self, sender):
        ww.open_path(ww.DATA)

    def openLog_(self, sender):
        ww.LOG_PATH.touch()
        ww.open_path(ww.LOG_PATH)

    def openHelp_(self, sender):
        p = ww.BASE / "LEEME.md"
        ww.open_path(p if p.exists() else ww.DATA)

    def togglePause_(self, sender):
        cfg = ww.load_config()
        cfg["paused"] = not cfg.get("paused")
        ww.save_config(cfg)
        self.refresh_(None)
        self.js("window.load&&load()")

    def runNow_(self, sender):
        if self.running:
            return
        self.running = True
        self.refresh_(None)

        def work():
            with objc.autorelease_pool():
                try:
                    ww.run_checks()
                except Exception as e:  # noqa: BLE001
                    print("Revisión:", e, flush=True)
                self.running = False
                self.performSelectorOnMainThread_withObject_waitUntilDone_("afterRun:", None, False)

        threading.Thread(target=work, daemon=True).start()

    def afterRun_(self, obj):
        self.refresh_(None)
        self.js("window.load&&load()")

    # ------------------------------------------------------------ menú de la barra y del Dock
    def refresh_(self, timer):
        try:
            cfg = ww.load_config()
            state = ww.load_json(ww.STATE_PATH, {})
            hist = ww.load_json(ww.HISTORY_PATH, [])
            seen = ww.load_json(ww.UI_PATH, {}).get("seen", "")
        except Exception as e:  # noqa: BLE001
            print("refresh:", e, flush=True)
            return
        alerts = [h for h in hist if h.get("status") == "ALERTA"]
        self.unseen = sum(1 for h in alerts if h.get("t", "") > seen)
        app().dockTile().setBadgeLabel_(str(self.unseen) if self.unseen else "")
        self.set_status_icon()
        times = [s["last"]["t"] for s in state.values() if s.get("last")]
        n = sum(1 for w in cfg["watches"] if w.get("enabled", True))
        paused = cfg.get("paused")
        errors = [w["name"] for w in cfg["watches"] if state.get(w["id"], {}).get("errors")]

        M = self.status_menu
        M.removeAllItems()
        sep = NSMenuItem.separatorItem
        M.addItem_(self.mi(f"WebWatch · {n} webs vigiladas", enabled=False))
        M.addItem_(self.mi("⏳ Revisando…" if self.running else
                           f"Última revisión: {ago(max(times)) if times else 'nunca'}", enabled=False))
        if paused:
            M.addItem_(self.mi("⏸ Revisión automática en pausa", enabled=False))
        if errors:
            M.addItem_(self.mi(f"⚠️ Con problemas: {short(', '.join(errors), 40)}", "showWindow:"))
        M.addItem_(sep())
        M.addItem_(self.mi("Revisar ahora", "runNow:", "r", enabled=not self.running))
        M.addItem_(self.mi("Abrir WebWatch", "showWindow:", "o"))
        M.addItem_(self.mi("Añadir web…", "addWatch:", "n"))
        M.addItem_(sep())
        M.addItem_(self.mi(f"Alertas recientes{f' · {self.unseen} sin ver' if self.unseen else ''}", enabled=False))
        recent = alerts[-6:][::-1]
        if not recent:
            M.addItem_(self.mi("    Ninguna todavía", enabled=False))
        for h in recent:
            dot = "● " if h["t"] > seen else "    "
            it = self.mi(f"{dot}{short(h['name'], 26)} — {short(h.get('detail') or h.get('note'), 42)}",
                         "openURL:", obj=h["url"])
            it.setToolTip_(f"{h['t']}\n{h.get('detail', '')}\nClic para abrir la web")
            M.addItem_(it)
        if alerts:
            M.addItem_(self.mi("    Ver todo el historial…", "showHistory:"))
        M.addItem_(sep())
        p = self.mi("Pausar revisión automática", "togglePause:")
        p.setState_(1 if paused else 0)
        M.addItem_(p)
        M.addItem_(self.mi("Abrir CSV de observaciones", "openCSV:"))
        M.addItem_(self.mi("Abrir Excel", "openExcel:"))
        M.addItem_(self.mi("Ajustes…", "openSettings:", ","))
        M.addItem_(sep())
        M.addItem_(self.mi("Salir de WebWatch", "terminate:", "q", target=app()))

        D = self.dock_menu
        D.removeAllItems()
        D.addItem_(self.mi("Revisando…" if self.running else "Revisar ahora", "runNow:", enabled=not self.running))
        D.addItem_(self.mi("Añadir web…", "addWatch:"))
        if self.unseen:
            D.addItem_(self.mi(f"Ver {self.unseen} alertas sin ver", "showHistory:"))
        p2 = self.mi("Pausar revisión automática", "togglePause:")
        p2.setState_(1 if paused else 0)
        D.addItem_(p2)


def main():
    ww.load_config()
    lock = open(ww.DATA / ".app.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)  # ya está abierta
    try:  # nombre en la barra de menús (si no, macOS pondría «Python»)
        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = "WebWatch"
    except Exception:  # noqa: BLE001
        pass
    A = app()
    A.setActivationPolicy_(NSApplicationActivationPolicyAccessory if "--background" in sys.argv
                           else NSApplicationActivationPolicyRegular)
    global DELEGATE
    DELEGATE = AppDelegate.alloc().init()
    A.setDelegate_(DELEGATE)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
