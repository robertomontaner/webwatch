# 👁 WebWatch 2.1 para Mac

Vigila páginas web y te avisa cuando cambian: el estado de la obra de tu piso, ofertas en Amazon o AliExpress, stock... Funciona **sin IA**: solo aplica las reglas que tú le pones. Todo se queda en tu Mac.

## Instalar (como cualquier app de Mac)

**Opción A · con el .dmg clásico (recomendada)**
1. Descomprime el zip y, en Terminal, ejecuta una sola vez:
   ```
   bash ~/Downloads/WebWatch/crear-dmg.sh
   ```
   Se crea `WebWatch-2.1.dmg`, ya firmado. La primera vez macOS puede pedir permiso para que Terminal controle el Finder (es para colocar el fondo y los iconos): acepta.
2. Abre el `.dmg` y **arrastra WebWatch a Aplicaciones**.
3. Abre WebWatch desde Aplicaciones o Launchpad. La primera vez te saluda y se prepara sola (1-3 min). Cuando acaba, te avisa con una notificación.

**Opción B · sin .dmg:** arrastra `WebWatch.app` de la carpeta descomprimida a Aplicaciones. Si macOS la bloquea, ejecuta `bash ~/Downloads/WebWatch/firmar.sh`.

Si abres la app desde el .dmg o desde Descargas, te ofrece copiarse ella sola a Aplicaciones.

**Para actualizar:** arrastra la versión nueva a Aplicaciones y elige «Reemplazar». Al abrirla se actualiza sola y conserva tus webs, tus ajustes y tu historial.

**Si macOS dice que no puede abrirla:** ve a Ajustes del Sistema → Privacidad y seguridad → «Abrir igualmente», o ejecuta `firmar.sh`. Con el .dmg creado en tu propio Mac no debería pasar.

## Dónde verlo

- **Ventana:** muestra tus webs con su estado. En los productos verás el precio, la variación y un gráfico. Haz clic en una web para ver el detalle y su historial.
- **Barra de menús (👁):** muestra las últimas alertas (clic para abrir la web), un botón para revisar ahora, otro para pausar y accesos al CSV y al Excel. Si cierras la ventana, la app sigue aquí.
- **Dock:** muestra un número rojo con las alertas sin ver. Con clic derecho tienes «Revisar ahora» y «Añadir web».
- **Menús de arriba:** Archivo (⌘N añadir, ⌘R revisar), Visualización (⌘1, ⌘2, ⌘3), Ajustes (⌘,) y los demás menús habituales de un Mac.

## Qué puede vigilar

| Tipo | Ejemplo | Cuándo te avisa |
|---|---|---|
| 🔄 Cambios | greenquart.com/estado-obra.php | Cuando cambia el texto (o la zona que elijas). Te dice qué se añadió y qué se quitó. |
| 🏷️ Precio | Producto de Amazon, AliExpress u otra tienda | Si baja de X €, si baja un X %, si marca su mínimo histórico, si vuelve el stock, o con cualquier cambio |
| 🔎 Palabras | «agotado», «plazas disponibles» | Cuando aparece o desaparece una palabra |

Pega el enlace y pulsa **Probar lectura** para ver qué lee el bot antes de guardar. La primera lectura de cada web es la referencia y no genera aviso.

## Cuándo revisa

Cada 10 minutos, macOS lanza WebWatch y este revisa solo las webs a las que les toca, según su frecuencia (la general o la de cada web). Las revisiones que se perdieron se hacen así:

- **Mac dormido:** al despertar.
- **Mac apagado:** al encenderlo e iniciar sesión.
- **Sin internet:** espera a que vuelva la conexión, sin dar error.
- **Web que ha fallado:** la reintenta a los 30 minutos.

Con el Mac dormido no puede revisar.

## Avisos y registros

- **Notificación del Mac.** Si quieres que al pulsarla se abra la web, instala `brew install terminal-notifier`.
- **Telegram.** Los pasos están dentro de Ajustes.
- **CSV.** `observaciones.csv` guarda una fila por cada observación (fecha, web, estado, valor, precio, stock, título, detalle). Usa el separador `;` para que el Excel en español lo abra bien; lo puedes cambiar en Ajustes.
- **Excel.** `webwatch_log.xlsx` tiene dos hojas: «Revisiones» y «Alertas».

Todo está en `~/Library/Application Support/WebWatch/`. Para abrir esa carpeta: Ajustes → Abrir carpeta.

## Amazon y AliExpress

- **Lectura:** WebWatch reconoce las dos tiendas y saca solo el precio, el título y el stock, sin selector.
- **Navegador:** usa tu Google Chrome con un perfil aparte, así que tu Chrome no se toca. Si no tienes Chrome, el instalador descarga Chromium.
- **Captcha:** si una tienda pide captcha, verás un aviso con el botón **Resolver**. Se abre el navegador del bot, lo resuelves una vez y cierras la ventana. Después se recuerda. En ese navegador también puedes aceptar cookies o elegir país.
- **Frecuencia:** revisa cada 2 horas o más. Amazon no permite el acceso automatizado en sus condiciones de uso; con una frecuencia baja y para uso personal (como hacen Keepa o CamelCamelCamel) normalmente no pasa nada, pero pueden bloquear.

## Problemas frecuentes

- **«No se puede abrir porque es de un desarrollador no identificado»:** ejecuta `bash ~/Downloads/WebWatch/firmar.sh` (paso 2 de la instalación).
- **No veo notificaciones:** ve a Ajustes del Sistema → Notificaciones y activa «Editor de Scripts» (o terminal-notifier).
- **«No encuentro el precio»:** en Opciones avanzadas, indica el selector CSS del precio. Para sacarlo: clic derecho sobre el precio → Inspeccionar → Copy selector.
- **Una web carga en blanco:** en Opciones avanzadas, cambia «Cómo leer la página» a «Navegador del bot».
- **Registro técnico:** menú Ayuda → Ver registro técnico.

## firmar.sh

```
bash firmar.sh                       # quita la cuarentena y firma en local (gratis, para tu Mac)
bash firmar.sh /Applications/WebWatch.app "Developer ID Application: Nombre (TEAMID)"
```

La firma local basta para tu Mac. Para pasarle la app a otras personas sin avisos hace falta una cuenta de Apple Developer y notarizarla; los comandos están en el propio script.

## Desinstalar

Haz doble clic en **Desinstalar.command**. Antes de borrar tus datos te pregunta.
