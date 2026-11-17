#!/bin/bash
# Preparación de WebWatch (la lanza la app sola la primera vez y tras cada actualización).
RES="$(cd "$(dirname "$0")" && pwd)"
SUP="$HOME/Library/Application Support/WebWatch"
CODE="$SUP/app"
VENV="$SUP/venv"
LOG="$SUP/install.log"
VER="$(cat "$RES/app/VERSION")"
FIRST=0; [ -x "$VENV/bin/python" ] || FIRST=1
mkdir -p "$SUP"
echo "=== $(date) · preparando WebWatch $VER" >>"$LOG"

say(){ osascript -e "display notification \"$1\" with title \"WebWatch\"" >/dev/null 2>&1; echo "· $1" >>"$LOG"; }
dialog(){ # dialog "texto" "Botón1" ["Botón2"]  -> imprime el botón pulsado
  local b="\"$2\""; [ -n "${3:-}" ] && b="\"$3\", \"$2\""
  local q="display dialog \"$1\" with title \"WebWatch\" buttons {$b} default button \"$2\""
  osascript -e "button returned of ($q with icon POSIX file \"$RES/icon.icns\")" 2>/dev/null \
    || osascript -e "button returned of ($q with icon note)" 2>/dev/null
}
fail(){
  echo "ERROR: $1" >>"$LOG"
  if [ "$(dialog "No he podido terminar de preparar WebWatch.\n\n$1" "Ver detalles" "Cerrar")" = "Ver detalles" ]; then open -a TextEdit "$LOG"; fi
  exit 1
}

# 1) Python
PY=""
for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /usr/bin/python3; do
  if [ -x "$c" ] && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  if [ "$(dialog "WebWatch necesita las «Herramientas de línea de comandos» de Apple (gratis, unos minutos).\n\nPulsa Instalar, espera a que terminen y vuelve a abrir WebWatch." "Instalar" "Cancelar")" = "Instalar" ]; then
    xcode-select --install >/dev/null 2>&1
  fi
  exit 1
fi

if [ $FIRST = 1 ]; then
  [ "$(dialog "Bienvenido a WebWatch 👁\n\nLa primera vez necesito preparar unas cosas (1-3 minutos, hace falta internet). Te aviso con una notificación cuando esté listo." "Empezar" "Cancelar")" = "Empezar" ] || exit 1
  say "Preparando WebWatch… (1-3 min)"
fi

# 2) Programa (los datos del usuario no se tocan)
pkill -f "WebWatch/app/macapp.py" 2>/dev/null
pkill -f "WebWatch/app/webwatch.py serve" 2>/dev/null
rm -rf "$CODE.new" && cp -R "$RES/app" "$CODE.new" && rm -rf "$CODE" && mv "$CODE.new" "$CODE" \
  || fail "No pude copiar los archivos del programa."

# 3) Librerías
if [ -e "$VENV/bin/python" ] && ! "$VENV/bin/python" -c 'import sys' >/dev/null 2>&1; then rm -rf "$VENV"; FIRST=1; fi
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV" >>"$LOG" 2>&1 || fail "No pude crear el entorno de Python."
[ $FIRST = 1 ] && say "Descargando componentes…"
"$VENV/bin/python" -m pip install -q --upgrade pip >>"$LOG" 2>&1
"$VENV/bin/python" -m pip install -q -r "$CODE/requirements.txt" >>"$LOG" 2>&1 \
  || fail "Falló la descarga de componentes. ¿Hay conexión a internet?"

# 3b) Mac con Apple Silicon: el Python de Apple se declara «universal2» y pip puede instalar el driver
#     de Playwright solo para Intel. Entonces el driver y Chrome corren emulados con Rosetta (lentos y
#     con fallos al abrir el navegador del bot). Se fuerza la versión arm64.
if [ "$(uname -m)" = "arm64" ]; then
  NODE="$("$VENV/bin/python" -c 'import os, playwright; print(os.path.join(os.path.dirname(playwright.__file__), "driver", "node"))' 2>/dev/null)"
  if [ -f "$NODE" ] && ! lipo -archs "$NODE" 2>/dev/null | grep -q arm64; then
    PWV="$("$VENV/bin/python" -c 'from importlib.metadata import version; print(version("playwright"))')"
    TMPW="$(mktemp -d)"
    if "$VENV/bin/python" -m pip download -q "playwright==$PWV" --no-deps --only-binary=:all: \
         --platform macosx_11_0_arm64 -d "$TMPW" >>"$LOG" 2>&1; then
      "$VENV/bin/python" -m pip install -q --force-reinstall --no-deps "$TMPW"/playwright-*.whl >>"$LOG" 2>&1 \
        && echo "· Playwright arm64 instalado" >>"$LOG"
    fi
    rm -rf "$TMPW"
  fi
fi

# 4) Navegador del bot
if [ -z "${WW_SKIP_BROWSER:-}" ] && [ ! -d "/Applications/Google Chrome.app" ] && [ ! -d "$HOME/Applications/Google Chrome.app" ] \
   && [ ! -d "$HOME/Library/Caches/ms-playwright" ]; then
  say "Descargando el navegador del bot (~150 MB)…"
  "$VENV/bin/python" -m playwright install chromium >>"$LOG" 2>&1 || echo "AVISO: sin Chromium" >>"$LOG"
fi

# 4b) Intérprete con identidad propia: sin esto el Dock muestra «Python» con el cohete y, si lo fijas,
#     fija Python.app en vez de WebWatch. Si algo falla, el lanzador usa el Python normal.
build_runtime(){
  local RT="$SUP/runtime/WebWatch.app" X BASE STUB REL LIB
  BASE="$("$VENV/bin/python" -c 'import sys; print(sys.base_prefix)' 2>/dev/null)" || return 1
  STUB="$BASE/Resources/Python.app/Contents/MacOS/Python"
  [ -x "$STUB" ] || return 1
  # Solo se crea una vez (y si cambia el Python base): rehacer un .app en cada actualización hace que
  # macOS muestre «Se ha impedido que WebWatch pueda modificar apps».
  local SIG; SIG="2|$STUB|$(shasum "$STUB" 2>/dev/null | cut -c1-40)"
  if [ -x "$RT/Contents/MacOS/webwatch-python" ] && [ "$(cat "$SUP/runtime/.built" 2>/dev/null)" = "$SIG" ]; then
    return 0
  fi
  rm -rf "$SUP/runtime" && mkdir -p "$RT/Contents/MacOS" "$RT/Contents/Resources" || return 1
  X="$RT/Contents/MacOS/webwatch-python"
  cp "$STUB" "$X" || return 1
  # El stub enlaza el framework con una ruta relativa a su sitio original: la hacemos absoluta.
  REL="$(otool -L "$STUB" | awk '/@executable_path/ {print $1; exit}')"
  if [ -n "$REL" ]; then
    LIB="$(cd "$(dirname "$STUB")" && cd "$(dirname "${REL#@executable_path/}")" && pwd)/$(basename "$REL")"
    [ -e "$LIB" ] || return 1
    install_name_tool -change "$REL" "$LIB" "$X" 2>/dev/null || return 1
  fi
  codesign -f -s - "$X" >/dev/null 2>&1 || return 1
  cp "$RES/icon.icns" "$RT/Contents/Resources/icon.icns" 2>/dev/null
  cat > "$RT/Contents/MacOS/WebWatch" <<'EOS'
#!/bin/bash
# Si fijas WebWatch en el Dock, se fija este bundle: abre la app de verdad.
APP="$(cat "$HOME/Library/Application Support/WebWatch/app_path.txt" 2>/dev/null)"
[ -x "$APP/Contents/MacOS/WebWatch" ] || APP="/Applications/WebWatch.app"
exec "$APP/Contents/MacOS/WebWatch" "$@"
EOS
  chmod +x "$RT/Contents/MacOS/WebWatch"
  cat > "$RT/Contents/Info.plist" <<EOS
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>com.webwatch.app.runtime</string>
  <key>CFBundleName</key><string>WebWatch</string>
  <key>CFBundleDisplayName</key><string>WebWatch</string>
  <key>CFBundleExecutable</key><string>WebWatch</string>
  <key>CFBundleIconFile</key><string>icon.icns</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
EOS
  codesign -f -s - "$RT" >/dev/null 2>&1
  # Prueba de humo: si no arranca con las librerías del venv, se descarta.
  "$X" -s -c 'import site, sys; site.addsitedir(sys.argv[1]); import AppKit, WebKit' \
    "$("$VENV/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" >/dev/null 2>&1 || return 1
  echo "$SIG" > "$SUP/runtime/.built"
}
build_runtime || { echo "AVISO: sin intérprete propio (se usará Python tal cual)" >>"$LOG"; rm -rf "$SUP/runtime"; }

# 5) Revisión automática y barra de menús (solo la primera vez, para respetar lo que cambies en Ajustes)
"$VENV/bin/python" "$CODE/webwatch.py" install >>"$LOG" 2>&1 || echo "AVISO: launchd" >>"$LOG"
if [ $FIRST = 1 ]; then
  "$VENV/bin/python" "$CODE/webwatch.py" login-item on >>"$LOG" 2>&1
  say "¡Listo! WebWatch está arriba a la derecha (👁)"
fi

echo "$VER" > "$SUP/.installed"
echo "=== preparado" >>"$LOG"
exit 0
