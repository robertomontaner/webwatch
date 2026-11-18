# Instrucciones para asistentes de IA (Claude, Codex, Cursor, Copilot…)

WebWatch es una app de Mac (bundle `WebWatch.app`) escrita en Python + bash. Lee esto antes de tocar nada.

## Versiones y releases: OBLIGATORIO

Cada cambio que se publique para los usuarios necesita **subir la versión**. Sin eso no se crea el .dmg
ni le llega la actualización a la app instalada.

1. Sube el número en **los dos archivos, con el mismo valor**:
   - `WebWatch.app/Contents/Resources/app/VERSION` (solo el número, p. ej. `2.5.1`)
   - `WebWatch.app/Contents/Info.plist` → `CFBundleShortVersionString` y `CFBundleVersion`
2. Formato `MAYOR.MENOR.PARCHE`: parche = arreglos, menor = funciones nuevas, mayor = cambios grandes.
3. Commit y push a `main`.

Qué pasa después, solo:
- `.github/workflows/release.yml` detecta que cambió `VERSION`, crea `WebWatch-<versión>.dmg` con
  `crear-dmg.sh` en un Mac de GitHub y publica la release `v<versión>`. Si la release ya existe no hace
  nada; si `VERSION` e `Info.plist` no coinciden, falla.
- La app instalada consulta la última release de GitHub y ofrece actualizarse (autoupdater en
  `webwatch.py`, funciones `check_update` / `install_update`). Compara con `VERSION`.

No crees tags ni releases a mano. No publiques sin que el usuario lo pida (commit y push solo cuando lo diga).

## Estructura

- `WebWatch.app/Contents/MacOS/WebWatch`: lanzador bash. Se relanza en arm64 si macOS lo abre con Rosetta.
- `WebWatch.app/Contents/Resources/setup.sh`: copia la app a `~/Library/Application Support/WebWatch/app`,
  crea el venv y el runtime (bundle propio para que el Dock diga «WebWatch»). Se ejecuta cuando cambia `VERSION`.
- `Resources/app/webwatch.py`: toda la lógica (revisiones, Telegram, servidor del panel en 127.0.0.1:8750, updater).
- `Resources/app/macapp.py`: barra de menús, Dock y ventana (PyObjC + WKWebView).
- `Resources/app/web/index.html`: el panel.
- Datos del usuario: `~/Library/Application Support/WebWatch` (config, historial, perfil del navegador del bot).
  Para probar sin tocarlos usa `WEBWATCH_DATA=/otra/carpeta`; ojo, si importas `webwatch.py` desde el repo
  sin esa variable, los datos van a `WebWatch.app/Contents/Resources/`.

## Probar en local

- Instalar lo del repo: `ditto WebWatch.app /Applications/WebWatch.app && codesign --force --deep -s - /Applications/WebWatch.app`
  y abrirla; como cambia `VERSION`, `setup.sh` se ejecuta solo.
- Crear el .dmg: `bash crear-dmg.sh`.
- Para matar la app desde un shell usa `pkill -f "[m]acapp.py"` (sin los corchetes se mata el propio shell).

## Seguimiento

El estado del proyecto y el backlog están en Notion (página «Webwatch»).
