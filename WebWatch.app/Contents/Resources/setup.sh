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

# 4) Navegador del bot
if [ -z "${WW_SKIP_BROWSER:-}" ] && [ ! -d "/Applications/Google Chrome.app" ] && [ ! -d "$HOME/Applications/Google Chrome.app" ] \
   && [ ! -d "$HOME/Library/Caches/ms-playwright" ]; then
  say "Descargando el navegador del bot (~150 MB)…"
  "$VENV/bin/python" -m playwright install chromium >>"$LOG" 2>&1 || echo "AVISO: sin Chromium" >>"$LOG"
fi

# 5) Revisión automática y barra de menús (solo la primera vez, para respetar lo que cambies en Ajustes)
"$VENV/bin/python" "$CODE/webwatch.py" install >>"$LOG" 2>&1 || echo "AVISO: launchd" >>"$LOG"
if [ $FIRST = 1 ]; then
  "$VENV/bin/python" "$CODE/webwatch.py" login-item on >>"$LOG" 2>&1
  say "¡Listo! WebWatch está arriba a la derecha (👁)"
fi

echo "$VER" > "$SUP/.installed"
echo "=== preparado" >>"$LOG"
exit 0
