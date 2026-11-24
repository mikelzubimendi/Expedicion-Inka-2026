# Generador de localidades

Este directorio contiene el proceso manual que arma `localidades.geojson` a partir de los
comentarios del chat de los 4 videos del streaming de YouTube (Día 1 a Día 4).

No se ejecuta automáticamente ni en cada deploy: se corre a demanda cuando hay comentarios
nuevos o cuando se quiere regenerar el mapa.

## Requisitos

- Python 3.10 o superior.
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) para descargar el chat (solo si no se pasa un
  archivo ya descargado).
- Conexión a internet la primera vez, para bajar el chat, las localidades de Georef y las
  geocodificaciones de Nominatim. Después se reutilizan la caché de `scripts/.cache/` y el
  diccionario de lugares.

## Uso rápido

Desde la raíz del repositorio:

```bash
# 1. Descargar los chats y generar solo los reportes de revisión
python3 scripts/generar_localidades.py --solo-reporte

# 2. Revisar los CSV (opcional) y corregir scripts/revision.json
# 3. Generar el GeoJSON definitivo
python3 scripts/generar_localidades.py
```

Por defecto se procesan los 4 videos del streaming definidos en `VIDEOS` (Día 1 a Día 4) y
se combinan todos los comentarios. El resultado se escribe en `localidades.geojson`, que es el
archivo que consume el mapa.

Para procesar un solo video o volver a descargar los chats:

```bash
python3 scripts/generar_localidades.py --video "https://www.youtube.com/watch?v=..."
python3 scripts/generar_localidades.py --actualizar-chat
```

## Opciones

```text
--video URL           Procesar un solo video (por defecto, los 4 del streaming)
--chat ARCHIVO        Usar un chat JSONL ya descargado
--salida ARCHIVO      GeoJSON de salida (por defecto: localidades.geojson)
--reporte ARCHIVO     CSV con todos los usuarios detectados (scripts/reporte.csv)
--no-detectados CSV   CSV con frases que no se pudieron resolver (scripts/no_detectados.csv)
--revision ARCHIVO    Correcciones manuales (scripts/revision.json)
--diccionario ARCHIVO Diccionario de frases aprendidas (scripts/diccionario_lugares.json)
--solo-reporte        No escribe el GeoJSON; solo genera los reportes
--sin-aprender        No guarda frases nuevas en el diccionario
--actualizar-diccionario  Sobrescribe las frases ya aprendidas
--actualizar-chat     Vuelve a descargar el chat
--actualizar-datos    Vuelve a descargar localidades y provincias de Georef
--pausa SEGUNDOS      Pausa entre consultas a Nominatim (por defecto 1.1)
--max-consultas N     Máximo de consultas nuevas a Nominatim (por defecto 400)
--verbose             Muestra más información por consola
```

## Cómo detecta las localidades

1. Baja el chat de cada video con `yt-dlp` (`live_chat`) y los lee línea por línea,
   conservando el día al que pertenece cada mensaje.
2. Agrupa los mensajes de todos los videos por usuario.
3. Busca frases con pistas de ubicación: “desde…”, “soy de…”, “estoy en…”, “saludo desde…”,
   “X presente”, “aguante X”, o mensajes cortos que son solo el nombre del lugar.
4. Resuelve el lugar con:
   - el listado oficial de localidades y provincias de [Georef](https://www.datos.gob.ar/),
     que incluye barrios de CABA y localidades de todo el país;
   - alias para escrituras habituales (“Mar Plata”, “Mardel”, “MDQ”, “Sgo Estero”, “Bs As”,
     “Caba”, “Bariloche”, etc.);
   - [Nominatim](https://nominatim.org/) para ciudades y países de fuera de Argentina y para
     barrios o lugares que no están en Georef.
5. Si un usuario escribió varias veces, elige la ubicación con mayor confianza y guarda
   todos sus otros comentarios como metadata.

Los resultados dudosos quedan en `scripts/reporte.csv` con una columna de confianza, y los
usuarios que quedaron sin ubicación en `scripts/no_detectados.csv`.

### Progreso

El script muestra el avance mientras corre:

```text
Buscando coincidencias con datos locales…
Progreso: 500/2226 usuarios (22%) · 410 ubicados · 90 sin ubicación · 12 consultas nuevas
Nominatim: 15 consultas nuevas…
```

La primera corrida puede tardar unos minutos si hay muchas frases nuevas. Las siguientes son
mucho más rápidas porque se reutilizan la caché y el diccionario.

## Diccionario de lugares

`scripts/diccionario_lugares.json` guarda las frases ya resueltas para no volver a buscarlas:

```json
{
  "version": 1,
  "lugares": {
    "chacarita": {
      "Lugar": "Chacarita",
      "Provincia": "Catamarca",
      "Pais": "Argentina",
      "lat": -26.70225,
      "lon": -66.04419,
      "Tipo": "localidad"
    }
  }
}
```

- Se completa automáticamente con las coincidencias de confianza alta o media.
- Si una frase ya existe, no se pisa en las corridas siguientes (para conservar correcciones
  manuales). Con `--actualizar-diccionario` se reemplaza por el resultado nuevo.
- El diccionario se consulta antes de salir a Nominatim; por eso los comentarios repetidos son
  instantáneos.
- Si una frase aparece en contextos de provincias distintas, el diccionario no se usa cuando
  la provincia no coincide y se resuelve por la vía normal.

## Correcciones manuales

`scripts/revision.json` permite ajustar el resultado automático:

```json
{
  "excluir_usuarios": ["@usuario_a_ignorar"],
  "excluir_lugares": ["Argentina"],
  "corregir": {
    "@un_usuario": {
      "Lugar": "La Chacarita",
      "Provincia": "Catamarca",
      "Pais": "Argentina",
      "lat": -28.4599,
      "lon": -65.7524
    }
  },
  "incluir": {
    "@otro_usuario": {
      "Lugar": "Córdoba",
      "Provincia": "Córdoba",
      "Pais": "Argentina",
      "lat": -31.415,
      "lon": -64.1791
    }
  }
}
```

- `excluir_usuarios`: no incluye a ese usuario en el mapa.
- `excluir_lugares`: descarta un lugar completo (por ejemplo, falsos positivos).
- `corregir`: reemplaza la ubicación detectada para un usuario.
- `incluir`: agrega un usuario que el detector no encontró.

Si se omite `lat`/`lon`, se intenta geocodificar el `Lugar` con el contexto de la provincia.

## Formato del GeoJSON

Cada feature es una localidad. Los oyentes y sus comentarios van anidados:

```json
{
  "type": "Feature",
  "properties": {
    "Lugar": "Córdoba",
    "Provincia": "Córdoba",
    "Pais": "Argentina",
    "Tipo": "localidad",
    "Cantidad": 2,
    "Oyentes": [
      {
        "Usuario": "@ejemplo",
        "Mensaje": "Saludos desde Córdoba",
        "Dia": "Día 1",
        "Comentarios": ["Qué lindo el vivo", "Aguante la ciencia pública"],
        "Dias": ["Día 1", "Día 3"],
        "ComentariosPorDia": {
          "Día 1": ["Saludos desde Córdoba", "Qué lindo el vivo"],
          "Día 3": ["Volví a ver el stream"]
        }
      }
    ]
  },
  "geometry": {
    "type": "Point",
    "coordinates": [-64.1791, -31.415]
  }
}
```

Las coordenadas siempre van en orden **longitud, latitud**.

## Caché y privacidad

- `scripts/.cache/` guarda el chat, los datos de Georef y las respuestas de Nominatim. Está
  ignorado por git.
- `scripts/diccionario_lugares.json` sí se versiona: es el aprendizaje acumulado entre
  corridas.
- El GeoJSON publicado incluye nombres de usuario y comentarios públicos del chat. Si se
  quiere moderar algún mensaje, se puede excluir al usuario o editar el GeoJSON antes de
  publicarlo.
