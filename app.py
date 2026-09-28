from flask import Flask, render_template, request, send_file, jsonify
import requests
import ssl
import xml.etree.ElementTree as ET
from xml.dom import minidom
import io

app = Flask(__name__)

ACB_GENERATOR_URL = "https://acb-fichas-2--jfelipo.replit.app/generate"
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


def generate_match_xml(payload):
    league = payload.get('league', 'euroleague')

    if league == 'acb':
        match_id = str(payload.get('matchId', '')).strip()
        if not match_id:
            return None, None, 'Introduce el número de partido de Liga Endesa.'
        if not match_id.isdigit():
            return None, None, 'El número de partido debe contener solo cifras.'

        try:
            response = requests.post(
                ACB_GENERATOR_URL,
                json={'matchId': match_id},
                headers={'User-Agent': 'BasketballStatsXML/1.0'},
                timeout=45,
                verify=SYSTEM_CA_BUNDLE or True,
            )
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as e:
            return None, None, f'No se pudo consultar el generador de ACB: {e}'
        except ValueError:
            return None, None, 'El generador de ACB devolvió una respuesta no válida.'

        xml_content = result.get('xml')
        if not result.get('success') or not xml_content:
            return (
                None,
                None,
                result.get('error', 'No se encontraron estadísticas para ese partido.'),
            )
        return xml_content.encode('utf-8'), f'estadisticas_acb_{match_id}.xml', None

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
