#!/bin/bash
# ------------------------------------------------------------------
#  crear-dmg.sh · crea WebWatch-<versión>.dmg, el típico de Mac:
#  lo abres, arrastras WebWatch a Aplicaciones y listo.
#
#  Uso (en Terminal, en tu Mac):   bash crear-dmg.sh
#  Opcional, firma Developer ID:   bash crear-dmg.sh "Developer ID Application: Nombre (TEAMID)"
# ------------------------------------------------------------------
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/WebWatch.app"
IDENTITY="${1:--}"
VER="$(cat "$APP/Contents/Resources/app/VERSION")"
VOL="WebWatch"
OUT="$HERE/WebWatch-$VER.dmg"
G=$'\033[32m'; Y=$'\033[33m'; B=$'\033[1m'; N=$'\033[0m'
[ "$(uname)" = "Darwin" ] || { echo "Este script se ejecuta en macOS."; exit 1; }
[ -d "$APP" ] || { echo "No encuentro WebWatch.app junto a este script."; exit 1; }

echo "${B}1) Preparando y firmando la app${N}"
STAGE="$(mktemp -d)"; TMP="$(mktemp -u).dmg"
trap 'rm -rf "$STAGE" "$TMP"; hdiutil detach "/Volumes/$VOL" -quiet 2>/dev/null || true' EXIT
xattr -dr com.apple.quarantine "$HERE" 2>/dev/null || true
ditto "$APP" "$STAGE/WebWatch.app"
chmod +x "$STAGE/WebWatch.app/Contents/MacOS/WebWatch" "$STAGE/WebWatch.app/Contents/Resources/setup.sh"
xattr -cr "$STAGE/WebWatch.app"
if [ "$IDENTITY" = "-" ]; then
  codesign --force --deep --sign - "$STAGE/WebWatch.app"
else
  codesign --force --deep --options runtime --timestamp --sign "$IDENTITY" "$STAGE/WebWatch.app"
fi
codesign --verify --deep --strict "$STAGE/WebWatch.app" && echo "   ${G}✓${N} firmada"

echo "${B}2) Montando la ventana del instalador${N}"
ln -s /Applications "$STAGE/Aplicaciones"
mkdir "$STAGE/.background"
if tiffutil -cathidpicheck "$HERE/dmg/fondo.png" "$HERE/dmg/fondo@2x.png" -out "$STAGE/.background/fondo.tiff" 2>/dev/null; then
  BG="fondo.tiff"
else
  cp "$HERE/dmg/fondo.png" "$STAGE/.background/fondo.png"; BG="fondo.png"
fi
cp "$APP/Contents/Resources/icon.icns" "$STAGE/.VolumeIcon.icns"
hdiutil detach "/Volumes/$VOL" -quiet 2>/dev/null || true
hdiutil create -quiet -volname "$VOL" -srcfolder "$STAGE" -fs HFS+ -format UDRW -ov "$TMP"
hdiutil attach -quiet -readwrite -noverify -noautoopen "$TMP"
command -v SetFile >/dev/null && SetFile -a C "/Volumes/$VOL" || true

# Colocación de iconos y fondo (la primera vez macOS pide permiso para controlar el Finder: acepta).
# Con tiempo límite: en GitHub Actions el Finder a veces no responde y se quedaría colgado.
if perl -e 'alarm shift; exec @ARGV' 90 osascript <<EOF
tell application "Finder"
  tell disk "$VOL"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {200, 120, 860, 520}
    set opts to the icon view options of container window
    set arrangement of opts to not arranged
    set icon size of opts to 128
    set text size of opts to 13
    set background picture of opts to file ".background:$BG"
    set position of item "WebWatch.app" of container window to {170, 200}
    set position of item "Aplicaciones" of container window to {490, 200}
    update without registering applications
    delay 1
    close
  end tell
end tell
EOF
then echo "   ${G}✓${N} ventana con fondo y flecha"
else echo "   ${Y}!${N} No pude colocar los iconos (permiso del Finder). El .dmg funciona igual, sin fondo."; fi
sync; sleep 1
hdiutil detach "/Volumes/$VOL" -quiet

echo "${B}3) Comprimiendo${N}"
rm -f "$OUT"
hdiutil convert -quiet "$TMP" -format UDZO -imagekey zlib-level=9 -o "$OUT"
[ "$IDENTITY" != "-" ] && codesign --sign "$IDENTITY" --timestamp "$OUT"
echo
echo "${G}${B}✓ Creado: $OUT${N}"
echo "  Ábrelo con doble clic y arrastra WebWatch a Aplicaciones."
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "dmg=$OUT" >> "$GITHUB_OUTPUT"   # para que el workflow sepa qué subir
elif [ -z "${CI:-}" ]; then
  open -R "$OUT"
fi
