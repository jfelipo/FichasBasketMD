from flask import Flask, render_template, request, send_file, jsonify
import os
import requests
import ssl
import xml.etree.ElementTree as ET
from xml.dom import minidom
import io

from euroleague_modules import (
    EuroleagueApiError,
    generate_gameday_xml,
    generate_standings_xml,
)
from acb_modules import (
    ACBApiError,
    generate_gameday_xml as generate_acb_gameday_xml,
    generate_standings_xml as generate_acb_standings_xml,
)

app = Flask(__name__)

ACB_API_URL = "https://api2.acb.com/api/matchdata/Result/boxscores"
SYSTEM_CA_BUNDLE = ssl.get_default_verify_paths().cafile


# --- Funciones de ayuda ---
def extraer_apellido(nombre_completo):
    if ',' in nombre_completo:
        return nombre_completo.split(',')[0].strip().title()
    return nombre_completo.title()


def convertir_minutos_a_formato_simple(minutos_str):
    if isinstance(minutos_str, str) and ':' in minutos_str:
        return minutos_str.split(':')[0]
    return "0"


def ajustar_minutos_totales(total_minutos):
    milestones = [200, 225, 250, 275]
    closest_milestone = min(milestones, key=lambda x: abs(x - total_minutos))
    if abs(total_minutos - closest_milestone) <= 12:
        return closest_milestone
    return total_minutos


# --- FUNCIÓN DE SCRAPING (CORREGIDA) ---
def scrape_euroleague_stats(url):
    headers = {
        'User-Agent':
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        if "live.euroleague.net/api/boxscore" in url:
            api_url = url
        else:
            parts = url.strip('/').split('/')
            game_code = parts[-1].split('#')[0]
            season_code = parts[-2]
            api_url = f"https://live.euroleague.net/api/boxscore?gamecode={game_code}&seasoncode={season_code}"

        response = requests.get(
            api_url,
            headers=headers,
            timeout=10,
            verify=SYSTEM_CA_BUNDLE or True,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return None, {
            'error_message':
            f'No se pudo obtener o procesar los datos de la API: {e}'
        }

    teams_data = []
    info_adicional = {}
    info_adicional['arbitros'] = data.get('Referees', '').title()

    quarters = data.get('ByQuarter', [])
    if len(quarters) == 2:
        parciales_list = [
            f"{q1}-{q2}" for q1, q2 in zip([
                quarters[0].get('Quarter1', 0), quarters[0].get('Quarter2', 0),
                quarters[0].get('Quarter3', 0), quarters[0].get('Quarter4', 0)
            ], [
                quarters[1].get('Quarter1', 0), quarters[1].get('Quarter2', 0),
                quarters[1].get('Quarter3', 0), quarters[1].get('Quarter4', 0)
            ])
        ]
        info_adicional['parciales'] = ", ".join(parciales_list)
    else:
        info_adicional['parciales'] = ''

    for team_stats in data.get('Stats', []):
        players = []
        for player_stat in team_stats.get('PlayersStats', []):
            if player_stat.get(
                    'Minutes') == 'DNP' or not player_stat.get('Minutes'):
                continue

            # --- INICIO DE LA CORRECCIÓN ---
            # Convertimos los minutos a entero (int) aquí para evitar el TypeError
            player_data = {
                'dorsal':
                player_stat.get('Dorsal', ''),
                'nombre':
                extraer_apellido(player_stat.get('Player', '')),
                'titular':
                bool(player_stat.get('IsStarter', 0)),
                'minutos':
                int(
                    convertir_minutos_a_formato_simple(
                        player_stat.get('Minutes'))),
                'puntos':
                player_stat.get('Points', 0),
                't2_made':
                player_stat.get('FieldGoalsMade2', 0),
                't2_attempted':
                player_stat.get('FieldGoalsAttempted2', 0),
                't3_made':
                player_stat.get('FieldGoalsMade3', 0),
                't3_attempted':
                player_stat.get('FieldGoalsAttempted3', 0),
                'tl_made':
                player_stat.get('FreeThrowsMade', 0),
                'tl_attempted':
                player_stat.get('FreeThrowsAttempted', 0),
                'rebotes':
                player_stat.get('TotalRebounds', 0),
                'asistencias':
                player_stat.get('Assistances', 0),
                'valoracion':
                player_stat.get('Valuation', 0),
            }
            # --- FIN DE LA CORRECCIÓN ---
            players.append(player_data)

        team_info = {
            'nombre': team_stats.get('Team', 'Equipo Desconocido').title(),
            'puntuacion': str(team_stats.get('totr', {}).get('Points', 0)),
            'jugadores': players,
            'entrenador': team_stats.get('Coach', 'N/A').title(),
            'api_totals': team_stats.get('totr', {})
        }
        teams_data.append(team_info)

    return teams_data, info_adicional


# --- FUNCIÓN DE CREACIÓN DE XML ---
def create_xml(teams_data, info_adicional):
    doc = ET.Element('doc')
    doc.set('xml:lang', 'es')

    story = ET.SubElement(doc, 'story')
    text = ET.SubElement(story, 'text')
    content = ET.SubElement(text, 'content')

    for i, team in enumerate(teams_data):
        table = ET.SubElement(content, 'table')
        table.set('class', 'fichabas_auto')
        header_row = ET.SubElement(table, 'tr')
        header_cell = ET.SubElement(header_row, 'td')
        header_cell.set('class', 'cabecera')
        header_cell.set('colspan', '11')
        header_cell.text = f"{team['nombre']}, {team['puntuacion']}"

        titles_row = ET.SubElement(table, 'tr')
        titles_row.set('class', 'valores titulos')
        title_headers = [
            '', 'Jugador', 'PTS', '2P', '3P', 'TL', 'RT', 'AS', 'MJ', 'V', ''
        ]
        for title in title_headers:
            ET.SubElement(titles_row, 'td').text = title if title else None

        jugadores_con_relleno = list(team['jugadores'])
        while len(jugadores_con_relleno) < 12:
            jugadores_con_relleno.append(None)

        for player in jugadores_con_relleno:
            player_row = ET.SubElement(table, 'tr')
            player_row.set('class', 'valores')
            ET.SubElement(player_row, 'td')
            if player is None:
                for _ in range(10):
                    ET.SubElement(player_row, 'td')
            else:
                nombre_cell = ET.SubElement(player_row, 'td')
                if player.get('titular', False):
                    nombre_cell.set('class', 'negrita')
                nombre_cell.text = player['nombre']
                ET.SubElement(player_row, 'td').text = str(player['puntos'])
                ET.SubElement(
                    player_row, 'td'
                ).text = f"{player['t2_made']}-{player['t2_attempted']}"
                ET.SubElement(
                    player_row, 'td'
                ).text = f"{player['t3_made']}-{player['t3_attempted']}"
                ET.SubElement(
                    player_row, 'td'
                ).text = f"{player['tl_made']}-{player['tl_attempted']}"
                ET.SubElement(player_row, 'td').text = str(player['rebotes'])
                ET.SubElement(player_row,
                              'td').text = str(player['asistencias'])
                ET.SubElement(player_row, 'td').text = str(player['minutos'])
                ET.SubElement(player_row,
                              'td').text = str(player['valoracion'])
                ET.SubElement(player_row, 'td')

        totales_row = ET.SubElement(table, 'tr')
        totales_row.set('class', 'totales')
        api_totals = team.get('api_totals', {})
        ET.SubElement(totales_row, 'td')
        ET.SubElement(totales_row, 'td').text = 'Totales'
        ET.SubElement(totales_row,
                      'td').text = str(api_totals.get('Points', 0))
        ET.SubElement(
            totales_row, 'td'
        ).text = f"{api_totals.get('FieldGoalsMade2', 0)}-{api_totals.get('FieldGoalsAttempted2', 0)}"
        ET.SubElement(
            totales_row, 'td'
        ).text = f"{api_totals.get('FieldGoalsMade3', 0)}-{api_totals.get('FieldGoalsAttempted3', 0)}"
        ET.SubElement(
            totales_row, 'td'
        ).text = f"{api_totals.get('FreeThrowsMade', 0)}-{api_totals.get('FreeThrowsAttempted', 0)}"
        ET.SubElement(totales_row,
                      'td').text = str(api_totals.get('TotalRebounds', 0))
        ET.SubElement(totales_row,
                      'td').text = str(api_totals.get('Assistances', 0))

        total_minutos_calculados = sum(
            p.get('minutos', 0) for p in team['jugadores'])
        minutos_ajustados = ajustar_minutos_totales(total_minutos_calculados)
        ET.SubElement(totales_row, 'td').text = str(minutos_ajustados)

        ET.SubElement(totales_row,
                      'td').text = str(api_totals.get('Valuation', 0))
        ET.SubElement(totales_row, 'td')

        entrenador_row = ET.SubElement(table, 'tr')
        entrenador_row.set('class', 'margenesfilete')
        ET.SubElement(entrenador_row, 'td')
        entr_label = ET.SubElement(entrenador_row, 'td')
        entr_label.set('class', 'negrita')
        entr_label.text = 'Entrenador:'
        entr_value = ET.SubElement(entrenador_row, 'td')
        entr_value.set('class', 'left')
        entr_value.set('colspan', '8')
        entr_value.text = f"\u2002{team.get('entrenador', '')}"
        ET.SubElement(entrenador_row, 'td')

        if i == len(teams_data) - 1:
            parciales_row = ET.SubElement(table, 'tr')
            parciales_row.set('class', 'margenesfilete')
            ET.SubElement(parciales_row, 'td')
            parciales_cell = ET.SubElement(parciales_row, 'td')
            parciales_cell.set('class', 'left')
            parciales_cell.set('colspan', '9')
            parciales_span = ET.SubElement(parciales_cell, 'span')
            parciales_span.set('class', 'negrita')
            parciales_span.text = 'Parciales: '
            parciales_span.tail = info_adicional.get('parciales', '')
            ET.SubElement(parciales_row, 'td')

            arbitros_row = ET.SubElement(table, 'tr')
            arbitros_row.set('class', 'margenesfilete')
            ET.SubElement(arbitros_row, 'td')
            arbitros_cell = ET.SubElement(arbitros_row, 'td')
            arbitros_cell.set('class', 'left')
            arbitros_cell.set('colspan', '9')
            arbitros_span = ET.SubElement(arbitros_cell, 'span')
            arbitros_span.set('class', 'negrita')
            arbitros_span.text = 'Árbitros: '
            arbitros_span.tail = info_adicional.get('arbitros', '')
            ET.SubElement(arbitros_row, 'td')

            cabecera_row = ET.SubElement(table, 'tr')
            cabecera_cell = ET.SubElement(cabecera_row, 'td')
            cabecera_cell.set('class', 'rojo')
            cabecera_cell.set('colspan', '11')
        else:
            blank_row = ET.SubElement(table, 'tr')
            blank_cell = ET.SubElement(blank_row, 'td')
            blank_cell.set('class', 'blanco')
            blank_cell.set('colspan', '11')

    xml_string = ET.tostring(doc, 'unicode')
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent="  ")

    lines = [line for line in pretty_xml.split('\n') if line.strip()]
    final_xml = "\n".join(lines)
    return final_xml.encode('utf-8')


def _acb_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _acb_minutes(value):
    minutes_str = str(value or '00:00')
    if ':' not in minutes_str:
        return minutes_str
    parts = minutes_str.split(':')
    minutes = _acb_int(parts[0])
    seconds = _acb_int(parts[1]) if len(parts) > 1 else 0
    rounded = round(minutes + seconds / 60)
    if rounded == 0 and seconds > 0:
        rounded = 1
    return str(rounded)


def _acb_player_name(value):
    name = str(value or '').strip()
    return name.split('. ', 1)[1] if '. ' in name else name


def fetch_acb_match_data(match_id):
    api_key = os.environ.get('ACB_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('Falta configurar el secreto ACB_API_KEY.')

    response = requests.get(
        ACB_API_URL,
        params={'matchId': match_id},
        headers={
            'x-apikey': api_key,
            'origin': 'https://live.acb.com',
            'referer': 'https://live.acb.com/',
            'User-Agent': 'Mozilla/5.0',
        },
        timeout=20,
        verify=SYSTEM_CA_BUNDLE or True,
    )
    response.raise_for_status()
    return response.json()


def parse_acb_api_data(data):
    teams_data = []
    for team_box in data.get('teamBoxscores') or []:
        team_info = team_box.get('team') or {}
        periods = team_box.get('statsByPeriods') or []
        total_period = next(
            (period for period in periods if _acb_int(period.get('quarter')) == 0),
            None,
        )
        if not total_period:
            continue

        stats = total_period.get('stats') or {}
        total_stats = stats.get('total') or {}
        team_stats = stats.get('team') or {}
        players_raw = stats.get('players') or []
        ordered_players = (
            [player for player in players_raw if player.get('isStarted')]
            + [player for player in players_raw if not player.get('isStarted')]
        )

        players = []
        for player in ordered_players:
            play_time = str(player.get('playTime') or '00:00')
            if play_time in ('00:00', '0:00'):
                continue
            player_info = player.get('player') or {}
            players.append({
                'nombre': _acb_player_name(
                    player_info.get('firstInitialAndLastName')
                ),
                'minutos': _acb_minutes(play_time),
                'puntos': _acb_int(player.get('points')),
                't2_enc': _acb_int(player.get('twoPointersMade')),
                't2_int': _acb_int(player.get('twoPointersAttempted')),
                't3_enc': _acb_int(player.get('threePointersMade')),
                't3_int': _acb_int(player.get('threePointersAttempted')),
                'tl_enc': _acb_int(player.get('freeThrowsMade')),
                'tl_int': _acb_int(player.get('freeThrowsAttempted')),
                'rebotes': _acb_int(player.get('totalRebounds')),
                'asistencias': _acb_int(player.get('assists')),
                'valoracion': _acb_int(player.get('rating')),
                'titular': bool(player.get('isStarted')),
            })

        teams_data.append({
            'nombre': str(team_info.get('fullName') or 'Equipo'),
            'puntuacion': str(_acb_int(total_stats.get('points'))),
            'jugadores': players,
            'entrenador': str(team_box.get('headCoach') or ''),
            'periods': periods,
            'team_rebotes_extra': _acb_int(team_stats.get('totalRebounds')),
            'team_valoracion_extra': _acb_int(team_stats.get('rating')),
            'num_ot': sum(
                1 for period in periods if _acb_int(period.get('quarter')) > 4
            ),
        })

    parciales = []
    if len(teams_data) == 2:
        team_period_points = []
        for team in teams_data:
            points_by_period = {}
            for period in team['periods']:
                quarter = _acb_int(period.get('quarter'))
                period_stats = period.get('stats') or {}
                period_total = period_stats.get('total') or {}
                points_by_period[quarter] = _acb_int(period_total.get('points'))
            team_period_points.append(points_by_period)

        played_periods = sorted(
            quarter for quarter in team_period_points[0]
            if quarter > 0 and quarter in team_period_points[1]
        )
        parciales = [
            f"{team_period_points[0][quarter]}-{team_period_points[1][quarter]}"
            for quarter in played_periods
        ]

    referees = data.get('referees') or []
    if isinstance(referees, str):
        referees = [referees]
    referee_names = [
        str(referee.get('name') or referee.get('fullName') or '')
        if isinstance(referee, dict) else str(referee)
        for referee in referees
    ]
    info_adicional = {
        'parciales': ' '.join(parciales),
        'arbitros': ', '.join(name for name in referee_names if name),
    }
    return teams_data, info_adicional


def _acb_td_value(parent, value, show_zero=False):
    cell = ET.SubElement(parent, 'td')
    if value is not None and (show_zero or str(value) not in ('', '0')):
        cell.text = str(value)
    return cell


def _acb_td_shots(parent, made, attempted):
    cell = ET.SubElement(parent, 'td')
    if made or attempted:
        cell.text = f'{made}-{attempted}'
    return cell


def create_acb_xml(teams_data, info_adicional):
    doc = ET.Element('doc')
    doc.set('xml:lang', 'es')
    story = ET.SubElement(doc, 'story')
    text = ET.SubElement(story, 'text')
    content = ET.SubElement(text, 'content')

    for team_index, team in enumerate(teams_data):
        table = ET.SubElement(content, 'table', {'class': 'fichabas_auto'})
        header_row = ET.SubElement(table, 'tr')
        header_cell = ET.SubElement(header_row, 'td', {
            'colspan': '11',
            'class': 'cabecera',
        })
        header_cell.text = f"{team['nombre']}, {team['puntuacion']}"

        titles_row = ET.SubElement(table, 'tr', {'class': 'valores titulos'})
        for title in ('', 'Jugador', 'PTS', '2P', '3P', 'TL', 'RT', 'AS', 'MJ', 'V', ''):
            cell = ET.SubElement(titles_row, 'td')
            cell.text = title or None

        totals = {
            'points': 0, 't2_made': 0, 't2_attempted': 0,
            't3_made': 0, 't3_attempted': 0,
            'ft_made': 0, 'ft_attempted': 0,
            'rebounds': 0, 'assists': 0, 'rating': 0,
        }
        padded_players = list(team['jugadores'])
        padded_players.extend([None] * max(0, 12 - len(padded_players)))

        for player in padded_players:
            row = ET.SubElement(table, 'tr', {'class': 'valores'})
            if player is None:
                for _ in range(11):
                    ET.SubElement(row, 'td')
                continue

            ET.SubElement(row, 'td')
            name_cell = ET.SubElement(row, 'td')
            if player.get('titular'):
                name_span = ET.SubElement(name_cell, 'span', {'class': 'negrita jug'})
                name_span.text = player['nombre']
            else:
                name_cell.text = player['nombre']

            _acb_td_value(row, player['puntos'])
            _acb_td_shots(row, player['t2_enc'], player['t2_int'])
            _acb_td_shots(row, player['t3_enc'], player['t3_int'])
            _acb_td_shots(row, player['tl_enc'], player['tl_int'])
            _acb_td_value(row, player['rebotes'])
            _acb_td_value(row, player['asistencias'])
            _acb_td_value(row, player['minutos'], show_zero=True)
            _acb_td_value(row, player['valoracion'], show_zero=True)
            ET.SubElement(row, 'td')

            totals['points'] += player['puntos']
            totals['t2_made'] += player['t2_enc']
            totals['t2_attempted'] += player['t2_int']
            totals['t3_made'] += player['t3_enc']
            totals['t3_attempted'] += player['t3_int']
            totals['ft_made'] += player['tl_enc']
            totals['ft_attempted'] += player['tl_int']
            totals['rebounds'] += player['rebotes']
            totals['assists'] += player['asistencias']
            totals['rating'] += player['valoracion']

        totals_row = ET.SubElement(table, 'tr', {'class': 'totales'})
        ET.SubElement(totals_row, 'td')
        ET.SubElement(totals_row, 'td').text = 'Totales'
        ET.SubElement(totals_row, 'td').text = str(totals['points'])
        _acb_td_shots(totals_row, totals['t2_made'], totals['t2_attempted'])
        _acb_td_shots(totals_row, totals['t3_made'], totals['t3_attempted'])
        _acb_td_shots(totals_row, totals['ft_made'], totals['ft_attempted'])
        rebounds = totals['rebounds'] + team['team_rebotes_extra']
        rating = totals['rating'] + team['team_valoracion_extra']
        _acb_td_value(totals_row, rebounds, show_zero=rebounds > 0)
        _acb_td_value(totals_row, totals['assists'])
        _acb_td_value(totals_row, 200 + team['num_ot'] * 25, show_zero=True)
        _acb_td_value(totals_row, rating, show_zero=True)
        ET.SubElement(totals_row, 'td')

        coach_row = ET.SubElement(table, 'tr', {'class': 'margenesfilete'})
        ET.SubElement(coach_row, 'td')
        coach_label = ET.SubElement(coach_row, 'td', {'class': 'negrita'})
        coach_label.text = 'Entrenador:'
        coach_name = ET.SubElement(coach_row, 'td', {'class': 'left', 'colspan': '8'})
        coach_name.text = f"\u2002{team['entrenador']}"
        ET.SubElement(coach_row, 'td')

        if team_index == len(teams_data) - 1:
            for label, value in (
                ('Parciales: ', info_adicional.get('parciales', '')),
                ('Árbitros: ', info_adicional.get('arbitros', '')),
            ):
                info_row = ET.SubElement(table, 'tr', {'class': 'margenesfilete'})
                ET.SubElement(info_row, 'td')
                info_cell = ET.SubElement(info_row, 'td', {
                    'class': 'left',
                    'colspan': '9',
                })
                info_label = ET.SubElement(info_cell, 'span', {'class': 'negrita'})
                info_label.text = label
                info_label.tail = value
                ET.SubElement(info_row, 'td')

            separator_row = ET.SubElement(table, 'tr')
            ET.SubElement(separator_row, 'td', {'class': 'rojo', 'colspan': '11'})
        else:
            blank_row = ET.SubElement(table, 'tr')
            ET.SubElement(blank_row, 'td', {'class': 'blanco', 'colspan': '11'})

    xml_bytes = ET.tostring(doc, encoding='utf-8', method='xml')
    return minidom.parseString(xml_bytes).toprettyxml(indent='\t', encoding='utf-8')


def generate_match_xml(payload):
    league = payload.get('league', 'euroleague')

    if league == 'acb':
        match_id = str(payload.get('matchId', '')).strip()
        if not match_id:
            return None, None, 'Introduce el número de partido de Liga Endesa.'
        if not match_id.isdigit():
            return None, None, 'El número de partido debe contener solo cifras.'

        try:
            api_data = fetch_acb_match_data(match_id)
            teams_data, info = parse_acb_api_data(api_data)
            if not teams_data:
                return None, None, 'No se encontraron datos para ese partido.'
            xml_content = create_acb_xml(teams_data, info)
        except RuntimeError as e:
            return None, None, str(e)
        except requests.RequestException as e:
            return None, None, f'Error al consultar la API de ACB: {e}'
        except (ValueError, TypeError, KeyError) as e:
            return None, None, f'No se pudieron procesar los datos de ACB: {e}'

        return xml_content, f'estadisticas_acb_{match_id}.xml', None

    if league != 'euroleague':
        return None, None, 'Competición no válida.'

    url = str(payload.get('url', '')).strip()
    if not url:
        return None, None, 'Introduce la URL del partido de Euroliga.'

    teams_data, info = scrape_euroleague_stats(url)
    if not teams_data:
        error_msg = (info or {}).get(
            'error_message', 'No se pudieron extraer los datos del partido.'
        )
        return None, None, error_msg

    return create_xml(teams_data, info), 'estadisticas_euroliga.xml', None


@app.route('/convert_euroleague_gameday', methods=['POST'])
def convert_euroleague_gameday():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({'error': 'La solicitud no contiene datos válidos.'}), 400

    raw_gameday = payload.get('gameday')
    if isinstance(raw_gameday, bool):
        return jsonify({'error': 'La jornada debe ser un número entre 1 y 38.'}), 400
    if isinstance(raw_gameday, int):
        gameday = raw_gameday
    elif isinstance(raw_gameday, str) and raw_gameday.strip().isdigit():
        gameday = int(raw_gameday.strip())
    else:
        return jsonify({'error': 'La jornada debe ser un número entre 1 y 38.'}), 400

    output_format = str(payload.get('format', 'ELBR')).strip().upper()
    try:
        xml_content = generate_gameday_xml(gameday, output_format)
        return jsonify({
            'success': True,
            'xml_content': xml_content,
            'filename': f'{output_format}.xml',
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except EuroleagueApiError as e:
        print(f'Error de API de Euroliga: {e}')
        return jsonify({'error': str(e)}), 502
    except Exception as e:
        print(f'ERROR en /convert_euroleague_gameday: {type(e).__name__}: {e}')
        return jsonify({'error': 'No se pudo generar el XML de la jornada.'}), 500


@app.route('/convert_euroleague_standings', methods=['POST'])
def convert_euroleague_standings():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({'error': 'La solicitud no contiene datos válidos.'}), 400

    try:
        xml_content = generate_standings_xml(payload.get('text', ''))
        return jsonify({
            'success': True,
            'xml_content': xml_content,
            'filename': 'ELBC.xml',
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        print(f'ERROR en /convert_euroleague_standings: {type(e).__name__}: {e}')
        return jsonify({'error': 'No se pudo convertir la clasificación.'}), 500


@app.route('/convert_acb_gameday', methods=['POST'])
def convert_acb_gameday():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({'error': 'La solicitud no contiene datos válidos.'}), 400

    raw_gameday = payload.get('gameday')
    if isinstance(raw_gameday, bool):
        return jsonify({'error': 'La jornada debe ser un número entre 1 y 34.'}), 400
    if isinstance(raw_gameday, int):
        gameday = raw_gameday
    elif isinstance(raw_gameday, str) and raw_gameday.strip().isdigit():
        gameday = int(raw_gameday.strip())
    else:
        return jsonify({'error': 'La jornada debe ser un número entre 1 y 34.'}), 400

    output_format = str(payload.get('format', 'ELBR')).strip().upper()
    try:
        xml_content = generate_acb_gameday_xml(gameday, output_format)
        return jsonify({
            'success': True,
            'xml_content': xml_content,
            'filename': f'{output_format}.xml',
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except ACBApiError as e:
        print(f'Error de API de ACB: {e}')
        return jsonify({'error': str(e)}), 502
    except Exception as e:
        print(f'ERROR en /convert_acb_gameday: {type(e).__name__}: {e}')
        return jsonify({'error': 'No se pudo generar el XML de la jornada ACB.'}), 500


@app.route('/convert_acb_standings', methods=['POST'])
def convert_acb_standings():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({'error': 'La solicitud no contiene datos válidos.'}), 400

    try:
        xml_content = generate_acb_standings_xml(payload.get('text', ''))
        return jsonify({
            'success': True,
            'xml_content': xml_content,
            'filename': 'ACB-0001.xml',
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        print(f'ERROR en /convert_acb_standings: {type(e).__name__}: {e}')
        return jsonify({'error': 'No se pudo convertir la clasificación de ACB.'}), 500


# --- Rutas de la App Flask (Sin cambios) ---
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate_xml_content', methods=['POST'])
def generate_xml_content():
    try:
        payload = request.get_json(silent=True) or {}
        xml_content, _, error = generate_match_xml(payload)
        if error:
            valid_acb_id = str(payload.get('matchId', '')).strip().isdigit()
            status_code = (
                502 if payload.get('league') == 'acb' and valid_acb_id else 400
            )
            return jsonify({'error': error}), status_code
        return jsonify({'success': True, 'xml_content': xml_content.decode('utf-8')})
    except Exception as e:
        print(f"ERROR en /generate_xml_content: {type(e).__name__}: {e}")
        return jsonify({'error':
                        f'Error inesperado en el servidor: {str(e)}'}), 500


@app.route('/download', methods=['POST'])
def download():
    try:
        payload = request.get_json(silent=True) or {}
        xml_content, filename, error = generate_match_xml(payload)
        if error:
            valid_acb_id = str(payload.get('matchId', '')).strip().isdigit()
            status_code = (
                502 if payload.get('league') == 'acb' and valid_acb_id else 400
            )
            return jsonify({'error': error}), status_code
        return send_file(io.BytesIO(xml_content),
                         mimetype='application/xml',
                         as_attachment=True,
                         download_name=filename)
    except Exception as e:
        print(f"ERROR en /download: {type(e).__name__}: {e}")
        return jsonify({'error': f'Error al generar el XML: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
