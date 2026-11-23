#!/usr/bin/env python3
"""Descarga y analiza los chats de Expedición Inka, días 2, 3 y 4.

Desde la raíz del repositorio:
    python3 scripts/generar_dias_2_4.py --solo-reporte
    python3 scripts/generar_dias_2_4.py

La primera opción produce los reportes CSV para revisión sin tocar el GeoJSON
publicado. La segunda combina los resultados con el mapa existente (día 1).
Requiere los mismos requisitos que generar_localidades.py, incluido yt-dlp.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
GENERATOR = SCRIPTS / "generar_localidades.py"
CACHE = SCRIPTS / ".cache" / "dias_2_4"
DEFAULT_OUTPUT = ROOT / "localidades.geojson"

VIDEOS = (
    (2, "vhFyl24JLlw", "https://www.youtube.com/watch?v=vhFyl24JLlw"),
    (3, "g3Blu5r05eQ", "https://www.youtube.com/watch?v=g3Blu5r05eQ"),
    (4, "0ivWpycYBuM", "https://www.youtube.com/watch?v=0ivWpycYBuM"),
)


def normalized(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    return "".join(char for char in text if unicodedata.category(char) != "Mn").casefold().strip()


def feature_key(feature: dict) -> tuple[str, str, str, str]:
    props = feature.get("properties") or {}
    return tuple(normalized(props.get(field)) for field in ("Lugar", "Provincia", "Pais", "Tipo"))


def people_from(feature: dict) -> list[dict]:
    props = feature.get("properties") or {}
    people = props.get("Oyentes")
    if isinstance(people, list):
        return [dict(person) for person in people if isinstance(person, dict)]
    if props.get("Usuario") or props.get("Comentario"):
        return [{
            "Usuario": props.get("Usuario", ""),
            "Mensaje": props.get("Comentario", ""),
            "Comentarios": [],
        }]
    return []


def merge_person(existing: dict, incoming: dict) -> None:
    comments = existing.setdefault("Comentarios", [])
    if not isinstance(comments, list):
        comments = existing["Comentarios"] = []
    for comment in incoming.get("Comentarios", []) or []:
        if comment and comment not in comments:
            comments.append(comment)
    message = incoming.get("Mensaje", "")
    if message and message != existing.get("Mensaje") and message not in comments:
        comments.append(message)


def merge_feature(target: dict, source: dict) -> None:
    target_people = target["properties"].setdefault("Oyentes", [])
    by_user = {normalized(person.get("Usuario")): person for person in target_people}
    for person in people_from(source):
        username = normalized(person.get("Usuario"))
        if username and username in by_user:
            merge_person(by_user[username], person)
        else:
            copied = dict(person)
            copied["Comentarios"] = list(copied.get("Comentarios", []) or [])
            target_people.append(copied)
            if username:
                by_user[username] = copied


def read_collection(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"No se pudo leer un GeoJSON válido en {path}: {exc}")
    if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise SystemExit(f"El archivo no es un FeatureCollection GeoJSON: {path}")
    return data


def run_generator(day: int, video_url: str, args: argparse.Namespace) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    output = CACHE / f"localidades_dia_{day}.geojson"
    report = SCRIPTS / f"reporte_dia_{day}.csv"
    unresolved = SCRIPTS / f"no_detectados_dia_{day}.csv"
    command = [
        sys.executable, str(GENERATOR),
        "--video", video_url,
        "--salida", str(output),
        "--reporte", str(report),
        "--no-detectados", str(unresolved),
        "--actualizar-chat",
        "--pausa", str(args.pausa),
        "--max-consultas", str(args.max_consultas),
    ]
    if args.actualizar_datos:
        command.append("--actualizar-datos")
    if args.sin_aprender:
        command.append("--sin-aprender")
    if args.solo_reporte:
        command.append("--solo-reporte")
    print(f"\n=== Expedición Inka: día {day} ===", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)
    return output


def video_summary(day: int, video_id: str, url: str, metadata: dict) -> dict:
    return {
        "dia": day,
        "video_id": video_id,
        "video": url,
        "comentarios_analizados": int(metadata.get("comentarios_analizados", 0)),
        "usuarios_analizados": int(metadata.get("usuarios_analizados", 0)),
        "localidades": int(metadata.get("localidades", 0)),
        "oyentes_mapeados": int(metadata.get("oyentes_mapeados", 0)),
    }


def combine(base_path: Path, day_paths: list[tuple[int, str, str, Path]], output_path: Path) -> None:
    base = read_collection(base_path)
    merged: dict[tuple[str, str, str, str], dict] = {}
    for feature in base["features"]:
        if isinstance(feature, dict):
            merged[feature_key(feature)] = feature

    video_data = []
    base_metadata = base.get("metadata") or {}
    day1_url = base_metadata.get("video", "https://www.youtube.com/live/CtAJIkQDiyQ")
    day1_id = str(base_metadata.get("video_id", "CtAJIkQDiyQ"))
    video_data.append(video_summary(1, day1_id, day1_url, base_metadata))

    for day, video_id, url, path in day_paths:
        collection = read_collection(path)
        metadata = collection.get("metadata") or {}
        video_data.append(video_summary(day, video_id, url, metadata))
        for feature in collection["features"]:
            if not isinstance(feature, dict):
                continue
            key = feature_key(feature)
            if key in merged:
                merge_feature(merged[key], feature)
            else:
                copied = dict(feature)
                copied["properties"] = dict(feature.get("properties") or {})
                copied["properties"]["Oyentes"] = people_from(feature)
                merged[key] = copied

    features = list(merged.values())
    for feature in features:
        props = feature.setdefault("properties", {})
        people = props.setdefault("Oyentes", [])
        people.sort(key=lambda person: normalized(person.get("Usuario")))
        props["Cantidad"] = len(people)
    features.sort(key=lambda feature: (
        normalized((feature.get("properties") or {}).get("Lugar")),
        normalized((feature.get("properties") or {}).get("Provincia")),
    ))

    metadata = {
        "video": day1_url,
        "video_id": day1_id,
        "titulo": "Expedición Inka 2026 - Días 1 a 4",
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "comentarios_analizados": sum(item["comentarios_analizados"] for item in video_data),
        "usuarios_analizados": sum(item["usuarios_analizados"] for item in video_data),
        "localidades": len(features),
        "oyentes_mapeados": sum(feature["properties"]["Cantidad"] for feature in features),
        "videos": video_data,
    }
    payload = {"type": "FeatureCollection", "metadata": metadata, "features": features}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_output.replace(output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analiza los chats de los días 2–4 y actualiza el mapa del día 1.")
    parser.add_argument("--salida", type=Path, default=DEFAULT_OUTPUT, help="GeoJSON combinado de salida.")
    parser.add_argument("--solo-reporte", action="store_true", help="Genera los CSV por día sin modificar el GeoJSON.")
    parser.add_argument("--pausa", type=float, default=1.1, help="Pausa entre solicitudes a Nominatim.")
    parser.add_argument("--max-consultas", type=int, default=400, help="Máximo de consultas nuevas a Nominatim por día.")
    parser.add_argument("--actualizar-datos", action="store_true", help="Vuelve a descargar datos de Georef.")
    parser.add_argument("--sin-aprender", action="store_true", help="No modifica el diccionario de lugares.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not GENERATOR.is_file():
        raise SystemExit(f"No se encuentra el generador existente: {GENERATOR}")
    if not args.solo_reporte and not args.salida.is_file():
        raise SystemExit(f"No se encuentra el mapa del día 1: {args.salida}. Use --solo-reporte o restaure el GeoJSON primero.")

    generated: list[tuple[int, str, str, Path]] = []
    for day, video_id, url in VIDEOS:
        path = run_generator(day, url, args)
        if not args.solo_reporte:
            if not path.is_file():
                raise SystemExit(f"El generador no produjo el GeoJSON del día {day}: {path}")
            generated.append((day, video_id, url, path))

    if args.solo_reporte:
        print("\nReportes listos: scripts/reporte_dia_N.csv y scripts/no_detectados_dia_N.csv")
        print("Revise los candidatos antes de regenerar el mapa sin --solo-reporte.")
        return

    combine(args.salida, generated, args.salida)
    print(f"\nMapa actualizado: {args.salida}")
    print("Se combinaron los resultados con las localidades ya existentes del día 1.")


if __name__ == "__main__":
    main()
