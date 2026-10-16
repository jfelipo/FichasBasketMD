"""ACB regular-season results, next-round and standings XML conversions."""

from datetime import datetime, timezone
from html import escape
import os
import re
import ssl
import time
from zoneinfo import ZoneInfo

import requests


API_URL = "https://api2.acb.com/api/matchdata/Menu/matchlist"
STANDINGS_API_URL = "https://api2.acb.com/api/seasondata/Competition/standings"
SYSTEM_CA_BUNDLE = ssl.get_default_verify_paths().cafile
MADRID_TIMEZONE = ZoneInfo("Europe/Madrid")

# The reference project anchors Jornada 19 to match ID 105537 for 2026-27.
BASE_GAMEDAY = 19
BASE_MATCH_ID = 105537
MATCHES_PER_GAMEDAY = 9
MAX_GAMEDAY = 34

# ----------------------------------------------------------------------------
# Constantes para auto-discovery de temporada/jornada.
#
# La API de ACB no expone documentación pública, así que estos valores actúan
# como semilla para el escaneo incremental y como último fallback.
#
# - DEFAULT_EDITION_ID  → temporada de referencia (se actualiza al cambiar de
#                         temporada si la auto-detección falla).
# - DEFAULT_ROUND_ID    → roundId de referencia conocido. El escaneo prueba
#                         roundId+1, roundId+2, ... hasta topar con uno sin
#                         datos; el último válido es la última jornada
#                         disponible.
# - ROUND_SCAN_LIMIT    → nº máximo de roundIds a probar hacia arriba en cada
#                         escaneo, para no saturar la API.
# - ROUND_CACHE_TTL     → segundos de validez del cache en memoria del último
#                         roundId descubierto (evita reescanear en cada llamada).
# ----------------------------------------------------------------------------
DEFAULT_EDITION_ID = "91"
DEFAULT_ROUND_ID = "6016"
ROUND_SCAN_LIMIT = 60
ROUND_CACHE_TTL = 3600  # 1 hora

# Endpoints probables para descubrir la temporada activa. La API de ACB no
# publica docs, así que probamos varios patrones y nos quedamos con el primero
# que responda algo útil.
SEASON_DISCOVERY_ENDPOINTS = (
    "https://api2.acb.com/api/seasondata/Competition/seasons",
    "https://api2.acb.com/api/seasondata/Menu/seasons",
    "https://api2.acb.com/api/matchdata/Menu/seasons",
    "https://api2.acb.com/api/seasondata/Competition/editions",
)

# Endpoints probables para listar las jornadas de una temporada.
ROUNDS_DISCOVERY_ENDPOINTS = (
    "https://api2.acb.com/api/seasondata/Competition/rounds",
    "https://api2.acb.com/api/matchdata/Menu/rounds",
    "https://api2.acb.com/api/seasondata/Competition/roundsList",
)

MONTH_NAMES = (
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
)
DAY_NAMES = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
SHORT_DAY_NAMES = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


class ACBApiError(RuntimeError):
    """Raised when the official ACB match feed cannot be retrieved or parsed."""


# Cache en memoria del último (editionId, roundId) resuelto automáticamente.
# Evita repetir el escaneo en cada llamada a la API.
_ROUND_CACHE = {
    "edition_id": None,
    "round_id": None,
    "timestamp": 0,
}


def _xml_text(value):
    return escape(str(value), quote=False)


def _parse_match_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(MADRID_TIMEZONE)


def _team_name(value):
    if isinstance(value, dict):
        value = value.get("fullName") or value.get("name") or ""
    return str(value or "").strip()


# ---------------------------------------------------------------------------
# Helpers de red para la API de ACB
# ---------------------------------------------------------------------------

def _acb_headers(api_key):
    """Cabeceras estándar para todas las llamadas a api2.acb.com."""
    return {
        "x-apikey": api_key,
        "origin": "https://live.acb.com",
        "referer": "https://live.acb.com/",
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }


def _acb_get(url, api_key, params=None, timeout=15):
    """GET a la API de ACB. Devuelve (status_code, json_or_None).

    Captura cualquier error de red o de parseo para que los callers puedan
    probar varios endpoints sin levantar excepciones.
    """
    try:
        response = requests.get(
            url,
            params=params or {},
            headers=_acb_headers(api_key),
            timeout=timeout,
            verify=SYSTEM_CA_BUNDLE or True,
        )
    except requests.RequestException:
        return None, None
    if response.status_code != 200:
        return response.status_code, None
    try:
        return 200, response.json()
    except ValueError:
        return 200, None


# ---------------------------------------------------------------------------
# Auto-discovery de temporada y última jornada disponible
# ---------------------------------------------------------------------------

def _discover_current_edition(api_key):
    """Descubre el editionId de la temporada activa consultando varios endpoints.

    Devuelve el ID como string, o None si ningún endpoint respondió algo útil.
    """
    for url in SEASON_DISCOVERY_ENDPOINTS:
        _, data = _acb_get(url, api_key, params={"competitionId": 1})
        if not data:
            continue

        # La respuesta puede ser una lista o un dict con alguna de estas claves.
        if isinstance(data, list):
            seasons = data
        elif isinstance(data, dict):
            seasons = (
                data.get("seasons")
                or data.get("editions")
                or data.get("items")
                or data.get("data")
                or []
            )
        else:
            seasons = []

        if not isinstance(seasons, list) or not seasons:
            continue

        # Criterio 1: temporada marcada como activa/actual.
        active = next(
            (
                s for s in seasons
                if isinstance(s, dict)
                and (s.get("active") or s.get("current") or s.get("isCurrent"))
            ),
            None,
        )
        # Criterio 2: si ninguno marca "activa", el de mayor id numérico.
        if active is None:
            try:
                active = max(
                    (
                        s for s in seasons
                        if isinstance(s, dict) and s.get("id") is not None
                    ),
                    key=lambda s: s.get("id", 0),
                    default=None,
                )
            except (TypeError, ValueError):
                active = None

        if isinstance(active, dict):
            eid = active.get("id") or active.get("editionId")
            if eid is not None:
                return str(eid)

    return None


def _discover_latest_round(api_key, edition_id):
    """Descubre el roundId más reciente listando las jornadas de la temporada.

    Devuelve el roundId como string, o None si no se pudo determinar.
    """
    for url in ROUNDS_DISCOVERY_ENDPOINTS:
        _, data = _acb_get(
            url, api_key,
            params={"competitionId": 1, "editionId": edition_id},
        )
        if not data:
            continue

        if isinstance(data, list):
            rounds = data
        elif isinstance(data, dict):
            rounds = (
                data.get("rounds")
                or data.get("roundsList")
                or data.get("items")
                or data.get("data")
                or []
            )
        else:
            rounds = []

        if not isinstance(rounds, list) or not rounds:
            continue

        def _round_key(r):
            if not isinstance(r, dict):
                return -1
            value = r.get("roundId") or r.get("id") or r.get("number") or 0
            try:
                return int(value)
            except (TypeError, ValueError):
                return -1

        last_round = max(rounds, key=_round_key)
        if isinstance(last_round, dict):
            rid = (
                last_round.get("roundId")
                or last_round.get("id")
                or last_round.get("number")
            )
            if rid is not None:
                return str(rid)

    return None


def _scan_latest_round(api_key, edition_id, start_round_id):
    """Escanea roundIds secuenciales hacia arriba hasta topar con uno sin datos.

    La API de ACB numera los roundIds de forma consecutiva dentro de cada
    temporada, así que partiendo del roundId de referencia conocido
    (DEFAULT_ROUND_ID) vamos probando roundId+1, roundId+2, ... y nos quedamos
    con el último que devuelva datos de clasificación válidos.

    Devuelve el último roundId válido como int, o None si ni siquiera el inicial
    funcionó.
    """
    try:
        start = int(start_round_id)
    except (TypeError, ValueError):
        return None

    last_valid = None
    for offset in range(0, ROUND_SCAN_LIMIT + 1):
        candidate = start + offset
        status, data = _acb_get(
            STANDINGS_API_URL,
            api_key,
            params={
                "competitionId": 1,
                "editionId": edition_id,
                "roundId": candidate,
            },
        )
        # 404/400 → ese roundId no existe → paramos el escaneo.
        if status and status != 200:
            break
        if not data:
            # Respuesta 200 pero sin JSON válido → tampoco nos sirve.
            break

        standings = data.get("standings") if isinstance(data, dict) else None
        if isinstance(standings, list) and standings:
            # roundId con datos reales → lo registramos y seguimos probando.
            last_valid = candidate
        # Si standings viene vacío (jornada futura ya publicada pero sin
        # jugar), no actualizamos last_valid pero seguimos escaneando, por
        # si hay más jornadas con datos detrás.

    return last_valid


def _resolve_standings_params(api_key):
    """Determina (editionId, roundId) para la clasificación más reciente.

    Orden de prioridad:
      1. Variables de entorno ACB_EDITION_ID y ACB_ROUND_ID (override manual).
         Útil para fijar la temporada a mano al cambiar de temporada, sin
         depender del auto-discovery.
      2. Cache en memoria (válido durante ROUND_CACHE_TTL segundos).
      3. Auto-discovery de la temporada + escaneo del último roundId con
         datos de clasificación.
      4. Constantes DEFAULT_EDITION_ID / DEFAULT_ROUND_ID como último recurso.

    Devuelve siempre una tupla (edition_id, round_id) de strings. Si solo se
    acaba resolviendo el fallback, se emite un warning por stderr (no se
    levanta excepción para que la app siga funcionando, aunque sea con datos
    antiguos).
    """
    # 1. Override manual vía entorno.
    env_edition = os.environ.get("ACB_EDITION_ID", "").strip()
    env_round = os.environ.get("ACB_ROUND_ID", "").strip()
    if env_edition and env_round:
        return env_edition, env_round

    # 2. Cache en memoria.
    now = time.time()
    cached = _ROUND_CACHE
    if (
        cached["edition_id"]
        and cached["round_id"]
        and now - cached["timestamp"] < ROUND_CACHE_TTL
    ):
        return cached["edition_id"], cached["round_id"]

    # 3. Auto-discovery.
    edition_id = env_edition or _discover_current_edition(api_key)
    if not edition_id:
        edition_id = DEFAULT_EDITION_ID
        print(
            "WARNING: no se pudo descubrir el editionId actual de ACB. "
            f"Usando valor por defecto ({DEFAULT_EDITION_ID}). "
            "Configura ACB_EDITION_ID en Render para fijarlo a mano."
        )

    round_id = env_round
    used_fallback_round = False
    if not round_id:
        # Primero intentamos listar las jornadas (más rápido, 1 sola petición).
        discovered_round = _discover_latest_round(api_key, edition_id)
        if discovered_round:
            round_id = discovered_round
        else:
            # Si no hay endpoint de listado, escaneamos roundIds secuenciales.
            scanned = _scan_latest_round(api_key, edition_id, DEFAULT_ROUND_ID)
            if scanned:
                round_id = str(scanned)
            else:
                round_id = DEFAULT_ROUND_ID
                used_fallback_round = True

    if used_fallback_round:
        print(
            f"WARNING: no se pudo descubrir el roundId actual de ACB. "
            f"Usando valor por defecto ({DEFAULT_ROUND_ID}). "
            "Configura ACB_ROUND_ID en Render para fijarlo a mano."
        )

    # 4. Actualizamos cache.
    _ROUND_CACHE.update(
        edition_id=edition_id,
        round_id=round_id,
        timestamp=now,
    )

    return edition_id, round_id


def _fetch_matchday(gameday):
    api_key = os.environ.get("ACB_API_KEY", "").strip()
    if not api_key:
        raise ACBApiError("Falta configurar el secreto ACB_API_KEY.")

    match_id = BASE_MATCH_ID + (gameday - BASE_GAMEDAY) * MATCHES_PER_GAMEDAY
    headers = _acb_headers(api_key)
    try:
        response = requests.get(
            API_URL,
            params={"matchId": match_id, "format": "week"},
            headers=headers,
            timeout=20,
            verify=SYSTEM_CA_BUNDLE or True,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise ACBApiError(
            f"No se pudo consultar el servicio de ACB para la jornada {gameday}."
        ) from error

    try:
        data = response.json()
    except ValueError as error:
        raise ACBApiError("El servicio de ACB devolvió una respuesta no válida.") from error

    matches = data if isinstance(data, list) else (
        data.get("matches", []) if isinstance(data, dict) else []
    )
    if not isinstance(matches, list) or not matches:
        raise ACBApiError(f"No se encontraron partidos para la jornada {gameday}.")

    games = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        home_team = _team_name(match.get("homeTeam"))
        away_team = _team_name(match.get("awayTeam"))
        if not home_team or not away_team:
            continue

        local_datetime = _parse_match_datetime(match.get("startDateTime"))
        status = str(match.get("matchStatus") or "").strip().upper()
        home_score = match.get("homeScore")
        away_score = match.get("awayScore")
        is_finished = (
            status in {"FINALIZED", "FINISHED", "COMPLETED"}
            and home_score is not None
            and away_score is not None
        )
        if is_finished:
            score_or_time = f"{home_score}-{away_score}"
        elif local_datetime:
            score_or_time = local_datetime.strftime("%H:%M")
        else:
            score_or_time = "Por definir"

        games.append({
            "date": local_datetime.date() if local_datetime else None,
            "datetime": local_datetime,
            "home": home_team,
            "away": away_team,
            "score_or_time": score_or_time,
            "finished": is_finished,
        })

    if not games:
        raise ACBApiError(f"El servicio de ACB no devolvió partidos válidos para la jornada {gameday}.")

    games.sort(
        key=lambda game: (
            game["datetime"] is None,
            game["datetime"] or datetime.max.replace(tzinfo=MADRID_TIMEZONE),
        )
    )
    return games


def _full_date(game_date):
    return (
        f"{DAY_NAMES[game_date.weekday()]}, {game_date.day} "
        f"{MONTH_NAMES[game_date.month - 1]}"
    )


def _short_date(game):
    if not game["datetime"]:
        return "Por definir"
    local_datetime = game["datetime"]
    return (
        f"{SHORT_DAY_NAMES[local_datetime.weekday()]}, "
        f"{local_datetime.day} {local_datetime.strftime('%H:%M')}h"
    )


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
    if (
        isinstance(gameday, bool)
        or not isinstance(gameday, int)
        or not 1 <= gameday <= MAX_GAMEDAY
    ):
        raise ValueError(f"La jornada debe ser un número entre 1 y {MAX_GAMEDAY}.")
    if output_format not in ("ELBR", "ELBP"):
        raise ValueError("Selecciona un formato válido: ELBR o ELBP.")

    games = _fetch_matchday(gameday)
    if output_format == "ELBP":
        rows = [
            f'<tr><td class="fecha">La próxima jornada ({gameday})</td></tr>'
        ]
        for game in games:
            rows.append(
                f'<tr><td>{_xml_text(game["home"])}-{_xml_text(game["away"])} '
                f'<ld pattern=""/>{_xml_text(_short_date(game))}</td></tr>'
            )
        table = '<table class="proxima_jornada">' + "".join(rows) + "</table>"
        return _wrap_gameday_xml(table, output_format)

    rows = []
    current_date = None
    for game in games:
        game_date = game["date"]
        date_label = _full_date(game_date) if game_date else "Fecha por definir"
        if date_label != current_date:
            current_date = date_label
            rows.append(
                f'<tr><td class="fecha">{_xml_text(date_label)}</td></tr>'
            )
        rows.append(
            f'<tr><td>{_xml_text(game["home"])}-{_xml_text(game["away"])}'
            f'<ld pattern=""/>{_xml_text(game["score_or_time"])}</td></tr>'
        )

    table = '<table class="resultados">' + "".join(rows) + "</table>"
    return _wrap_gameday_xml(table, output_format)


def _stat_integer(token):
    token = str(token).strip().replace("\u00a0", "")
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    if re.fullmatch(r"-?\d{1,3}(?:[.,]\d{3})+", token):
        return int(token.replace(".", "").replace(",", ""))
    return None


def _is_percentage(token):
    return bool(re.fullmatch(r"\d+(?:[.,]\d+)?%", str(token).strip()))


def _is_team_word(token):
    token = str(token).strip(".,'’/&()-")
    return bool(token) and any(char.isalpha() for char in token) and not any(
        char.isdigit() for char in token
    )


def _team_name_from_tokens(tokens):
    name_tokens = [
        token for token in tokens
        if token.strip(".,").lower() not in {"logo", "escudo"}
    ]
    midpoint = len(name_tokens) // 2
    if (
        len(name_tokens) >= 2
        and len(name_tokens) % 2 == 0
        and [token.casefold() for token in name_tokens[:midpoint]]
        == [token.casefold() for token in name_tokens[midpoint:]]
    ):
        name_tokens = name_tokens[:midpoint]
    return " ".join(name_tokens).strip()


def _standings_stats(tokens, start):
    values = tokens[start:start + 6]
    if len(values) != 6 or not _is_percentage(values[3]):
        return None

    played, wins, losses = (_stat_integer(value) for value in values[:3])
    points_for = _stat_integer(values[4])
    points_against = _stat_integer(values[5])
    if None in (played, wins, losses, points_for, points_against):
        return None
    if played < 0 or wins < 0 or losses < 0 or wins + losses != played:
        return None

    return {
        "wins": wins,
        "losses": losses,
        "points_for": points_for,
        "points_against": points_against,
    }


def parse_standings_text(text):
    """Parse the vertical or row-oriented plain text copied from ACB.com."""
    if not isinstance(text, str) or not text.strip():
        return []

    tokens = re.findall(r"\S+", text.replace("\ufeff", ""))
    teams = []
    index = 0
    while index < len(tokens):
        position = _stat_integer(tokens[index])
        if position is None or not 1 <= position <= MAX_GAMEDAY:
            index += 1
            continue

        parsed = None
        search_end = min(index + 28, len(tokens) - 5)
        for stats_start in range(index + 2, search_end + 1):
            name_tokens = tokens[index + 1:stats_start]
            if not name_tokens or not all(_is_team_word(token) for token in name_tokens):
                continue
            stats = _standings_stats(tokens, stats_start)
            if not stats:
                continue
            name = _team_name_from_tokens(name_tokens)
            if name:
                parsed = {
                    "position": position,
                    "name": name,
                    **stats,
                }
                index = stats_start + 6
                break

        if parsed:
            teams.append(parsed)
        else:
            index += 1

    return teams


def _fetch_acb_standings():
    """Obtiene la clasificación de la última jornada disponible desde la API de ACB.

    El editionId y roundId se resuelven automáticamente siguiendo la estrategia
    descrita en `_resolve_standings_params`:
      1. Variables de entorno ACB_EDITION_ID / ACB_ROUND_ID si están presentes.
      2. Auto-discovery + escaneo del último roundId con datos.
      3. Constantes por defecto como último recurso.
    """
    api_key = os.environ.get("ACB_API_KEY", "").strip()
    if not api_key:
        raise ACBApiError("Falta configurar el secreto ACB_API_KEY.")

    edition_id, round_id = _resolve_standings_params(api_key)

    try:
        response = requests.get(
            STANDINGS_API_URL,
            params={
                "competitionId": 1,
                "editionId": edition_id,
                "roundId": round_id,
            },
            headers=_acb_headers(api_key),
            timeout=20,
            verify=SYSTEM_CA_BUNDLE or True,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise ACBApiError(
            "No se pudo consultar el servicio de clasificación de ACB "
            f"(editionId={edition_id}, roundId={round_id})."
        ) from error

    try:
        data = response.json()
    except ValueError as error:
        raise ACBApiError(
            "El servicio de ACB devolvió una respuesta no válida para la clasificación."
        ) from error

    # 1. Diccionario de equipos: id → nombre legible.
    teams_list = data.get("teams", []) if isinstance(data, dict) else []
    team_names = {}
    for team_info in teams_list:
        if isinstance(team_info, dict):
            team_names[team_info.get("id")] = (
                team_info.get("fullName")
                or team_info.get("shortName")
                or ""
            )

    # 2. Tabla de clasificación.
    standings = data.get("standings", []) if isinstance(data, dict) else []
    if not standings:
        # Si la API no devuelve standings para el roundId resuelto, limpiamos
        # el cache para que la próxima llamada vuelva a escanear.
        _ROUND_CACHE.update(edition_id=None, round_id=None, timestamp=0)
        raise ACBApiError(
            "La API de ACB no devolvió datos de clasificación para "
            f"editionId={edition_id}, roundId={round_id}."
        )

    teams = []
    for item in standings:
        if not isinstance(item, dict):
            continue

        team_id = item.get("teamId")
        name = team_names.get(team_id, "Equipo Desconocido")

        teams.append({
            "position": item.get("position", 0),
            "name": str(name).strip(),
            "wins": _stat_integer(item.get("wins", 0)),
            # En la API de ACB, derrotas se llama "loses" (con una sola 's').
            "losses": _stat_integer(
                item.get("loses", item.get("losses", 0))
            ),
            "points_for": _stat_integer(item.get("pointsFor", 0)),
            "points_against": _stat_integer(item.get("pointsAgainst", 0)),
        })

    if not teams:
        raise ACBApiError(
            "No se pudieron extraer equipos de la respuesta de la API de ACB."
        )

    # Ordenamos por la posición por si la API nos los da desordenados.
    teams.sort(key=lambda x: x["position"])

    return teams


def generate_standings_xml(text=None):
    """Genera el XML de clasificación. Si no se pasa texto, lo pilla de la API."""
    if text and text.strip():
        teams = parse_standings_text(text)
    else:
        teams = _fetch_acb_standings()

    if not teams:
        raise ValueError(
            "No se encontraron equipos. Copia la tabla de ACB.com como texto e inténtalo de nuevo."
        )

    now = datetime.now(timezone.utc)
    date_str = now.date().isoformat()
    source_id = int(now.timestamp())
    rows = []
    for team in teams:
        rows.append(
            "<tr>"
            f'<td>{_xml_text(team["name"])}</td>'
            f'<td>{team["wins"]}</td>'
            f'<td>{team["losses"]}</td>'
            f'<td>{team["points_for"]}</td>'
            f'<td>{team["points_against"]}</td>'
            "</tr>"
        )

    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<?EM-templateName /SysConfig/GODO/Templates/Base/story.xml?>\n'
        '<!DOCTYPE doc\n'
        '  SYSTEM "/SysConfig/GODO/Rules/eidosint.dtd">\n'
        f'<doc xml:lang="es"><story><text sourceCIL="4.12.{source_id}" '
        f'this="/GODO/MD/Baloncesto/Articulos/{date_str}/ACB-0001.xml">'
        '<content class="ACBX"><table class="clasificacion">'
        + "".join(rows)
        + "</table></content></text></story></doc>"
    )
