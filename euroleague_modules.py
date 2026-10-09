"""EuroLeague results, next-round and standings XML conversions."""

from datetime import date, datetime, timezone
from html import escape
import os
import re
import ssl
from uuid import uuid4
import xml.etree.ElementTree as ET

import requests


EUROLEAGUE_SEASON = os.environ.get("EUROLEAGUE_SEASON", "E2026")
API_BASE = "https://api-live.euroleague.net/v1"
SYSTEM_CA_BUNDLE = ssl.get_default_verify_paths().cafile

TEAM_NAMES = {
    "ANADOLU EFES ISTANBUL": "Anadolu Efes",
    "OLYMPIACOS PIRAEUS": "Olympiacos",
    "MACCABI RAPYD TEL AVIV": "Maccabi Tel Aviv",
    "MACCABI PLAYTIKA TEL AVIV": "Maccabi Tel Aviv",
    "MACCABI TEL AVIV": "Maccabi Tel Aviv",
    "PANATHINAIKOS AKTOR ATHENS": "Panathinaikos",
    "FC BAYERN MUNICH": "Bayern Múnich",
    "VALENCIA BASKET": "Valencia Basket",
    "EA7 EMPORIO ARMANI MILAN": "Armani Milán",
    "OLIMPIA MILANO": "Armani Milán",
    "ZALGIRIS KAUNAS": "Zalgiris Kaunas",
    "REAL MADRID": "Real Madrid",
    "AS MONACO": "AS Mónaco",
    "PARIS BASKETBALL": "Paris Basketball",
    "DUBAI BASKETBALL": "Dubai Basketball",
    "FENERBAHCE BEKO ISTANBUL": "Fenerbahçe",
    "FENERBAHCE TARFIN ISTANBUL": "Fenerbahçe",
    "KOSNER BASKONIA VITORIA-GASTEIZ": "Kosner Baskonia",
    "BASKONIA VITORIA-GASTEIZ": "Baskonia",
    "VIRTUS BOLOGNA": "Virtus Bolonia",
    "CRVENA ZVEZDA MERIDIANBET BELGRADE": "Estrella Roja",
    "PARTIZAN MOZZART BET BELGRADE": "Partizan",
    "HAPOEL IBI TEL AVIV": "Hapoel Tel Aviv",
    "LDLC ASVEL VILLEURBANNE": "Asvel Villeurbanne",
    "FC BARCELONA": "Barça",
    "BESIKTAS ISTANBUL": "Besiktas",
}

MONTH_NAMES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}
DAY_NAMES = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
SHORT_DAY_NAMES = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
ENGLISH_MONTHS = {
    name: number for number, name in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        start=1,
    )
}


class EuroleagueApiError(RuntimeError):
    """Raised when the official EuroLeague feeds cannot be retrieved or parsed."""


def _local_tag(tag):
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element, name, default=""):
    """Busca el texto de un tag de forma recursiva para encontrarlo aunque esté anidado."""
    name = name.lower()
    for child in element.iter():
        if _local_tag(child.tag) == name:
            return (child.text or "").strip()
    return default


def _feed_items(root, item_tag):
    return [
        element for element in root.iter()
        if _local_tag(element.tag) == item_tag.lower()
    ]


def _fetch_feed(endpoint, params):
    try:
        response = requests.get(
            f"{API_BASE}/{endpoint}",
            params=params,
            headers={"Accept": "application/xml", "User-Agent": "BasketballStatsXML/1.0"},
            timeout=20,
            verify=SYSTEM_CA_BUNDLE or True,
        )
        response.raise_for_status()
        return ET.fromstring(response.content)
    except requests.RequestException as error:
        raise EuroleagueApiError(
            f"No se pudo consultar el servicio de Euroliga ({endpoint})."
        ) from error
    except ET.ParseError as error:
        raise EuroleagueApiError(
            f"El servicio de Euroliga devolvió XML no válido ({endpoint})."
        ) from error


def _parse_date(value):
    match = re.fullmatch(r"([A-Za-z]{3})\s+(\d{1,2}),\s*(\d{4})", value.strip())
    if match:
        month = ENGLISH_MONTHS.get(match.group(1).title())
        if month:
            return date(int(match.group(3)), month, int(match.group(2)))
    try:
        return date.fromisoformat(value.strip())
    except ValueError as error:
        raise EuroleagueApiError("La API devolvió una fecha de partido no válida.") from error


def _parse_bool(value):
    return value.strip().lower() in ("true", "1", "yes")


def _team_name(value):
    return TEAM_NAMES.get(value.strip().upper(), value.strip())


def _format_full_date(game_date):
    return (
        f"{DAY_NAMES[game_date.weekday()]}, {game_date.day} "
        f"{MONTH_NAMES[game_date.month]}"
    )


def _format_short_date(game_date, time):
    return f"{SHORT_DAY_NAMES[game_date.weekday()]}, {game_date.day} {time or '00:00'}h"


def _xml_text(value):
    return escape(str(value), quote=False)


def _wrap_gameday_xml(table, output_format):
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<?EM-templateName /SysConfig/GODO/Templates/Base/story.xml?>\n'
        '<!DOCTYPE doc\n'
        '  SYSTEM "/SysConfig/GODO/Rules/eidosint.dtd">\n'
        '<doc xml:lang="es"><story><text sourceCIL="4.12.Generated" '
        f'this="/GODO/MD/Baloncesto/Articulos/{today}/{output_format}.xml">'
        f'<content class="ACBX">{table}</content></text></story></doc>'
    )


def generate_gameday_xml(gameday, output_format):
    if isinstance(gameday, bool) or not isinstance(gameday, int) or not 1 <= gameday <= 38:
        raise ValueError("La jornada debe ser un número entre 1 y 38.")
    if output_format not in ("ELBR", "ELBP"):
        raise ValueError("Selecciona un formato válido: ELBR o ELBP.")

    schedule_root = _fetch_feed(
        "schedules",
        {
            "competitionCode": "E",
            "seasonCode": EUROLEAGUE_SEASON,
            "phaseTypeCode": "RS",
        },
    )
    results_root = _fetch_feed(
        "results",
        {"competitionCode": "E", "seasonCode": EUROLEAGUE_SEASON},
    )

    schedule_items = []
    for item in _feed_items(schedule_root, "item"):
        try:
            item_gameday = int(_child_text(item, "gameday"))
        except ValueError:
            continue
        if item_gameday != gameday:
            continue

        date_text = _child_text(item, "date")
        if not date_text:
            continue
        game_date = _parse_date(date_text)
        schedule_items.append({
            "date": game_date,
            "time": _child_text(item, "startime"),
            "home": _team_name(_child_text(item, "hometeam")),
            "away": _team_name(_child_text(item, "awayteam")),
            "gamecode": _child_text(item, "gamecode"),
            "played": _parse_bool(_child_text(item, "played")),
        })

    if not schedule_items:
        raise ValueError(f"No se encontraron partidos para la jornada {gameday}.")

    results_by_gamecode = {
        _child_text(item, "gamecode"): item
        for item in _feed_items(results_root, "game")
        if _child_text(item, "gamecode")
    }

    games = []
    for scheduled in schedule_items:
        result = results_by_gamecode.get(scheduled["gamecode"])
        home_score = _child_text(result, "homescore") if result is not None else ""
        away_score = _child_text(result, "awayscore") if result is not None else ""
        games.append({
            **scheduled,
            "home_score": home_score,
            "away_score": away_score,
        })

    games.sort(key=lambda game: (game["date"], game["time"] or "00:00"))
    if output_format == "ELBP":
        rows = [
            f'<tr><td class="fecha">La próxima jornada ({gameday})</td></tr>'
        ]
        for game in games:
            when = _format_short_date(game["date"], game["time"])
            rows.append(
                f'<tr><td>{_xml_text(game["home"])}-{_xml_text(game["away"])} '
                f'<ld pattern=""/>{_xml_text(when)}</td></tr>'
            )
        table = '<table class="proxima_jornada">' + "".join(rows) + "</table>"
        return _wrap_gameday_xml(table, output_format)

    grouped_rows = []
    current_date = None
    for game in games:
        if game["date"] != current_date:
            current_date = game["date"]
            grouped_rows.append(
                f'<tr><td class="fecha">{_xml_text(_format_full_date(current_date))}</td></tr>'
            )
        if game["played"] and game["home_score"] and game["away_score"]:
            score_or_time = f'{game["home_score"]}-{game["away_score"]}'
        else:
            score_or_time = game["time"] or "Por definir"
        grouped_rows.append(
            f'<tr><td>{_xml_text(game["home"])}-{_xml_text(game["away"])}'
            f'<ld pattern=""/>{_xml_text(score_or_time)}</td></tr>'
        )

    table = '<table class="resultados">' + "".join(grouped_rows) + "</table>"
    return _wrap_gameday_xml(table, output_format)


def parse_standings_text(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    teams = []
    index = 0

    while index < len(lines):
        if not re.fullmatch(r"\d+", lines[index]):
            index += 1
            continue

        rank = int(lines[index])
        name_index = index + 1
        if name_index < len(lines) and "logo" in lines[name_index].lower():
            name_index += 1
        stats_index = name_index + 1
        if stats_index >= len(lines):
            index += 1
            continue

        name = lines[name_index] if name_index < len(lines) else ""
        stats = lines[stats_index].split()
        if (
            name
            and len(stats) >= 6
            and re.fullmatch(r"\d+", stats[1])
            and re.fullmatch(r"\d+", stats[2])
        ):
            teams.append({
                "rank": rank,
                "name": name,
                "wins": stats[1],
                "losses": stats[2],
                "points_for": stats[4],
                "points_against": stats[5],
            })
            index = stats_index + 1
        else:
            index += 1

    return teams


def _fetch_euroleague_standings():
    """Obtiene la clasificación directamente de la API de Euroliga."""
    root = _fetch_feed(
        "standings",
        {"competitionCode": "E", "seasonCode": EUROLEAGUE_SEASON},
    )

    teams = []
    for item in _feed_items(root, "team"):
        name = _child_text(item, "name")
        if not name:
            continue
        try:
            rank = int(_child_text(item, "ranking", "0"))
        except ValueError:
            rank = 0

        # Usamos los nombres exactos que nos pasaste: ptsfavour y ptsagainst
        points_for = _child_text(item, "ptsfavour", "0")
        points_against = _child_text(item, "ptsagainst", "0")

        teams.append({
            "rank": rank,
            "name": _team_name(name),
            "wins": _child_text(item, "wins", "0"),
            "losses": _child_text(item, "losses", "0"),
            "points_for": points_for,
            "points_against": points_against,
        })

    if not teams:
        raise EuroleagueApiError("La API de Euroliga no devolvió equipos en la clasificación.")
    return teams


def _new_xml_id():
    return f"U{uuid4().hex[:13].upper()}"


def generate_standings_xml(text=None):
    """Genera el XML de clasificación. Si no se pasa texto, lo pilla de la API."""
    if text and text.strip():
        teams = parse_standings_text(text)
    else:
        teams = _fetch_euroleague_standings()

    if not teams:
        raise ValueError("No se encontraron equipos. Comprueba el formato de los datos pegados.")

    rows = []
    for team in teams:
        placement_class = (
            "circulo" if team["rank"] <= 8
            else "cuadrado" if team["rank"] <= 13
            else ""
        )
        class_attribute = f' class="{placement_class}"' if placement_class else ""
        rows.append(
            f'<tr id="{_new_xml_id()}"{class_attribute}>'
            f'<td id="{_new_xml_id()}">{_xml_text(team["name"])}</td>'
            f'<td id="{_new_xml_id()}">{_xml_text(team["wins"])}</td>'
            f'<td>{_xml_text(team["losses"])}</td>'
            f'<td id="{_new_xml_id()}">{_xml_text(team["points_for"])}</td>'
            f'<td>{_xml_text(team["points_against"])}</td></tr>'
        )

    today = datetime.now(timezone.utc).date().isoformat()
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<?EM-templateName /SysConfig/GODO/Templates/Base/story.xml?>\n'
        '<!DOCTYPE doc SYSTEM "/SysConfig/GODO/Rules/eidosint.dtd">\n'
        '<doc xml:lang="es"><story>'
        '<text sourceCIL="4.12.1882248657" '
        f'this="/GODO/MD/Importacion/Articulos-autolink/{today}/ELBC.xml">'
        '<content class="ACBX"><table class="clasificacion">'
        + "\n".join(rows)
        + "</table></content></text></story></doc>"
    )
