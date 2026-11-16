#!/bin/bash
# WebWatch · desinstalador
SUPPORT="$HOME/Library/Application Support/WebWatch"
echo "Desinstalando WebWatch…"
for L in com.webwatch.bot com.webwatch.menubar; do
  launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/$L.plist" 2>/dev/null
  rm -f "$HOME/Library/LaunchAgents/$L.plist"
done
pkill -f "WebWatch/app/macapp.py" 2>/dev/null
pkill -f "WebWatch/app/webwatch.py" 2>/dev/null
rm -rf "/Applications/WebWatch.app" "$HOME/Applications/WebWatch.app" "$SUPPORT/app" "$SUPPORT/venv"
echo "✓ App y revisión automática quitadas."
echo
read -r -p "¿Borrar también tus datos (webs, CSV, Excel, historial)? [s/N] " a
if [[ "$a" =~ ^[sS]$ ]]; then rm -rf "$SUPPORT"; echo "✓ Datos borrados."
else echo "Tus datos siguen en: $SUPPORT"; fi
read -r -p "Pulsa Enter para cerrar…" _
