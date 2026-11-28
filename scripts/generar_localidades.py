#!/usr/bin/env python3
"""
Genera localidades.geojson a partir de los comentarios del chat de un vivo de YouTube.

El proceso es manual y a demanda:

    python3 scripts/generar_localidades.py

Descarga (si hace falta) el chat del vivo con yt-dlp, detecta las localidades
mencionadas, las geocodifica y escribe el GeoJSON que consume el mapa.

Para revisar antes de publicar:

    python3 scripts/generar_localidades.py --solo-reporte

Los casos dudosos se pueden corregir en scripts/revision.json.

Dependencias:
  - Python 3.10+
  - yt-dlp (solo si se descarga el chat automáticamente)
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

VIDEOS = [
    ("https://www.youtube.com/live/CtAJIkQDiyQ", "CtAJIkQDiyQ", "EXPEDICIÓN INKA - Día 1"),
    ("https://www.youtube.com/watch?v=vhFyl24JLlw", "vhFyl24JLlw", "EXPEDICIÓN INKA - Día 2"),
    ("https://www.youtube.com/watch?v=g3Blu5r05eQ", "g3Blu5r05eQ", "EXPEDICIÓN INKA - Día 3"),
    ("https://www.youtube.com/watch?v=0ivWpycYBuM", "0ivWpycYBuM", "EXPEDICIÓN INKA - Día 4 (último día)"),
]
VIDEO_URL = VIDEOS[0][0]
VIDEO_ID = VIDEOS[0][1]


def day_label(title: str) -> str:
    """Devuelve una etiqueta corta, por ejemplo «Día 2», desde el título."""
    match = re.search(r"D[ií]a\s*\d+", title, flags=re.I)
    return match.group(0).capitalize() if match else title


def day_sort_key(label: str) -> tuple[int, str]:
    match = re.search(r"(\d+)", label or "")
    return (int(match.group(1)) if match else 99, label or "")


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
CACHE = SCRIPTS / ".cache"
DEFAULT_OUTPUT = ROOT / "localidades.geojson"
DEFAULT_REPORT = SCRIPTS / "reporte.csv"
DEFAULT_UNRESOLVED = SCRIPTS / "no_detectados.csv"
DEFAULT_REVISION = SCRIPTS / "revision.json"
DEFAULT_DICTIONARY = SCRIPTS / "diccionario_lugares.json"

GEOREF_LOCALIDADES = "https://apis.datos.gob.ar/georef/api/localidades?max=5000"
GEOREF_PROVINCIAS = "https://apis.datos.gob.ar/georef/api/provincias"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "MapaInka/1.0 (https://github.com/AndoniZubimendi/mapa-inka)"

# ---------------------------------------------------------------------------
# Normalización y limpieza
# ---------------------------------------------------------------------------

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF\uFE0F\u200D]+"
)
SHORTCODE_RE = re.compile(r":[a-zA-Z0-9_+\-]+:")
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
HANDLE_RE = re.compile(r"(?<!\w)@[\w.\-]+")


def strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def norm(text: str) -> str:
    text = strip_accents(str(text)).lower()
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    text = SHORTCODE_RE.sub(" ", text)
    text = EMOJI_RE.sub(" ", text)
    text = URL_RE.sub(" ", text)
    text = HANDLE_RE.sub(" ", text)
    text = re.sub(r"[^a-z0-9ñ\s.,;:!?()/\-]", " ", text)
    text = re.sub(r"[.,;:()/]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,;:-")


def clean_text(text: str) -> str:
    """Texto legible para guardar en el GeoJSON."""
    text = SHORTCODE_RE.sub("", text)
    text = EMOJI_RE.sub("", text)
    text = URL_RE.sub("", text)
    text = HANDLE_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,;:-")


def cut_phrase(text: str) -> str:
    text = re.split(r"[\n\r]|(?:\s[-–—]\s)|[;!?|]", text)[0]
    text = text.split(",")[0]
    text = re.sub(r"\([^)]*\)", " ", text)
    return re.sub(r"\s+", " ", text).strip(" ,.;:-\"'")


# ---------------------------------------------------------------------------
# Datos de referencia: provincias, países y alias
# ---------------------------------------------------------------------------

PROVINCES = {
    "caba": "Ciudad Autónoma de Buenos Aires",
    "capital federal": "Ciudad Autónoma de Buenos Aires",
    "ciudad autonoma de buenos aires": "Ciudad Autónoma de Buenos Aires",
    "buenos aires": "Buenos Aires",
    "bs as": "Buenos Aires",
    "bsas": "Buenos Aires",
    "bs.as": "Buenos Aires",
    "baires": "Buenos Aires",
    "pcia de buenos aires": "Buenos Aires",
    "provincia de buenos aires": "Buenos Aires",
    "catamarca": "Catamarca",
    "chaco": "Chaco",
    "chubut": "Chubut",
    "cordoba": "Córdoba",
    "cba": "Córdoba",
    "corrientes": "Corrientes",
    "entre rios": "Entre Ríos",
    "formosa": "Formosa",
    "jujuy": "Jujuy",
    "la pampa": "La Pampa",
    "la rioja": "La Rioja",
    "mendoza": "Mendoza",
    "mza": "Mendoza",
    "misiones": "Misiones",
    "neuquen": "Neuquén",
    "rio negro": "Río Negro",
    "salta": "Salta",
    "san juan": "San Juan",
    "san luis": "San Luis",
    "santa cruz": "Santa Cruz",
    "santa fe": "Santa Fe",
    "sfe": "Santa Fe",
    "santiago del estero": "Santiago del Estero",
    "sgo del estero": "Santiago del Estero",
    "sde": "Santiago del Estero",
    "tierra del fuego": "Tierra del Fuego, Antártida e Islas del Atlántico Sur",
    "tucuman": "Tucumán",
    "tuc": "Tucumán",
}

PROVINCE_KEYS = sorted(PROVINCES, key=len, reverse=True)

# Provincias que no tienen una ciudad homónima: si alguien dice solo el nombre,
# se marca la provincia (no una localidad homónima de otra provincia).
PROVINCE_ONLY = {
    "chubut", "santa cruz", "misiones", "la pampa", "rio negro",
    "entre rios", "tierra del fuego",
}

COUNTRIES = {
    "argentina", "chile", "uruguay", "brasil", "paraguay", "bolivia", "peru",
    "venezuela", "colombia", "ecuador", "mexico", "costa rica", "panama",
    "cuba", "republica dominicana", "guatemala", "honduras", "nicaragua",
    "el salvador", "españa", "italia", "portugal", "francia", "alemania",
    "reino unido", "inglaterra", "irlanda", "paises bajos", "belgica",
    "suiza", "austria", "grecia", "polonia", "suecia", "noruega",
    "dinamarca", "finlandia", "rusia", "ucrania", "turquia", "israel",
    "estados unidos", "eeuu", "ee.uu.", "canada", "australia",
    "nueva zelanda", "japon", "china", "india", "vietnam", "birmania",
    "tailandia", "filipinas", "sudafrica", "egipto", "marruecos", "argelia",
    "tunez", "senegal", "nigeria", "kenia", "etiopia", "ghana", "bulgaria",
    "rumania", "hungria", "republica checa", "eslovaquia", "eslovenia",
    "croacia", "serbia", "bosnia", "albania", "letonia", "lituania",
    "estonia", "islandia", "luxemburgo", "malta", "chipre",
}

COUNTRY_ALIASES = {
    "ee uu": "estados unidos",
    "ee.uu": "estados unidos",
    "eua": "estados unidos",
    "uk": "reino unido",
    "inglaterra": "reino unido",
}

# Centroides aproximados para resolver países sin consultar Nominatim.
COUNTRY_POINTS = {
    "chile": (-35.6751, -71.5430),
    "uruguay": (-32.5228, -55.7658),
    "brasil": (-14.2350, -51.9253),
    "paraguay": (-23.4425, -58.4438),
    "bolivia": (-16.2902, -63.5887),
    "peru": (-9.1900, -75.0152),
    "venezuela": (6.4238, -66.5897),
    "colombia": (4.5709, -74.2973),
    "ecuador": (-1.8312, -78.1834),
    "mexico": (23.6345, -102.5528),
    "costa rica": (9.7489, -83.7534),
    "espana": (40.4637, -3.7492),
    "italia": (41.8719, 12.5674),
    "portugal": (39.3999, -8.2245),
    "francia": (46.2276, 2.2137),
    "alemania": (51.1657, 10.4515),
    "reino unido": (55.3781, -3.4360),
    "irlanda": (53.1424, -7.6921),
    "paises bajos": (52.1326, 5.2913),
    "belgica": (50.5039, 4.4699),
    "suiza": (46.8182, 8.2275),
    "austria": (47.5162, 14.5501),
    "grecia": (39.0742, 21.8243),
    "polonia": (51.9194, 19.1451),
    "suecia": (60.1282, 18.6435),
    "noruega": (60.4720, 8.4689),
    "dinamarca": (56.2639, 9.5018),
    "finlandia": (61.9241, 25.7482),
    "rusia": (61.5240, 105.3188),
    "ucrania": (48.3794, 31.1656),
    "turquia": (38.9637, 35.2433),
    "israel": (31.0461, 34.8516),
    "estados unidos": (37.0902, -95.7129),
    "canada": (56.1304, -106.3468),
    "australia": (-25.2744, 133.7751),
    "nueva zelanda": (-40.9006, 174.8860),
    "japon": (36.2048, 138.2529),
    "china": (35.8617, 104.1954),
    "india": (20.5937, 78.9629),
    "vietnam": (14.0583, 108.2772),
    "birmania": (21.9162, 95.9560),
    "tailandia": (15.8700, 100.9925),
    "filipinas": (12.8797, 121.7740),
    "sudafrica": (-30.5595, 22.9375),
    "egipto": (26.8206, 30.8025),
    "marruecos": (31.7917, -7.0926),
    "argelia": (28.0339, 1.6596),
    "tunez": (33.8869, 9.5375),
    "senegal": (14.4974, -14.4524),
    "nigeria": (9.0820, 8.6753),
    "kenia": (-0.0236, 37.9062),
    "etiopia": (9.1450, 40.4897),
    "ghana": (7.9465, -1.0232),
    "bulgaria": (42.7339, 25.4858),
    "rumania": (45.9432, 24.9668),
    "hungria": (47.1625, 19.5033),
    "republica checa": (49.8175, 15.4730),
    "eslovaquia": (48.6690, 19.6990),
    "eslovenia": (46.1512, 14.9955),
    "croacia": (45.1000, 15.2000),
    "serbia": (44.0165, 21.0059),
    "bosnia": (44.2000, 17.8000),
    "albania": (41.1533, 20.1683),
    "letonia": (56.8796, 24.6032),
    "lituania": (55.1694, 23.8813),
    "estonia": (58.5953, 25.0136),
    "islandia": (64.9631, -19.0208),
    "luxemburgo": (49.8153, 6.1296),
    "malta": (35.9375, 14.3754),
    "chipre": (35.1264, 33.4299),
}

# Localidades que no siempre están en el listado de Georef o que necesitan una
# coordenada de ciudad y no de provincia.
EXTRA_PLACES = {
    "san martin": ("San Martín", "Buenos Aires", "Argentina", -34.5770, -58.5370),
    "gregorio de laferrere": ("Gregorio de Laferrere", "Buenos Aires", "Argentina", -34.7500, -58.5850),
    "balsa las perlas": ("Las Perlas", "Río Negro", "Argentina", -38.9869, -68.1389),
    "lavalle mendoza": ("Lavalle", "Mendoza", "Argentina", -32.7190, -68.5900),
    "la boca": ("La Boca", "Ciudad Autónoma de Buenos Aires", "Argentina", -34.6345, -58.3633),
    "del shincal": ("El Shincal", "Catamarca", "Argentina", -27.6847, -67.1769),
    "shincal": ("El Shincal", "Catamarca", "Argentina", -27.6847, -67.1769),
    "el shincal": ("El Shincal", "Catamarca", "Argentina", -27.6847, -67.1769),
    "fiorito": ("Fiorito", "Buenos Aires", "Argentina", -34.7000, -58.3167),
    "valle viejo": ("Valle Viejo", "Catamarca", "Argentina", -28.4667, -65.7167),
}

# Ciudades y regiones del exterior que aparecen en el chat y que no están en
# Georef. Se resuelven sin consultar Nominatim.
FOREIGN_PLACES = {
    "madrid": ("Madrid", "Comunidad de Madrid", "España", 40.4168, -3.7038),
    "barcelona": ("Barcelona", "Cataluña", "España", 41.3826, 2.1771),
    "londres inglaterra": ("Londres", "Inglaterra", "Reino Unido", 51.5074, -0.1278),
    "paris": ("París", "Isla de Francia", "Francia", 48.8566, 2.3522),
    "roma": ("Roma", "Lacio", "Italia", 41.9028, 12.4964),
    "montevideo": ("Montevideo", "Montevideo", "Uruguay", -34.9011, -56.1645),
    "santiago de chile": ("Santiago", "Región Metropolitana", "Chile", -33.4489, -70.6693),
    "lima": ("Lima", "Lima", "Perú", -12.0464, -77.0428),
    "sao paulo": ("São Paulo", "São Paulo", "Brasil", -23.5505, -46.6333),
    "rio de janeiro": ("Río de Janeiro", "Río de Janeiro", "Brasil", -22.9068, -43.1729),
    "porto alegre": ("Porto Alegre", "Río Grande del Sur", "Brasil", -30.0368, -51.2090),
    "pais vasco": ("País Vasco", None, "España", 42.9912, -2.5543),
    "cerdena": ("Cerdeña", None, "Italia", 40.0913, 9.0306),
    "sardegna": ("Cerdeña", None, "Italia", 40.0913, 9.0306),
    "san pedro de atacama": ("San Pedro de Atacama", "Antofagasta", "Chile", -22.9090, -68.1990),
    "cusco": ("Cusco", "Cusco", "Perú", -13.5319, -71.9675),
    "cuzco": ("Cusco", "Cusco", "Perú", -13.5319, -71.9675),
    "el cusco": ("Cusco", "Cusco", "Perú", -13.5319, -71.9675),
}

# Alias de localidades que aparecen escritas de forma coloquial o abreviada.
PLACE_ALIASES = {
    "mar plata": "Mar del Plata",
    "mar de plata": "Mar del Plata",
    "mardel": "Mar del Plata",
    "mardell": "Mar del Plata",
    "mdq": "Mar del Plata",
    "sta fe": "Santa Fe",
    "santa fe capital": "Santa Fe",
    "sgo estero": "Santiago del Estero",
    "sgo del estero": "Santiago del Estero",
    "sgo. del estero": "Santiago del Estero",
    "santiago estero": "Santiago del Estero",
    "santiago del estero": "Santiago del Estero",
    "santuago estero": "Santiago del Estero",
    "jujuy": "San Salvador de Jujuy",
    "sierras de cordoba": "Córdoba",
    "las sierras de cordoba": "Córdoba",
    "laferrere": "Gregorio de Laferrere",
    "gregorio de laferrere": "Gregorio de Laferrere",
    "gral villegas": "General Villegas",
    "general villegas": "General Villegas",
    "patagones": "Carmen de Patagones",
    "alfar": "Mar del Plata",
    "republica de la boca": "La Boca",
    "la republica de la boca": "La Boca",
    "sta rosa de calamuchita": "Santa Rosa de Calamuchita",
    "santa rosa de calamuchita": "Santa Rosa de Calamuchita",
    "catamraca": "San Fernando del Valle de Catamarca",
    "lp": "La Plata",
    "caba": "Ciudad Autónoma de Buenos Aires",
    "capital federal": "Ciudad Autónoma de Buenos Aires",
    "baires": "Ciudad Autónoma de Buenos Aires",
    "bs as": "Ciudad Autónoma de Buenos Aires",
    "bsas": "Ciudad Autónoma de Buenos Aires",
    "bs.as": "Ciudad Autónoma de Buenos Aires",
    "bariloche": "San Carlos de Bariloche",
    "catamarca": "San Fernando del Valle de Catamarca",
    "catamarca capital": "San Fernando del Valle de Catamarca",
    "tucuman": "San Miguel de Tucumán",
    "tucuman capital": "San Miguel de Tucumán",
    "la plata": "La Plata",
    "laplata": "La Plata",
    "lomas zamora": "Lomas de Zamora",
    "lomas de zamora": "Lomas de Zamora",
    "florencio varela": "Florencio Varela",
    "fcio varela": "Florencio Varela",
    "jose c paz": "José C. Paz",
    "jose cpaz": "José C. Paz",
    "gral guemes": "General Güemes",
    "general guemes": "General Güemes",
    "sta rosa": "Santa Rosa",
    "sta rosa calamuchita": "Santa Rosa de Calamuchita",
    "santa rosa calamuchita": "Santa Rosa de Calamuchita",
    "rio cuarto": "Río Cuarto",
    "rio grande": "Río Grande",
    "tierra fuego": "Tierra del Fuego, Antártida e Islas del Atlántico Sur",
    "corcoba": "Córdoba",
    "santiago de estero": "Santiago del Estero",
    "misones": "Misiones",
}

# Nombres ambiguos: provincia a la que se los asocia por defecto.
PREFERRED_PROVINCE = {
    "santa maria": "Catamarca",
    "la falda": "Córdoba",
    "santa rosa": "La Pampa",
    "san martin": "Buenos Aires",
    "belgrano": "Ciudad Autónoma de Buenos Aires",
    "chacarita": "Ciudad Autónoma de Buenos Aires",
    "villa urquiza": "Ciudad Autónoma de Buenos Aires",
    "villa devoto": "Ciudad Autónoma de Buenos Aires",
    "flores": "Ciudad Autónoma de Buenos Aires",
    "palermo": "Ciudad Autónoma de Buenos Aires",
    "recoleta": "Ciudad Autónoma de Buenos Aires",
    "caballito": "Ciudad Autónoma de Buenos Aires",
    "almagro": "Ciudad Autónoma de Buenos Aires",
    "boedo": "Ciudad Autónoma de Buenos Aires",
    "colegiales": "Ciudad Autónoma de Buenos Aires",
    "liniers": "Ciudad Autónoma de Buenos Aires",
    "mataderos": "Ciudad Autónoma de Buenos Aires",
    "nunez": "Ciudad Autónoma de Buenos Aires",
    "saavedra": "Ciudad Autónoma de Buenos Aires",
    "retiro": "Ciudad Autónoma de Buenos Aires",
}

# Nombres que también son palabras comunes o nombres de personas: solo se
# aceptan si vienen acompañados por una pista clara ("desde", "soy de", etc.).
COMMON_WORD_PLACES = {
    "argentina", "paula", "azara", "profundidad", "los arboles", "la falda",
    "santa cruz", "la pampa", "belgrano", "flores", "palermo", "retiro",
    "colegiales", "boedo", "nunez", "saavedra", "chacarita", "villa urquiza",
}

# Frases que no son lugares aunque contengan nombres de localidades.
GENERIC_PHRASES = {
    "la ciencia", "la universidad", "la universidad publica", "la educacion publica",
    "la arqueologia", "la patagonia", "el sur", "el conicet", "conicet",
    "la oficina", "el laboratorio", "el museo", "la escuela", "la secundaria",
    "el colegio", "el instituto", "el centro", "la banda", "la familia",
    "el equipo", "el proyecto", "el programa", "la facultad", "la catedra",
    "la carrera", "el ministerio", "la direccion", "la fundacion", "el area",
    "la red", "el grupo", "la municipalidad", "la universidad nacional",
    # Nombres comunes que también existen como localidades y generan falsos
    # positivos al geocodificarse ("aguante el metal" -> El Metal, Asturias).
    "el metal", "la chamba", "coca cola", "la ciudad", "la republica",
}

CONFIDENCE_ORDER = {"alta": 0, "media": 1, "baja": 2}


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------


@dataclass
class Message:
    usuario: str
    texto: str
    timestamp: int
    dia: str = ""


@dataclass
class Place:
    nombre: str
    provincia: str | None
    pais: str
    lat: float
    lon: float
    tipo: str = "localidad"
    confianza: str = "alta"
    fuente: str = ""
    detalle: str = ""


@dataclass
class Match:
    place: Place
    mensaje: Message
    frase: str
    regla: str
    confianza: str


def place_to_dict(place: Place) -> dict:
    return {
        "Lugar": place.nombre,
        "Provincia": place.provincia or "",
        "Pais": place.pais or "",
        "lat": round(place.lat, 5),
        "lon": round(place.lon, 5),
        "Tipo": place.tipo,
    }


def place_from_dict(data: dict) -> Place | None:
    try:
        return Place(
            str(data["Lugar"]),
            data.get("Provincia") or None,
            data.get("Pais") or None,
            float(data["lat"]),
            float(data["lon"]),
            data.get("Tipo") or "localidad",
            "alta",
            "diccionario",
        )
    except (KeyError, TypeError, ValueError):
        return None


def load_dictionary(path: Path) -> dict[str, Place]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"El diccionario {path} no es JSON válido: {exc}")
    entries = raw.get("lugares", raw) if isinstance(raw, dict) else {}
    result: dict[str, Place] = {}
    for key, value in entries.items():
        place = place_from_dict(value)
        if place:
            result[norm(key)] = place
    return result


def save_dictionary(path: Path, dictionary: dict[str, Place]) -> None:
    payload = {
        "version": 1,
        "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "lugares": {key: place_to_dict(place) for key, place in sorted(dictionary.items())},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def replace_place(place: Place, **changes: Any) -> Place:
    data = {
        "nombre": place.nombre,
        "provincia": place.provincia,
        "pais": place.pais,
        "lat": place.lat,
        "lon": place.lon,
        "tipo": place.tipo,
        "confianza": place.confianza,
        "fuente": place.fuente,
        "detalle": place.detalle,
    }
    data.update(changes)
    return Place(**data)


# ---------------------------------------------------------------------------
# Chat de YouTube
# ---------------------------------------------------------------------------


def download_chat(video_url: str, video_id: str, force: bool = False) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / f"chat.{video_id}.live_chat.json"
    if target.exists() and not force:
        return target

    print(f"Descargando el chat de {video_id} con yt-dlp…", file=sys.stderr)
    cmd = [
        "yt-dlp", "--no-warnings", "--skip-download",
        "--write-subs", "--sub-langs", "live_chat", "--sub-format", "json",
        "-o", str(CACHE / f"chat.{video_id}.%(ext)s"), video_url,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        sys.exit("No encontré yt-dlp. Instalalo o pasá el chat con --chat.")
    except subprocess.CalledProcessError as exc:
        sys.exit(f"yt-dlp falló con código {exc.returncode} para {video_id}.")

    candidates = sorted(CACHE.glob(f"chat.{video_id}*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        sys.exit("yt-dlp no generó el archivo del chat para " + video_id + ".")
    if candidates[0] != target:
        candidates[0].replace(target)
    return target


def parse_chat(path: Path, dia: str = "") -> list[Message]:
    messages: list[Message] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            actions = payload.get("replayChatItemAction", {}).get("actions", [])
            for action in actions:
                item = action.get("addChatItemAction", {}).get("item", {})
                renderer = item.get("liveChatTextMessageRenderer")
                if not renderer:
                    continue
                author = (renderer.get("authorName", {}).get("simpleText") or "").strip()
                runs = renderer.get("message", {}).get("runs", [])
                parts = []
                for run in runs:
                    if "text" in run:
                        parts.append(run["text"])
                    elif "emoji" in run:
                        parts.append(run["emoji"].get("emojiId") or "")
                text = "".join(parts).strip()
                if not author or not text:
                    continue
                try:
                    timestamp = int(renderer.get("timestampUsec", "0")) // 1000
                except ValueError:
                    timestamp = 0
                messages.append(Message(author, text, timestamp, dia))

    messages.sort(key=lambda m: m.timestamp)
    return messages


def group_messages(messages: Iterable[Message]) -> dict[str, list[Message]]:
    grouped: dict[str, list[Message]] = defaultdict(list)
    for message in messages:
        grouped[message.usuario].append(message)
    return grouped


# ---------------------------------------------------------------------------
# Datos geográficos
# ---------------------------------------------------------------------------


def fetch_json(url: str, cache_path: Path, force: bool = False) -> Any:
    CACHE.mkdir(parents=True, exist_ok=True)
    if cache_path.exists() and not force:
        return json.loads(cache_path.read_text(encoding="utf-8"))

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.load(response)
    except Exception as exc:
        if cache_path.exists():
            print(f"Aviso: no se pudo actualizar {cache_path.name} ({exc}). Uso la copia local.", file=sys.stderr)
            return json.loads(cache_path.read_text(encoding="utf-8"))
        raise

    cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def load_reference_data(force: bool = False) -> tuple[list[dict], list[dict]]:
    localidades = fetch_json(GEOREF_LOCALIDADES, CACHE / "localidades_ar.json", force)
    provincias = fetch_json(GEOREF_PROVINCIAS, CACHE / "provincias_ar.json", force)
    return localidades.get("localidades", []), provincias.get("provincias", [])


class Gazetteer:
    def __init__(self, localidades: list[dict], provincias: list[dict]):
        self.by_name: dict[str, list[Place]] = defaultdict(list)
        self.by_first: dict[str, list[tuple[str, Place]]] = defaultdict(list)
        self.provinces: dict[str, Place] = {}
        self._seen: set[tuple] = set()

        for row in localidades:
            coords = row.get("centroide") or {}
            lat, lon = coords.get("lat"), coords.get("lon")
            name = (row.get("nombre") or "").strip()
            province = ((row.get("provincia") or {}).get("nombre") or "").strip()
            if not name or lat is None or lon is None:
                continue
            key = (norm(name), norm(province), round(float(lat), 4), round(float(lon), 4))
            if key in self._seen:
                continue
            self._seen.add(key)
            place = Place(name, province or None, "Argentina", float(lat), float(lon),
                          "localidad", "alta", "Georef")
            self.by_name[norm(name)].append(place)

        # Ordenar candidatos: preferir entidades/localidades simples sobre
        # componentes, y luego por nombre.
        for name, places in self.by_name.items():
            places.sort(key=lambda p: (p.nombre != p.nombre.title(), p.nombre))
            first = name.split()[0]
            self.by_first[first].append((name, places[0]))
            for place in places[1:]:
                self.by_first[first].append((name, place))
        for first in self.by_first:
            self.by_first[first].sort(key=lambda item: len(item[0]), reverse=True)

        for row in provincias:
            name = (row.get("nombre") or "").strip()
            coords = row.get("centroide") or {}
            lat, lon = coords.get("lat"), coords.get("lon")
            if not name or lat is None or lon is None:
                continue
            # El centroide de Tierra del Fuego incluye la Antártida; usamos un
            # punto más representativo de la provincia.
            if name.startswith("Tierra del Fuego"):
                lat, lon = -54.0, -68.3
            tipo = "localidad" if name.startswith("Ciudad Autónoma de Buenos Aires") else "provincia"
            place = Place(name, name, "Argentina", float(lat), float(lon),
                          tipo, "alta", "Georef provincias")
            self.provinces[norm(name)] = place
            self.by_name[norm(name)].append(place)

    def names_for(self, phrase: str) -> list[tuple[str, Place]]:
        token = phrase.split()[0] if phrase.split() else ""
        return self.by_first.get(token, [])

    def exact_province(self, phrase: str) -> Place | None:
        text = norm(phrase)
        text = re.sub(r"\b(?:capital|argentina)\b", " ", text)
        text = re.sub(r"\b(?:provincia|pcia|prov)\s+de\s+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        for alias in PROVINCE_KEYS:
            if text == alias:
                name = PROVINCES[alias]
                if alias == "buenos aires":
                    return self.provinces.get("buenos aires")
                if norm(name) in self.provinces:
                    return self.provinces[norm(name)]
        return None

    def by_province(self, name: str, province: str) -> Place | None:
        options = [p for p in self.by_name.get(name, []) if p.provincia == province]
        return options[0] if options else None


# ---------------------------------------------------------------------------
# Geocodificación (Nominatim)
# ---------------------------------------------------------------------------


REJECT_CLASSES = {
    "amenity", "shop", "highway", "railway", "building", "waterway", "natural",
    "landuse", "leisure", "tourism", "man_made", "office", "emergency", "historic",
    "military", "power", "place_of_worship", "healthcare", "craft", "club",
    "boundary_relation", "water", "route", "aeroway", "barrier",
}

ALLOWED_PLACE_TYPES = {
    "city", "town", "village", "hamlet", "municipality", "administrative",
    "state", "province", "region", "country", "suburb", "neighbourhood",
    "quarter", "borough", "island", "archipelago", "locality",
}

GENERIC_TOKENS = {
    "conicet", "unlp", "uba", "unt", "unrc", "unlp", "universidad", "museo",
    "instituto", "colegio", "escuela", "secundaria", "laboratorio", "oficina",
    "fundacion", "proyecto", "programa", "equipo", "catedra", "ministerio",
    "direccion", "municipalidad", "centro", "area", "red", "grupo",
    "departamento", "facultad", "carrera", "conicet", "investigacion", "prensa",
    "osteoteca", "biblioteca", "cadic", "inapl", "unaj", "untref", "conae",
}


class Geocoder:
    def __init__(self, cache_path: Path, pause: float = 1.1, max_new_requests: int | None = None):
        self.cache_path = cache_path
        self.pause = pause
        self.max_new_requests = max_new_requests
        self.new_requests = 0
        self.cache: dict[str, Any] = {}
        if cache_path.exists():
            try:
                self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.cache = {}
        self.dirty = False
        self._requests = 0

    def save(self) -> None:
        if self.dirty:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")

    def _request(self, query: str, country_codes: str | None = None) -> Any:
        key = query + ("|" + country_codes if country_codes else "")
        if key in self.cache:
            return self.cache[key]
        if self.max_new_requests is not None and self.new_requests >= self.max_new_requests:
            return []

        params = {
            "q": query,
            "format": "jsonv2",
            "limit": 5,
            "addressdetails": 1,
            "accept-language": "es",
        }
        if country_codes:
            params["countrycodes"] = country_codes
        url = NOMINATIM + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                data = json.load(response)
        except Exception as exc:
            print(f"  Nominatim falló para “{query}”: {exc}", file=sys.stderr)
            data = []
        time.sleep(self.pause)
        self.cache[key] = data
        self.dirty = True
        self.new_requests += 1
        self._requests += 1
        if self._requests % 15 == 0:
            self.save()
            print(f"  Nominatim: {self.new_requests} consultas nuevas…", file=sys.stderr, flush=True)
        return data

    @staticmethod
    def _acceptable(item: dict) -> bool:
        cls = (item.get("class") or item.get("category") or "").lower()
        typ = (item.get("type") or "").lower()
        addr = (item.get("addresstype") or "").lower()
        if cls in REJECT_CLASSES:
            return False
        if cls not in {"place", "boundary"}:
            return False
        return typ in ALLOWED_PLACE_TYPES or addr in ALLOWED_PLACE_TYPES

    def lookup_country(self, country: str) -> Place:
        results = self._request(country)
        for item in results:
            if (item.get("type") or "").lower() == "country" or item.get("addresstype") == "country":
                return self._to_place(item, country)
        for item in results:
            if self._acceptable(item):
                place = self._to_place(item, country)
                place.tipo = "pais"
                return place
        # Si Nominatim no responde, devolvemos un punto aproximado en (0,0)
        # para no perder el dato; queda marcado para revisión.
        return Place(country.title(), None, country.title(), 0.0, 0.0, "pais", "baja", "sin geocodificar")

    def lookup(self, phrase: str, provincia: str | None, pais: str | None) -> Place | None:
        phrases = self._query_variants(phrase)
        if not phrases:
            return None

        # Sin país explícito asumimos Argentina: el público del stream es
        # mayoritariamente argentino y así evitamos homónimos remotos
        # ("el metal" -> El Metal, Asturias).
        default_cc = "ar" if pais in (None, "Argentina") else None
        queries: list[tuple[str, str | None]] = []
        for index, candidate in enumerate(phrases[:2]):
            if provincia and pais in (None, "Argentina"):
                queries.append((f"{candidate}, {provincia}, Argentina", "ar"))
            if index == 0 and pais:
                queries.append((f"{candidate}, {pais}", "ar" if pais == "Argentina" else None))
            queries.append((candidate, default_cc))

        seen_queries = set()
        for query, cc in queries:
            key = query + "|" + (cc or "")
            if key in seen_queries:
                continue
            seen_queries.add(key)
            results = self._request(query, cc)
            for item in results:
                if not self._acceptable(item):
                    continue
                return self._to_place(item, phrase)
        return None

    @staticmethod
    def _query_variants(phrase: str) -> list[str]:
        phrase = clean_text(phrase).strip(" ,.;:-")
        if not phrase:
            return []
        words = phrase.split()
        variants = []
        if len(words) > 4:
            variants.append(" ".join(words[:4]))
            variants.append(" ".join(words[:2]))
        else:
            variants.append(phrase)
        if len(words) > 1:
            variants.append(" ".join(words[:1]))
        out = []
        for variant in variants:
            if len(variant) < 3:
                continue
            if norm(variant) in out:
                continue
            out.append(variant)
        return out

    @staticmethod
    def _to_place(item: dict, phrase: str) -> Place:
        address = item.get("address") or {}
        country = address.get("country") or ""
        state = address.get("state") or address.get("province") or address.get("region") or ""
        city = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
            or address.get("hamlet")
            or address.get("suburb")
            or address.get("neighbourhood")
            or address.get("county")
        )
        typ = (item.get("type") or item.get("addresstype") or "").lower()
        addr = (item.get("addresstype") or "").lower()
        kind = addr if addr in ALLOWED_PLACE_TYPES else typ
        lat, lon = float(item["lat"]), float(item["lon"])

        if typ in {"country"} or addr == "country":
            name = country or phrase
            return Place(name, None, country or None, lat, lon, "pais", "media", "Nominatim")

        if kind in {"state", "province", "region"} or (typ == "administrative" and not city):
            name = state or phrase
            return Place(name, state or None, country or None, lat, lon,
                         "provincia" if typ in {"state", "province"} else "region",
                         "media", "Nominatim")

        if kind in {"suburb", "neighbourhood", "quarter", "borough"}:
            name = item.get("name") or address.get(kind) or phrase
            return Place(name, state or None, country or None, lat, lon,
                         "localidad", "baja", "Nominatim")

        if kind in {"locality", "hamlet", "isolated_dwelling"}:
            name = item.get("name") or phrase
            return Place(name, state or None, country or None, lat, lon,
                         "localidad", "media", "Nominatim")

        name = city or phrase
        return Place(name, state or None, country or None, lat, lon,
                     "localidad", "media", "Nominatim")


# ---------------------------------------------------------------------------
# Detección de lugares
# ---------------------------------------------------------------------------


CUE_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\bdesde\s+(.+)", re.I), "desde", "alta"),
    (re.compile(r"\b(?:soy|somos)\s+de\s+(.+)", re.I), "soy de", "alta"),
    (re.compile(r"\b(?:estoy|estamos|vivo|vivimos|resido|residimos)\s+en\s+(.+)", re.I), "estoy en", "alta"),
    (re.compile(r"\b(?:acá|aca|aquí|aqui)\s+(?:en|desde)\s+(.+)", re.I), "acá en", "alta"),
    (re.compile(r"\b(?:saludos?|abrazo)\b[^.!?\n]{0,40}?\bdesde\s+(.+)", re.I), "saludo", "alta"),
    (re.compile(r"^\s*(?:saludos?|abrazo)\s+de\s+(.+)", re.I), "saludo", "alta"),
    (re.compile(r"^\s*un\s+abrazo\s+de\s+(.+)", re.I), "saludo", "alta"),
    (re.compile(r"^\s*(.+?)\s+presente\b", re.I), "presente", "media"),
    (re.compile(r"^\s*(?:aguante|fuerza)\s+(.+)$", re.I), "aguante", "media"),
    (re.compile(r"^\s*presente\s+(.+)$", re.I), "presente", "media"),
]

SHORT_MESSAGE_WORDS = 9

# Palabras que no son lugares y que aparecen solas en mensajes cortos.
SHORT_STOPWORDS = {
    "hola", "holaa", "holaaa", "holaaaa", "holaaaaa", "holaaaaaa",
    "buenas", "buen", "buenos", "buen dia", "buenos dias", "buenas tardes",
    "buenas noches", "dia", "dias", "tardes", "noches",
    "gracias", "muchas", "mil", "felicitaciones", "felicidades", "exitos",
    "exito", "genio", "genios", "genia", "grandes", "grande", "crack",
    "excelente", "excelentes", "hermoso", "hermosa", "hermosos",
    "maravilloso", "maravillosa", "increible", "impresionante",
    "espectacular", "aplausos", "bravo", "vamos", "vamooo", "vamoooo",
    "vamoooooo", "dale", "daleee", "sii", "si", "no", "wow", "like",
    "chicos", "chicas", "equipo", "gente", "todos", "todas", "amigos",
    "cute", "guille", "guillermina", "mayra", "fede", "federico",
    "aylen", "flor", "florencia", "lau", "laura", "dario", "gabi",
    "gabriel", "gabriela", "paula", "valen", "vale", "meli", "sofia",
    "que", "emociom", "emocion", "emocionante", "lindo", "linda",
    "bueno", "buena", "muy", "mucho", "mucha", "muchos", "muchas",
    "interesante", "orgullo", "trabajo", "trabajos", "saludo", "saludos",
    "abrazo", "abrazos", "beso", "besos", "cariño", "cariños",
    "hasta", "manana", "mañana", "luego", "despues", "después",
    "presente", "aca", "aqui", "ahi", "ahí", "ahora", "ya", "viene",
    "vivo", "viva", "vivan", "aguante", "fuerza", "ciencia", "publica",
    "pública", "educacion", "educación", "universidad", "conicet",
    "arqueologia", "arqueología", "stream", "streaming", "video",
    "audio", "sonido", "pantalla", "senal", "señal", "corte", "corto",
}


def is_generic_short(normalized: str) -> bool:
    words = normalized.split()
    if not words:
        return True
    if normalized in GENERIC_PHRASES:
        return True
    if all(word in SHORT_STOPWORDS for word in words):
        return True
    content = [word for word in words if word not in {
        "el", "la", "los", "las", "un", "una", "de", "del", "en", "mi", "nuestra",
        "nuestro", "soy", "somos", "estoy", "estamos", "desde", "acá", "aca", "aquí",
    }]
    if content and content[0] in GENERIC_TOKENS:
        return True
    if len(words) <= 2 and re.search(r"[a-z0-9/+]{18,}", normalized):
        return True
    return False


def detect_province(text: str) -> str | None:
    normalized = norm(text)
    explicit = re.search(r"\b(?:provincia|pcia|prov)\s+de\s+([a-zñ ]+)", normalized)
    if explicit:
        candidate = explicit.group(1).strip()
        for alias in PROVINCE_KEYS:
            if candidate.startswith(alias):
                return PROVINCES[alias]
    for alias in PROVINCE_KEYS:
        if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", normalized):
            return PROVINCES[alias]
    return None


def detect_country(phrase: str) -> str | None:
    normalized = norm(phrase)
    normalized = COUNTRY_ALIASES.get(normalized, normalized)
    for country in sorted(COUNTRIES, key=len, reverse=True):
        if normalized == country or normalized.startswith(country + " "):
            return country
    return None


def detect_country_in_text(text: str) -> str | None:
    normalized = norm(text)
    for alias, country in sorted(COUNTRY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", normalized):
            return country
    for country in sorted(COUNTRIES, key=len, reverse=True):
        if re.search(r"(?<![a-z0-9])" + re.escape(country) + r"(?![a-z0-9])", normalized):
            return country
    return None


def message_candidates(message: Message) -> list[tuple[str, str, str]]:
    """Devuelve (frase, regla, confianza base) para un mensaje."""
    candidates: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    for pattern, rule, confidence in CUE_PATTERNS:
        for match in pattern.finditer(message.texto):
            phrase = cut_phrase(match.group(1))
            phrase = re.sub(r"^(?:acá|aca|aquí|aqui|yo|nosotros)\s+", "", phrase, flags=re.I)
            phrase = phrase.strip(" ,.;:-\"'")
            if len(phrase) < 2:
                continue
            key = norm(phrase)
            if key and key not in seen:
                seen.add(key)
                candidates.append((phrase, rule, confidence))

    normalized = norm(message.texto)
    words = normalized.split()
    if normalized and (len(words) <= SHORT_MESSAGE_WORDS or len(normalized) <= 55):
        if not is_generic_short(normalized):
            phrase = cut_phrase(message.texto)
            key = norm(phrase)
            if key and key not in seen:
                seen.add(key)
                candidates.append((phrase, "mensaje corto", "media"))

    return candidates


def _prefix_alias(phrase: str) -> tuple[str, str] | None:
    normalized = norm(phrase)
    for alias in sorted(PLACE_ALIASES, key=len, reverse=True):
        if normalized == alias or normalized.startswith(alias + " "):
            return alias, PLACE_ALIASES[alias]
    return None


def _anywhere_alias(phrase: str) -> tuple[str, str] | None:
    normalized = norm(phrase)
    for alias in sorted(PLACE_ALIASES, key=len, reverse=True):
        if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", normalized):
            return alias, PLACE_ALIASES[alias]
    return None


def _name_variants(phrase: str) -> list[str]:
    base = norm(phrase)
    variants = [base]
    no_article = re.sub(r"^(?:la|el|los|las)\s+", "", base)
    if no_article != base:
        variants.append(no_article)
    city = re.sub(r"^(?:la\s+)?(?:ciudad|localidad|municipio|barrio|villa)\s+(?:de\s+)?", "", base)
    if city and city not in variants:
        variants.append(city)
    collapsed = re.sub(r"(.)\1{2,}", r"\1", base)
    if collapsed not in variants:
        variants.append(collapsed)
    return variants


def _prefix_extra(phrase: str) -> tuple[str, str, str, float, float] | None:
    normalized = norm(phrase)
    for name in sorted(EXTRA_PLACES, key=len, reverse=True):
        if normalized == name or normalized.startswith(name + " "):
            return EXTRA_PLACES[name]
    return None


def _prefix_foreign(phrase: str) -> tuple[str, str, str, float, float] | None:
    normalized = norm(phrase)
    for name in sorted(FOREIGN_PLACES, key=len, reverse=True):
        if normalized == name or normalized.startswith(name + " "):
            return FOREIGN_PLACES[name]
    return None


class Resolver:

    def __init__(self, gazetteer: Gazetteer, geocoder: Geocoder,
                 dictionary: dict[str, Place] | None = None):
        self.gaz = gazetteer
        self.geocoder = geocoder
        self.dictionary = dictionary or {}
        self.learned: dict[str, Place] = {}

    def _learn(self, phrase: str, place: Place) -> None:
        normalized = norm(phrase)
        if not normalized or is_generic_short(normalized):
            return
        if len(normalized.split()) > 4:
            return
        if place.confianza == "baja" or place.tipo not in {"localidad", "pais", "provincia"}:
            return
        self.learned[normalized] = place

    def _dictionary_hit(self, phrase: str, context: str) -> Place | None:
        normalized = norm(phrase)
        place = self.dictionary.get(normalized)
        if not place:
            return None
        context_country = detect_country_in_text(context)
        if context_country and context_country != "argentina":
            if norm(place.pais or "") != context_country:
                return None
        hint = detect_province(phrase) or detect_province(context)
        if hint and place.provincia:
            if norm(place.provincia) == norm(hint):
                return place
            if hint == "Buenos Aires" and place.provincia == "Ciudad Autónoma de Buenos Aires":
                return place
            return None
        return place

    def resolve(self, phrase: str, context: str, rule: str,
                allow_nominatim: bool = True) -> tuple[Place | None, str]:
        phrase = clean_text(phrase).strip(" ,.;:-")
        if not phrase:
            return None, "frase vacía"

        normalized = norm(phrase)
        if normalized in GENERIC_PHRASES or is_generic_short(normalized):
            return None, "frase genérica"
        first_content = next((word for word in normalized.split()
                              if word not in {"el", "la", "los", "las", "de", "del", "en"}), "")
        if first_content in GENERIC_TOKENS:
            return None, "institución o lugar común"
        if re.search(r"\d{3,}", normalized):
            return None, "contiene números"

        context_country = detect_country_in_text(context)
        foreign_context = context_country is not None and context_country != "argentina"
        if foreign_context and allow_nominatim:
            place = self.geocoder.lookup(phrase, None, context_country.title())
            if place:
                self._learn(phrase, place)
                return place, "Nominatim país"

        dictionary_hit = self._dictionary_hit(phrase, context)
        if dictionary_hit:
            return replace_place(dictionary_hit, fuente="diccionario"), "diccionario"

        hint_for_extra = detect_province(phrase) or detect_province(context)
        extra = _prefix_extra(phrase) or EXTRA_PLACES.get(normalized)
        if extra and (not hint_for_extra or hint_for_extra == extra[1]):
            name, province, country, lat, lon = extra
            place = Place(name, province, country, lat, lon, "localidad", "alta", "lista local")
            self._learn(phrase, place)
            return place, "lista local"

        foreign = _prefix_foreign(phrase)
        if foreign:
            name, province, country, lat, lon = foreign
            place = Place(name, province, country, lat, lon, "localidad", "alta", "lista exterior")
            self._learn(phrase, place)
            return place, "exterior"

        country = detect_country(phrase)
        if country:
            if country == "argentina":
                return None, "país Argentina"
            key = COUNTRY_ALIASES.get(country, country)
            if key in COUNTRY_POINTS:
                lat, lon = COUNTRY_POINTS[key]
                place = Place(country.title(), None, country.title(), lat, lon,
                              "pais", "media", "centroide")
                self._learn(phrase, place)
                return place, "país"
            if allow_nominatim:
                place = self.geocoder.lookup_country(country)
                self._learn(phrase, place)
                return place, "país"
            return None, "país sin geocodificar"

        province_only = None
        for variant in _name_variants(phrase):
            province_only = self.gaz.exact_province(variant)
            if province_only:
                break
        if province_only:
            explicit_province = re.search(
                r"\b(?:provincia|pcia|prov)\b", norm(context) + " " + norm(phrase)
            )
            if explicit_province:
                return province_only, "provincia"
            # Para las provincias que también son una ciudad (Córdoba, Salta,
            # Santa Fe, etc.) preferimos la ciudad; para el resto, la provincia.
            alias = None
            normalized_province = norm(province_only.nombre)
            for key in PROVINCE_KEYS:
                if norm(PROVINCES[key]) == normalized_province and (
                    norm(phrase).startswith(key) or norm(phrase) == key
                ):
                    alias = key
                    break
            if norm(province_only.nombre) == "ciudad autonoma de buenos aires":
                return province_only, "provincia"
            if alias == "buenos aires":
                explicit = re.search(r"\b(?:provincia|pcia|prov)\b", norm(context))
                if not explicit:
                    return self.gaz.provinces.get("ciudad autonoma de buenos aires"), "provincia"
                return province_only, "provincia"
            province_only_names = {norm(PROVINCES[key]) for key in PROVINCE_ONLY}
            if normalized_province in province_only_names:
                return province_only, "provincia"
            if alias in PROVINCE_ONLY or (alias and re.search(r"\b(?:provincia|pcia|prov)\b", norm(context))):
                return province_only, "provincia"
            # Si la provincia tiene una ciudad homónima, seguimos con el gazetteer.

        if foreign_context:
            # El contexto menciona otro país (por ejemplo “San Pedro de
            # Atacama, Chile”): no lo resolvemos como una localidad argentina
            # homónima. En la segunda pasada se consulta Nominatim con el país.
            return None, "contexto de otro país"

        alias_hit = _prefix_alias(phrase) or _anywhere_alias(phrase)
        if alias_hit:
            _, target = alias_hit
            place, reason = self._resolve_name(norm(target), phrase, context, rule,
                                               nominatim_fallback=False)
            if place:
                self._learn(phrase, place)
                return place, reason

        for variant in _name_variants(phrase):
            place, reason = self._match_gazetteer(variant, phrase, context, rule)
            if place:
                self._learn(phrase, place)
                return place, reason

        if not allow_nominatim:
            return None, "sin coincidencia (sin Nominatim)"

        # Si la frase incluye una provincia, probamos Nominatim con ese contexto.
        province = detect_province(context) or detect_province(phrase)
        place = self.geocoder.lookup(phrase, province, "Argentina" if province else None)
        if place:
            # Sin provincia ni país en el texto no hay forma de confirmar el
            # homónimo: queda para revisión y no se publica por defecto.
            if not province and not context_country:
                place = replace_place(place, confianza="baja",
                                      detalle="Nominatim sin contexto")
            self._learn(phrase, place)
            return place, "Nominatim"

        return None, "sin coincidencia"

    def _match_gazetteer(self, variant: str, phrase: str, context: str, rule: str,
                         allow_anywhere: bool = False) -> tuple[Place | None, str]:
        for name, place in self.gaz.names_for(variant):
            if variant == name or variant.startswith(name + " "):
                if name in COMMON_WORD_PLACES and rule not in {"desde", "soy de", "presente", "aguante"}:
                    if variant != name:
                        continue
                resolved, reason = self._resolve_name(name, phrase, context, rule)
                if resolved:
                    return resolved, reason
        if allow_anywhere:
            normalized = norm(phrase)
            for name, _ in self.gaz.names_for(variant):
                if len(name) >= 5 and re.search(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", normalized):
                    resolved, reason = self._resolve_name(name, phrase, context, rule)
                    if resolved:
                        return resolved, reason
        return None, ""

    def _resolve_name(self, name: str, phrase: str, context: str, rule: str,
                      nominatim_fallback: bool = True) -> tuple[Place | None, str]:
        hint = detect_province(phrase) or detect_province(context)
        extra = EXTRA_PLACES.get(name)
        if extra and (not hint or hint == extra[1]):
            n, province, country, lat, lon = extra
            return Place(n, province, country, lat, lon, "localidad", "alta", "lista local"), "lista local"

        candidates = self.gaz.by_name.get(name)
        if not candidates:
            return None, ""
        # Deduplicar por coordenadas redondeadas.
        unique: dict[tuple, Place] = {}
        for candidate in candidates:
            key = (round(candidate.lat, 4), round(candidate.lon, 4), candidate.tipo)
            unique.setdefault(key, candidate)
        candidates = list(unique.values())

        if hint == "Buenos Aires":
            # Los barrios de CABA comparten el nombre de la provincia en el habla
            # cotidiana; aceptamos ambos.
            candidates_hint = [c for c in candidates if c.provincia in {"Buenos Aires", "Ciudad Autónoma de Buenos Aires"}]
        elif hint:
            candidates_hint = [c for c in candidates if c.provincia == hint]
        else:
            candidates_hint = []

        if hint and candidates_hint:
            return candidates_hint[0], "provincia"
        if hint and not candidates_hint:
            # El texto menciona otra provincia (por ejemplo “Chacarita,
            # Catamarca”): no forzamos una localidad homónima de otra provincia.
            return None, ""

        if name in PREFERRED_PROVINCE:
            preferred = [c for c in candidates if c.provincia == PREFERRED_PROVINCE[name]]
            if preferred:
                confidence = "alta" if not hint else "media"
                place = replace_place(preferred[0], confianza=confidence)
                return place, "preferencia"

        if len(candidates) == 1:
            return candidates[0], "única"

        # Si todas las coincidencias están en la misma provincia, no hay ambigüedad.
        provinces = {c.provincia for c in candidates}
        if len(provinces) == 1:
            return candidates[0], "única provincia"

        if hint:
            return None, ""

        # Último recurso: elegir la primera y marcarla para revisión.
        return replace_place(candidates[0], confianza="baja"), "ambigua"


# ---------------------------------------------------------------------------
# Construcción del GeoJSON
# ---------------------------------------------------------------------------


RULE_PRIORITY = {
    "desde": 0, "soy de": 0, "estoy en": 0, "acá en": 0,
    "saludo": 1, "presente": 1, "aguante": 2, "mensaje corto": 3,
}

# Solo estas pistas justifican consultar Nominatim. "aguante" es una arenga,
# no una afirmación de ubicación, y produce falsos positivos como
# "aguante el metal" -> El Metal (Asturias).
NOMINATIM_RULES = {"desde", "soy de", "estoy en", "acá en", "saludo", "presente"}


NON_PLACE_WORDS = {
    "hermoso", "hermosa", "lugar", "sitio", "mañana", "manana", "gracias",
    "bendiciones", "viva", "mejor", "zona", "reserva", "vida", "falta",
    "suerte", "pais", "mundo", "dia", "dias", "trabajo", "equipo", "chicos",
    "gente", "amigos", "todo", "todos", "toda", "todas", "nada", "algo",
    "sur", "norte", "este", "oeste", "centro", "conurbano", "patagonia",
    "que", "quien", "quienes", "como", "cuando", "donde", "cuanto", "cuanta",
    "cuantos", "cuantas", "porque", "para", "sobre", "entre", "segun", "mientras",
    "por", "con", "sin", "su", "sus", "mi", "mis", "tu", "tus", "nuestra",
    "nuestro", "parte", "abuela", "abuelo", "familia", "parientes", "amigos",
    "division", "antropologia", "arqueologia", "ciencia", "cultura", "ancestral",
    "costa", "centrales", "umai", "turqui", "colegas", "unju",
    "metal", "chamba", "esta", "aventura", "cientificos", "cientificas",
}


def candidate_is_plausible(phrase: str, rule: str, message: Message) -> bool:
    normalized = norm(phrase)
    if not normalized or is_generic_short(normalized):
        return False
    words = normalized.split()
    if len(words) > 5:
        return False
    if re.search(r"[0-9]", normalized):
        return False
    if any(word in NON_PLACE_WORDS for word in words):
        return False
    # Los mensajes cortos que no coincidieron con Georef/alias no se mandan a
    # Nominatim: suelen ser saludos, nombres de personas o frases sueltas.
    if rule == "mensaje corto":
        return normalized in FOREIGN_PLACES or normalized in EXTRA_PLACES
    return True


def best_for_candidates(candidates: list[tuple], resolver: Resolver,
                        allow_nominatim: bool) -> Match | None:
    best: tuple[int, Match] | None = None
    for phrase, rule, base_confidence, message in candidates:
        place, reason = resolver.resolve(phrase, message.texto, rule,
                                         allow_nominatim=allow_nominatim)
        if not place:
            continue
        confidence = place.confianza
        if confidence == "alta" and reason == "ambigua":
            confidence = "baja"
        if confidence == "alta" and rule == "mensaje corto" and reason == "Nominatim":
            confidence = "media"
        match = Match(place, message, phrase, rule, confidence)
        score = CONFIDENCE_ORDER.get(confidence, 9)
        if best is None or score < best[0]:
            best = (score, match)
    return best[1] if best else None


def choose_matches(grouped: dict[str, list[Message]], resolver: Resolver,
                   verbose: bool = False) -> tuple[list[Match], list[dict]]:
    matches: list[Match] = []
    unresolved: list[dict] = []
    total = len(grouped)
    last_report = time.monotonic()
    print("  Buscando coincidencias con datos locales…", file=sys.stderr, flush=True)

    for index, (user, messages) in enumerate(grouped.items(), 1):
        candidates: list[tuple] = []
        seen: set[tuple[str, str]] = set()
        for message in messages:
            for phrase, rule, base_confidence in message_candidates(message):
                key = (norm(phrase), rule)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append((phrase, rule, base_confidence, message))

        if not candidates:
            continue

        # Primera pasada sin red: Georef, alias, provincias, países y una lista
        # curada de lugares del exterior.
        match = best_for_candidates(candidates, resolver, allow_nominatim=False)

        # Solo si no hubo coincidencia, probamos Nominatim con un máximo de dos
        # frases plausibles por usuario. Así no se consulta por saludos ni por
        # nombres de personas.
        if match is None:
            ordered = sorted(
                candidates,
                key=lambda item: (RULE_PRIORITY.get(item[1], 9), item[3].timestamp),
            )
            plausible: list[tuple] = []
            tried: set[str] = set()
            for candidate in ordered:
                phrase, rule, _, message = candidate
                if rule not in NOMINATIM_RULES:
                    continue
                if not candidate_is_plausible(phrase, rule, message):
                    continue
                key = norm(phrase)
                if key in tried:
                    continue
                tried.add(key)
                plausible.append(candidate)
                if len(plausible) >= 2:
                    break
            if plausible:
                match = best_for_candidates(plausible, resolver, allow_nominatim=True)

        if match:
            matches.append(match)
        else:
            first = sorted(candidates, key=lambda item: (RULE_PRIORITY.get(item[1], 9), item[3].timestamp))[0]
            unresolved.append({
                "usuario": user,
                "frase": first[0],
                "mensaje": first[3].texto,
                "motivo": "sin coincidencia",
            })
            if verbose:
                print(f"  Sin ubicación: {user} | {first[0]}", file=sys.stderr)

        now = time.monotonic()
        if index == total or index % 25 == 0 or now - last_report >= 5:
            percent = index * 100 // total if total else 100
            print(
                f"  Progreso: {index}/{total} usuarios ({percent}%) · "
                f"{len(matches)} ubicados · {len(unresolved)} sin ubicación · "
                f"{resolver.geocoder.new_requests} consultas nuevas",
                file=sys.stderr, flush=True,
            )
            last_report = now

    return matches, unresolved


def pick_best_per_user(matches: list[Match]) -> dict[str, Match]:
    best: dict[str, Match] = {}
    for match in matches:
        current = best.get(match.mensaje.usuario)
        if current is None:
            best[match.mensaje.usuario] = match
            continue
        new_key = (CONFIDENCE_ORDER.get(match.confianza, 9), match.mensaje.timestamp)
        old_key = (CONFIDENCE_ORDER.get(current.confianza, 9), current.mensaje.timestamp)
        if new_key < old_key:
            best[match.mensaje.usuario] = match
    return best


def load_revision(path: Path) -> dict:
    if not path.exists():
        return {"excluir_usuarios": [], "excluir_lugares": [], "incluir": {},
                "corregir": {}, "incluir_baja": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"El archivo {path} no es JSON válido: {exc}")
    data.setdefault("excluir_usuarios", [])
    data.setdefault("excluir_lugares", [])
    data.setdefault("incluir", {})
    data.setdefault("corregir", {})
    data.setdefault("incluir_baja", False)
    return data


def place_from_override(entry: dict, resolver: Resolver) -> Place | None:
    lat, lon = entry.get("lat"), entry.get("lon")
    name = entry.get("Lugar") or entry.get("lugar")
    if lat is not None and lon is not None and name:
        return Place(
            name,
            entry.get("Provincia") or entry.get("provincia"),
            entry.get("Pais") or entry.get("pais") or "Argentina",
            float(lat), float(lon),
            entry.get("Tipo") or entry.get("tipo") or "localidad",
            "alta", "revisión",
        )
    if name:
        province = entry.get("Provincia") or entry.get("provincia") or ""
        country = entry.get("Pais") or entry.get("pais") or ("Argentina" if province else None)
        place = resolver.geocoder.lookup(name, province or None, country)
        if not place:
            context = name + (", " + province if province else "")
            place, _ = resolver.resolve(name, context, "desde")
        if place:
            place = replace_place(place, fuente="revisión")
            if province:
                place = replace_place(place, provincia=province)
            return place
    return None


def build_features(best: dict[str, Match], all_messages: dict[str, list[Message]],
                   revision: dict, resolver: Resolver,
                   incluir_baja: bool = False) -> list[dict]:
    excluded = set(revision.get("excluir_usuarios", []))
    excluded_places = {norm(name) for name in revision.get("excluir_lugares", [])}

    records: dict[str, list[tuple[str, Place, Message]]] = defaultdict(list)

    for user, match in best.items():
        if user in excluded:
            continue
        override = revision.get("corregir", {}).get(user, {})
        place = place_from_override(override, resolver) or match.place
        # Las ubicaciones dudosas quedan en el reporte para revisión, no en el
        # mapa, salvo que se pidan explícitamente o se corrijan a mano.
        if not override and not incluir_baja and match.confianza == "baja":
            continue
        if norm(place.nombre) in excluded_places:
            continue
        records[user].append((user, place, match.mensaje))

    for user, entry in revision.get("incluir", {}).items():
        if user in excluded:
            continue
        place = place_from_override(entry, resolver)
        if not place or norm(place.nombre) in excluded_places:
            continue
        messages = all_messages.get(user, [])
        anchor = messages[0] if messages else Message(user, "", 0)
        records[user].append((user, place, anchor))

    features: dict[tuple, dict] = {}
    for user, entries in records.items():
        for _, place, anchor in entries:
            if place.lat == 0 and place.lon == 0:
                continue
            key = (place.tipo, norm(place.nombre), norm(place.provincia or ""), norm(place.pais or ""))
            feature = features.setdefault(key, {
                "type": "Feature",
                "properties": {
                    "Lugar": place.nombre,
                    "Provincia": place.provincia or "",
                    "Pais": place.pais or "",
                    "Tipo": place.tipo,
                    "Oyentes": [],
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(place.lon, 5), round(place.lat, 5)],
                },
            })
            if any(o["Usuario"] == user for o in feature["properties"]["Oyentes"]):
                continue

            anchor_text = clean_text(anchor.texto)
            anchor_day = anchor.dia or ""
            others: list[str] = []
            comments_by_day: dict[str, list[str]] = {}
            days: list[str] = []

            for message in all_messages.get(user, []):
                text = clean_text(message.texto)
                if not text:
                    continue
                dia = message.dia or anchor_day
                if dia and dia not in days:
                    days.append(dia)
                if anchor_text and text == anchor_text and dia == anchor_day:
                    continue
                if text not in others:
                    others.append(text)
                if dia:
                    bucket = comments_by_day.setdefault(dia, [])
                    if text not in bucket:
                        bucket.append(text)

            if anchor_day and anchor_day not in days:
                days.append(anchor_day)
            if anchor_text and anchor_day:
                bucket = comments_by_day.setdefault(anchor_day, [])
                if anchor_text not in bucket:
                    bucket.insert(0, anchor_text)

            ordered_days = sorted(days, key=day_sort_key)
            ordered_comments = {
                dia: comments_by_day[dia]
                for dia in sorted(comments_by_day, key=day_sort_key)
            }

            feature["properties"]["Oyentes"].append({
                "Usuario": user,
                "Mensaje": anchor_text,
                "Dia": anchor_day,
                "Comentarios": others,
                "Dias": ordered_days,
                "ComentariosPorDia": ordered_comments,
            })

    feats = list(features.values())
    for feature in feats:
        feature["properties"]["Oyentes"].sort(key=lambda item: item["Usuario"].lower())
        feature["properties"]["Cantidad"] = len(feature["properties"]["Oyentes"])
    feats.sort(key=lambda f: (f["properties"]["Lugar"].lower(), f["properties"]["Provincia"]))
    return feats


def write_geojson(features: list[dict], output: Path, total_messages: int,
                  total_users: int) -> None:
    payload = {
        "type": "FeatureCollection",
        "metadata": {
            "videos": [
                {"id": vid, "url": url, "titulo": titulo, "dia": day_label(titulo)}
                for url, vid, titulo in VIDEOS
            ],
            "dias": [day_label(titulo) for _, _, titulo in VIDEOS],
            "video": VIDEO_URL,
            "video_id": VIDEO_ID,
            "titulo": "Expedición Inka",
            "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "comentarios_analizados": total_messages,
            "usuarios_analizados": total_users,
            "localidades": len(features),
            "oyentes_mapeados": sum(f["properties"]["Cantidad"] for f in features),
        },
        "features": features,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_reports(matches: list[Match], unresolved: list[dict], all_messages: dict[str, list[Message]],
                  report_path: Path, unresolved_path: Path) -> None:
    best = pick_best_per_user(matches)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["usuario", "lugar", "provincia", "pais", "tipo", "lat", "lon",
                         "confianza", "fuente", "regla", "frase", "mensaje", "comentarios"])
        for user in sorted(best):
            match = best[user]
            place = match.place
            others = []
            for message in all_messages.get(user, []):
                text = clean_text(message.texto)
                if text and text != clean_text(match.mensaje.texto) and text not in others:
                    others.append(text)
            writer.writerow([
                user, place.nombre, place.provincia or "", place.pais or "", place.tipo,
                f"{place.lat:.5f}", f"{place.lon:.5f}", match.confianza, place.fuente,
                match.regla, match.frase, clean_text(match.mensaje.texto), " | ".join(others),
            ])

    with unresolved_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["usuario", "frase", "mensaje", "motivo"])
        seen = set()
        for row in unresolved:
            key = (row["usuario"], row["frase"], row["mensaje"])
            if key in seen:
                continue
            seen.add(key)
            writer.writerow([row["usuario"], row["frase"], row["mensaje"], row["motivo"]])


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera localidades.geojson a partir del chat del vivo de YouTube.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  python3 scripts/generar_localidades.py\n"
            "  python3 scripts/generar_localidades.py --solo-reporte\n"
            "  python3 scripts/generar_localidades.py --chat /ruta/chat.live_chat.json\n"
        ),
    )
    parser.add_argument("--video", default=None, help="URL de un único vivo a procesar (por defecto se procesan todos los videos del streaming).")
    parser.add_argument("--chat", type=Path, help="Archivo JSONL del chat ya descargado.")
    parser.add_argument("--salida", type=Path, default=DEFAULT_OUTPUT, help="GeoJSON de salida.")
    parser.add_argument("--reporte", type=Path, default=DEFAULT_REPORT, help="CSV de revisión.")
    parser.add_argument("--no-detectados", type=Path, default=DEFAULT_UNRESOLVED,
                        help="CSV con frases no resueltas.")
    parser.add_argument("--revision", type=Path, default=DEFAULT_REVISION,
                        help="JSON con correcciones manuales.")
    parser.add_argument("--diccionario", type=Path, default=DEFAULT_DICTIONARY,
                        help="Diccionario de frases ya aprendidas (scripts/diccionario_lugares.json).")
    parser.add_argument("--sin-aprender", action="store_true",
                        help="No guarda nuevas frases en el diccionario.")
    parser.add_argument("--actualizar-diccionario", action="store_true",
                        help="Sobrescribe con los resultados de esta corrida las frases ya existentes.")
    parser.add_argument("--solo-reporte", action="store_true",
                        help="No escribe el GeoJSON; solo genera los CSV de revisión.")
    parser.add_argument("--incluir-baja", action="store_true",
                        help="Incluye en el GeoJSON los lugares de confianza baja. "
                             "También se puede activar con \"incluir_baja\": true en revision.json.")
    parser.add_argument("--actualizar-chat", action="store_true", help="Vuelve a descargar el chat.")
    parser.add_argument("--actualizar-datos", action="store_true",
                        help="Vuelve a descargar localidades y provincias de Georef.")
    parser.add_argument("--pausa", type=float, default=1.1,
                        help="Segundos entre consultas a Nominatim (por defecto 1.1).")
    parser.add_argument("--max-consultas", type=int, default=400,
                        help="Máximo de consultas nuevas a Nominatim en una corrida (por defecto 400).")
    parser.add_argument("--verbose", action="store_true", help="Muestra más detalles.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)

    if args.chat:
        chat_sources = [(args.chat, "Día 1")]
    elif args.video:
        vid = args.video.split("v=")[-1].split("&")[0] if "v=" in args.video else args.video.rstrip("/").split("/")[-1]
        chat_sources = [(download_chat(args.video, vid, force=args.actualizar_chat), "")]
    else:
        chat_sources = [
            (download_chat(url, vid, force=args.actualizar_chat), day_label(titulo))
            for url, vid, titulo in VIDEOS
        ]

    all_messages: list[Message] = []
    for chat_path, dia in chat_sources:
        print(f"Leyendo chat: {chat_path}" + (f" ({dia})" if dia else ""), file=sys.stderr)
        msgs = parse_chat(chat_path, dia)
        all_messages.extend(msgs)
        print(f"  {len(msgs)} comentarios", file=sys.stderr)
    messages = all_messages
    grouped = group_messages(messages)
    print(f"{len(messages)} comentarios de {len(grouped)} usuarios (todos los videos).", file=sys.stderr)

    localidades, provincias = load_reference_data(force=args.actualizar_datos)
    gaz = Gazetteer(localidades, provincias)
    dictionary = load_dictionary(args.diccionario)
    geocoder = Geocoder(CACHE / "geocoding.json", pause=args.pausa,
                        max_new_requests=args.max_consultas)
    resolver = Resolver(gaz, geocoder, dictionary)

    matches, unresolved = choose_matches(grouped, resolver, verbose=args.verbose)
    best = pick_best_per_user(matches)
    print(f"Usuarios con localidad detectada: {len(best)}", file=sys.stderr)
    if unresolved:
        print(f"Usuarios sin ubicación: {len(unresolved)} (ver {args.no_detectados})", file=sys.stderr)

    write_reports(matches, unresolved, grouped, args.reporte, args.no_detectados)
    print(f"Reporte: {args.reporte}", file=sys.stderr)
    print(f"No detectados: {args.no_detectados}", file=sys.stderr)

    if not args.sin_aprender and resolver.learned:
        merged = dict(dictionary)
        if args.actualizar_diccionario:
            merged.update(resolver.learned)
        else:
            for key, place in resolver.learned.items():
                merged.setdefault(key, place)
        save_dictionary(args.diccionario, merged)
        print(f"Diccionario: {args.diccionario} ({len(merged)} frases)", file=sys.stderr)

    if args.solo_reporte:
        geocoder.save()
        return

    revision = load_revision(args.revision)
    incluir_baja = args.incluir_baja or revision.get("incluir_baja", False)
    features = build_features(best, grouped, revision, resolver,
                              incluir_baja=incluir_baja)
    write_geojson(features, args.salida, len(messages), len(grouped))
    geocoder.save()

    mapped = sum(f["properties"]["Cantidad"] for f in features)
    print(f"GeoJSON: {args.salida} ({len(features)} lugares, {mapped} oyentes)", file=sys.stderr)


if __name__ == "__main__":
    main()
