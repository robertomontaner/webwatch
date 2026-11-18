# 👁 WebWatch 2.5 para Mac

Vigila páginas web y te avisa cuando cambian: el estado de la obra de tu piso, ofertas en Amazon o AliExpress, stock... Funciona **sin IA**: solo aplica las reglas que tú le pones. Todo se queda en tu Mac.

## Instalar (como cualquier app de Mac)

**Opción A · con el .dmg clásico (recomendada)**
1. Descomprime el zip y, en Terminal, ejecuta una sola vez:
   ```
   bash ~/Downloads/WebWatch/crear-dmg.sh
   ```
   Se crea `WebWatch-2.4.dmg`, ya firmado. La primera vez macOS puede pedir permiso para que Terminal controle el Finder (es para colocar el fondo y los iconos): acepta.
2. Abre el `.dmg` y **arrastra WebWatch a Aplicaciones**.
3. Abre WebWatch desde Aplicaciones o Launchpad. La primera vez te saluda y se prepara sola (1-3 min). Cuando acaba, te avisa con una notificación.

**Opción B · sin .dmg:** arrastra `WebWatch.app` de la carpeta descomprimida a Aplicaciones. Si macOS la bloquea, ejecuta `bash ~/Downloads/WebWatch/firmar.sh`.

Si abres la app desde el .dmg o desde Descargas, te ofrece copiarse ella sola a Aplicaciones.

**Para actualizar:** WebWatch te avisa cuando hay versión nueva; pulsa **Actualizar** y se cierra unos segundos y se abre ya actualizada (o Ajustes → Actualizaciones → «Buscar ahora»). Conserva tus webs, tus ajustes y tu historial.

**Si macOS dice que no puede abrirla:** ve a Ajustes del Sistema → Privacidad y seguridad → «Abrir igualmente», o ejecuta `firmar.sh`. Con el .dmg creado en tu propio Mac no debería pasar.

## Dónde verlo

- **Ventana:** muestra tus webs con su estado. En los productos verás el precio, la variación y un gráfico. Haz clic en una web para ver el detalle y su historial.
- **Barra de menús (👁):** muestra las últimas alertas (clic para abrir la web), un botón para revisar ahora, otro para pausar y acceso al CSV. Mientras revisa, enseña qué está haciendo. Si cierras la ventana, la app sigue aquí.
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

Al encender el Mac, WebWatch puede abrir la ventana, quedarse solo en la barra de menús o no abrirse (Ajustes → Al encender el Mac).


Cada 10 minutos, macOS lanza WebWatch y este revisa solo las webs a las que les toca, según su frecuencia (la general o la de cada web). Las revisiones que se perdieron se hacen así:

- **Mac dormido:** al despertar.
- **Mac apagado:** al encenderlo e iniciar sesión.
- **Sin internet:** espera a que vuelva la conexión, sin dar error.
- **Web que ha fallado:** la reintenta a los 30 minutos.

Con el Mac dormido no puede revisar.

## Avisos y registros

- **Notificación del Mac.** Al pulsarla se abre la web. La primera vez macOS te pide permiso para WebWatch.
- **Horas de silencio.** En Ajustes eliges un horario sin notificaciones; en Telegram llegan sin sonar.
- **Captura.** En las opciones avanzadas de cada web puedes pedir una captura de la página cuando avise (se guarda en `capturas/` y se manda por Telegram).
- **Telegram.** Los pasos están dentro de Ajustes. Además puedes escribirle al bot: `/estado`, `/revisar` (o `/revisar 2`), `/objetivo 2 49,99` y `/pausa`. El token se guarda en el Llavero del Mac.
- **CSV.** `observaciones.csv` guarda una fila por cada observación (fecha, web, estado, valor, precio, stock, título, detalle). Usa el separador `;` para que las hojas de cálculo en español lo abran bien; lo puedes cambiar en Ajustes.
- **Copia de tus webs.** Ajustes → Exportar guarda la lista en Descargas; Importar la carga en otro Mac.

Todo está en `~/Library/Application Support/WebWatch/`. Para abrir esa carpeta: Ajustes → Abrir carpeta.

## Amazon y AliExpress

- **Lectura:** WebWatch reconoce las dos tiendas y saca solo el precio, el título y el stock, sin selector.
- **Navegador:** usa tu Google Chrome con un perfil aparte, así que tu Chrome no se toca. Si no tienes Chrome, el instalador descarga Chromium.
- **Captcha:** si una tienda pide captcha, te avisa una vez (notificación y Telegram) y verás el botón **Resolver**. Se abre el navegador del bot, lo resuelves y cierras la ventana: al cerrarla revisa enseguida esa tienda. Mientras no lo resuelvas, solo lo reintenta cada 6 horas (insistir hace que la tienda desconfíe más). En ese navegador también puedes aceptar cookies o elegir país.
- **Frecuencia:** mínimo cada 2 horas (la app no deja menos en estas tiendas). Amazon no permite el acceso automatizado en sus condiciones de uso; con una frecuencia baja y para uso personal (como hacen Keepa o CamelCamelCamel) normalmente no pasa nada, pero pueden bloquear.

## Problemas frecuentes

- **«No se puede abrir porque es de un desarrollador no identificado»:** ejecuta `bash ~/Downloads/WebWatch/firmar.sh` (paso 2 de la instalación).
- **No veo notificaciones:** ve a Ajustes del Sistema → Notificaciones y activa «WebWatch».
- **«No encuentro el precio»:** en Opciones avanzadas pulsa **🎯 Elegir en la página**: se abre la página y haces clic en el precio.
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
