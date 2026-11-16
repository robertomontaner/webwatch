#!/bin/bash
# ------------------------------------------------------------------
#  firmar.sh · quita la cuarentena de macOS y firma WebWatch
#
#  Uso (en Terminal):
#     bash firmar.sh                         -> carpeta descargada + app instalada, firma local
#     bash firmar.sh /ruta/WebWatch.app      -> esa app
#     bash firmar.sh /ruta/WebWatch.app "Developer ID Application: Tu Nombre (TEAMID)"
#
#  · Firma local (ad-hoc, «-»): gratis. Basta para usarla en TU Mac.
#  · Developer ID (99 €/año, Apple Developer): para pasarla a otras personas
#    sin avisos; después hay que notarizarla:
#      ditto -c -k --keepParent WebWatch.app WebWatch.zip
#      xcrun notarytool submit WebWatch.zip --keychain-profile PERFIL --wait
#      xcrun stapler staple WebWatch.app
# ------------------------------------------------------------------
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="${1:-}"
IDENTITY="${2:--}"
G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; B=$'\033[1m'; N=$'\033[0m'

[ "$(uname)" = "Darwin" ] || { echo "Esto es solo para macOS."; exit 1; }

echo "${B}1) Quitando la cuarentena de la carpeta descargada${N}"
xattr -dr com.apple.quarantine "$HERE" 2>/dev/null && echo "   ${G}✓${N} $HERE"
chmod +x "$HERE"/*.command "$HERE"/*.sh 2>/dev/null

if [ -z "$APP" ]; then
  for c in "/Applications/WebWatch.app" "$HOME/Applications/WebWatch.app" "$HERE/WebWatch.app"; do
    [ -d "$c" ] && APP="$c" && break
  done
fi
if [ -z "$APP" ] || [ ! -d "$APP" ]; then
  echo "   ${Y}!${N} No encuentro WebWatch.app."
  exit 0
fi

echo "${B}2) Limpiando atributos extendidos de la app${N}"
xattr -cr "$APP" && echo "   ${G}✓${N} $APP"

if [ "$IDENTITY" = "-" ]; then
  echo "${B}3) Firmando (firma local ad-hoc)${N}"
  codesign --force --deep --sign - "$APP" 2>&1 | sed 's/^/   /'
else
  echo "${B}3) Firmando con: $IDENTITY${N}"
  codesign --force --deep --options runtime --timestamp --sign "$IDENTITY" "$APP" 2>&1 | sed 's/^/   /'
fi

if codesign --verify --deep --strict "$APP" 2>/dev/null; then
  echo "   ${G}✓ Firma válida${N}"
else
  echo "   ${R}✗ La verificación de la firma ha fallado${N}"; exit 1
fi
xattr -dr com.apple.quarantine "$APP" 2>/dev/null

echo "${B}4) Gatekeeper${N}"
if spctl --assess --type execute "$APP" 2>/dev/null; then
  echo "   ${G}✓ Aceptada por Gatekeeper${N}"
else
  echo "   ${Y}i${N} Con firma local Gatekeeper dice «rejected»: es normal. La app abre igual en"
  echo "     este Mac porque ya no tiene cuarentena. Solo una firma Developer ID + notarización"
  echo "     evita el aviso en otros Macs."
fi
echo
echo "${G}Listo.${N}"
