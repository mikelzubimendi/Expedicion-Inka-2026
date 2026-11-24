#!/usr/bin/env python3
"""Estadisticas a partir de localidades.geojson.

Calcula, por dia y global:
- comentarios: total de mensajes en ComentariosPorDia
- usuarios: oyentes unicos
- localidades: features/ubicaciones con actividad

Tambien calcula el top 10 de usuarios por cantidad de comentarios.
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEOJSON = ROOT / "localidades.geojson"
OUT_JSON = Path(__file__).resolve().parent / "estadisticas_localidades.json"

DIAS = ["Día 1", "Día 2", "Día 3", "Día 4"]


def main():
    with GEOJSON.open(encoding="utf-8") as f:
        data = json.load(f)

    features = data["features"]

    comments_by_day = Counter()
    users_by_day = defaultdict(set)
    locs_by_day = defaultdict(set)
    user_comments = Counter()
    user_localidad = {}

    all_users = set()

    for idx, feat in enumerate(features):
        loc_name = feat["properties"]["Lugar"]
        prov = feat["properties"]["Provincia"]
        pais = feat["properties"]["Pais"]
        loc_key = (loc_name, prov, pais)

        for oyente in feat["properties"].get("Oyentes", []):
            user = oyente["Usuario"]
            all_users.add(user)
            user_localidad[user] = f"{loc_name}, {prov}, {pais}"

            for dia, msgs in oyente.get("ComentariosPorDia", {}).items():
                comments_by_day[dia] += len(msgs)
                users_by_day[dia].add(user)
                locs_by_day[dia].add(idx)
                user_comments[user] += len(msgs)

    por_dia = {}
    for dia in DIAS:
        por_dia[dia] = {
            "comentarios": comments_by_day.get(dia, 0),
            "usuarios": len(users_by_day.get(dia, set())),
            "localidades": len(locs_by_day.get(dia, set())),
        }

    global_stats = {
        "comentarios": sum(comments_by_day.values()),
        "usuarios": len(all_users),
        "localidades": len(features),
    }

    top_usuarios = [
        {
            "usuario": u,
            "comentarios": n,
            "localidad": user_localidad.get(u),
        }
        for u, n in user_comments.most_common(10)
    ]

    result = {
        "global": global_stats,
        "por_dia": por_dia,
        "top_10_usuarios": top_usuarios,
    }

    with OUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # Resumen en consola
    print("GLOBAL:", global_stats)
    for dia in DIAS:
        print(dia, por_dia[dia])
    print("\nTop 10 usuarios por comentarios:")
    for i, u in enumerate(top_usuarios, 1):
        print(f"{i:2d}. {u['usuario']}: {u['comentarios']} ({u['localidad']})")

    print(f"\nGuardado en: {OUT_JSON}")


if __name__ == "__main__":
    main()
