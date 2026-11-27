# Mapa Inka 🎧🗺️

**El mapa de la comunidad que siguió el streaming.**

Cada punto muestra una localidad desde donde alguien siguió la transmisión, con el nombre de
usuario y los comentarios que dejó en el chat. Buscá tu ciudad o tu usuario y recorré dónde
está el resto de la comunidad.

- 🌐 **Ver el mapa:** <https://mikelzubimendi.github.io/Expedicion-Inka-2026/>
- ▶️ **Ver el streaming (4 videos):** <https://www.youtube.com/watch?v=CtAJIkQDiyQ>
- 🗺️ **Datos generados desde el chat de los 4 videos** con el script de [`scripts/`](scripts/README.md).

## Qué muestra

Cada marcador es una localidad. Al abrirlo se ve:

- La localidad, la provincia y el país.
- La cantidad de oyentes registrados desde ese lugar.
- El nombre de usuario de cada oyente.
- El mensaje donde nombró su ciudad.
- Los comentarios adicionales que haya dejado en el chat.

La lista lateral se puede buscar por localidad, provincia, usuario o texto de un comentario.
Los botones **Todos / Día 1 / Día 2 / Día 3 / Día 4** filtran los oyentes y comentarios de cada
video, o los muestran todos juntos. El botón del encabezado lleva directo al streaming.

## Funcionalidades

- Mapa oscuro con capa satelital opcional y **botón de modo claro/oscuro** (se recuerda en el
  navegador).
- Agrupado de marcadores (clustering) para ver todo el mundo sin superposición.
- Buscador tolerante a mayúsculas y acentos, que también busca dentro de usuarios y
  comentarios.
- Popups con la lista de oyentes y sus comentarios.
- El encuadre inicial prioriza Argentina y el Cono Sur; **Ver todo el mapa** muestra también
  los oyentes del resto del mundo.
- Diseño adaptativo: panel lateral en escritorio y hoja inferior plegable en celulares.
- Publicación automática en GitHub Pages con cada push a `main`.

## Cómo se generan los datos

El GeoJSON no se edita a mano: se genera a partir de los comentarios del chat de los 4 videos
del streaming. El proceso es manual y a demanda:

```bash
python3 scripts/generar_localidades.py --solo-reporte   # revisar candidatos
python3 scripts/generar_localidades.py                  # escribir localidades.geojson
```

El script:

1. Descarga el chat de los 4 videos con `yt-dlp`.
2. Detecta mensajes donde la gente nombra su ciudad (“desde Salta”, “soy de La Plata”,
   “Córdoba presente”, etc.).
3. Geocodifica con el listado oficial de localidades de Georef y con Nominatim para el resto
   del mundo.
4. Agrupa por localidad y guarda usuario, mensaje, comentarios adicionales y el día de cada
   comentario.

Las frases ya resueltas se guardan en `scripts/diccionario_lugares.json`, así que los
comentarios repetidos se resuelven al instante y las siguientes corridas son mucho más
rápidas. El script muestra el progreso (`usuarios procesados / total`) mientras trabaja.

Los detalles, opciones y correcciones manuales están en [`scripts/README.md`](scripts/README.md).
El archivo `scripts/revision.json` permite excluir usuarios o corregir ubicaciones dudosas
sin tocar el código.

## Ver el sitio localmente

El navegador bloquea `fetch()` al abrir el archivo con `file://`, así que conviene levantar un
servidor local:

```bash
python3 -m http.server 8000
```

Luego abrir <http://localhost:8000>.

## Publicación

El workflow [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) publica el sitio en
GitHub Pages con cada push a `main`. La página queda en:

**<https://andonizubimendi.github.io/mapa-inka/>**

Si hay que reactivarlo: **Settings → Pages → Build and deployment → Source: GitHub Actions**,
y luego **Actions → Publicar en GitHub Pages → Run workflow**.

## Estructura

```
index.html                     Página del mapa
styles.css                     Estilos, modo oscuro/claro y diseño adaptativo
app.js                         Carga del GeoJSON y lógica del mapa
localidades.geojson            Localidades y oyentes generados desde el chat
scripts/generar_localidades.py Generador del GeoJSON a partir del chat
scripts/diccionario_lugares.json Frases ya aprendidas para acelerar corridas
scripts/revision.json          Correcciones manuales del proceso
scripts/README.md              Uso y formato del generador
.github/workflows/deploy.yml   Publicación automática en GitHub Pages
```

## Créditos

- [Leaflet](https://leafletjs.com/) y
  [Leaflet.markercluster](https://github.com/Leaflet/Leaflet.markercluster).
- Mapa base de [OpenStreetMap](https://www.openstreetmap.org/copyright), con un filtro CSS para
  el modo oscuro.
- Imágenes satelitales de [Esri](https://www.esri.com/).
- Localidades y provincias de [Georef](https://www.datos.gob.ar/) (datos abiertos de
  Argentina).
- Geocodificación de lugares fuera de Argentina con [Nominatim](https://nominatim.org/).
- Tipografía [Inter](https://rsms.me/inter/).
- Chat descargado con [yt-dlp](https://github.com/yt-dlp/yt-dlp).

## Nota sobre privacidad

El mapa publica nombres de usuario y comentarios que ya eran públicos en el chat de YouTube.
Si se quiere quitar a alguien o moderar un mensaje, se puede agregar el usuario a
`scripts/revision.json` o editar el GeoJSON antes de publicarlo.
