from flask import Flask, render_template, request, jsonify
import xml.etree.ElementTree as ET
from xml.dom import minidom
import urllib.request
import json

app = Flask(__name__)

ACB_HEADERS = {
    'x-apikey': '0dd94928-6f57-4c08-a3bd-b1b2f092976e',
    'origin': 'https://live.acb.com',
    'referer': 'https://live.acb.com/',
}


def convertir_tiros_formato(enc, intentos):
    if enc == 0 and intentos == 0:
        return ''
    return f"{enc}-{intentos}"


def convertir_minutos(minutos_str):
    if ':' in minutos_str:
        parts = minutos_str.split(':')
        mins = int(parts[0])
        secs = int(parts[1]) if len(parts) > 1 else 0
        result = round(mins + secs / 60)
        if result == 0 and secs > 0:
            result = 1
        return str(result)
    return minutos_str


def extraer_apellido(first_initial_and_last):
    if '. ' in first_initial_and_last:
        return first_initial_and_last.split('. ', 1)[1]
    return first_initial_and_last


def fetch_match_data(match_id):
    url = f'https://api2.acb.com/api/matchdata/Result/boxscores?matchId={match_id}'
    req = urllib.request.Request(url)
    for k, v in ACB_HEADERS.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def parse_api_data(data):
    teams_data = []

    for team_box in data.get('teamBoxscores', []):
        team_info = team_box.get('team', {})
        team_name = team_info.get('fullName', '')

        head_coach = team_box.get('headCoach', '')

        periods = team_box.get('statsByPeriods', [])

        total_period = next((p for p in periods if p['quarter'] == 0), None)
        if total_period is None:
            continue

        team_points = total_period['stats']['total']['points']
        team_stats = total_period['stats'].get('team', {})
        team_rebotes_extra = team_stats.get('totalRebounds', 0)
        team_valoracion_extra = team_stats.get('rating', 0)

        num_ot = sum(1 for p in periods if p['quarter'] > 4)

        players_raw = total_period['stats']['players']

        starters = [p for p in players_raw if p.get('isStarted')]
        bench = [p for p in players_raw if not p.get('isStarted')]
        ordered_players = starters + bench

        players = []
        for p in ordered_players:
            play_time = p.get('playTime', '00:00')
            if play_time == '00:00' or play_time == '0:00':
                continue

            player_info = p.get('player', {})
            nombre = extraer_apellido(player_info.get('firstInitialAndLastName', ''))
            dorsal = player_info.get('shirtNumber', '')

            minutos = convertir_minutos(play_time)
            puntos = p.get('points', 0)
            t2_enc = p.get('twoPointersMade', 0)
            t2_int = p.get('twoPointersAttempted', 0)
            t3_enc = p.get('threePointersMade', 0)
            t3_int = p.get('threePointersAttempted', 0)
            tl_enc = p.get('freeThrowsMade', 0)
            tl_int = p.get('freeThrowsAttempted', 0)
            rebotes = p.get('totalRebounds', 0)
            asistencias = p.get('assists', 0)
            valoracion = p.get('rating', 0)
            titular = p.get('isStarted', False)

            players.append({
                'dorsal': dorsal,
                'nombre': nombre,
                'minutos': minutos,
                'puntos': str(puntos),
                't2_enc': t2_enc, 't2_int': t2_int,
                't3_enc': t3_enc, 't3_int': t3_int,
                'tl_enc': tl_enc, 'tl_int': tl_int,
                'rebotes': str(rebotes),
                'asistencias': str(asistencias),
                'valoracion': str(valoracion),
                'titular': titular,
            })

        teams_data.append({
            'nombre': team_name,
            'puntuacion': str(team_points),
            'jugadores': players,
            'entrenador': head_coach,
            'periods': periods,
            'team_rebotes_extra': team_rebotes_extra,
            'team_valoracion_extra': team_valoracion_extra,
            'num_ot': num_ot,
        })

    parciales_parts = []
    if len(teams_data) == 2:
        t1_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[0]['periods']}
        t2_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[1]['periods']}
        quarters = sorted(q for q in t1_periods if q > 0)
        for q in quarters:
            parciales_parts.append(f"{t1_periods[q]}-{t2_periods[q]}")

    info_adicional = {
        'parciales': ' '.join(parciales_parts),
        'arbitros': ', '.join(data.get('referees', [])),
    }

    return teams_data, info_adicional


def td_val(parent, value):
    td = ET.SubElement(parent, 'td')
    if value and value != '0':
        td.text = value
    return td


def td_tiro(parent, enc, intentos):
    td = ET.SubElement(parent, 'td')
    fmt = convertir_tiros_formato(enc, intentos)
    if fmt:
        td.text = fmt
    return td


def create_xml(teams_data, info_adicional):
    doc = ET.Element('doc')
    doc.set('xml:lang', 'es')

    story = ET.SubElement(doc, 'story')
    text_el = ET.SubElement(story, 'text')
    content = ET.SubElement(text_el, 'content')

    for team in teams_data:
        table = ET.SubElement(content, 'table')
        table.set('class', 'fichabas_auto')

        header_row = ET.SubElement(table, 'tr')
        header_cell = ET.SubElement(header_row, 'td')
        header_cell.set('colspan', '11')
        header_cell.set('class', 'cabecera')
        header_cell.text = f"{team['nombre']}, {team['puntuacion']}"

        titles_row = ET.SubElement(table, 'tr')
        titles_row.set('class', 'valores titulos')
        for title in ['', 'Jugador', 'PTS', '2P', '3P', 'TL', 'RT', 'AS', 'MJ', 'V', '']:
            td = ET.SubElement(titles_row, 'td')
            if title:
                td.text = title

        totales = {
            'puntos': 0,
            't2_enc': 0, 't2_int': 0,
            't3_enc': 0, 't3_int': 0,
            'tl_enc': 0, 'tl_int': 0,
            'rebotes': 0,
            'asistencias': 0,
            'valoracion': 0,
        }

        jugadores_con_relleno = list(team['jugadores'])
        while len(jugadores_con_relleno) < 12:
            jugadores_con_relleno.append(None)

        for player in jugadores_con_relleno:
            row = ET.SubElement(table, 'tr')
            row.set('class', 'valores')

            if player is None:
                for _ in range(11):
                    ET.SubElement(row, 'td')
            else:
                ET.SubElement(row, 'td')

                nombre_cell = ET.SubElement(row, 'td')
                if player.get('titular', False):
                    span = ET.SubElement(nombre_cell, 'span')
                    span.set('class', 'negrita jug')
                    span.text = player['nombre']
                else:
                    nombre_cell.text = player['nombre']

                td_val(row, player['puntos'])
                td_tiro(row, player['t2_enc'], player['t2_int'])
                td_tiro(row, player['t3_enc'], player['t3_int'])
                td_tiro(row, player['tl_enc'], player['tl_int'])
                td_val(row, player['rebotes'])
                td_val(row, player['asistencias'])

                mj_td = ET.SubElement(row, 'td')
                mj_td.text = player['minutos']

                val_td = ET.SubElement(row, 'td')
                val_td.text = player['valoracion']

                ET.SubElement(row, 'td')

                try:
                    totales['puntos'] += int(player['puntos'])
                except (ValueError, TypeError):
                    pass

                totales['t2_enc'] += player['t2_enc']
                totales['t2_int'] += player['t2_int']
                totales['t3_enc'] += player['t3_enc']
                totales['t3_int'] += player['t3_int']
                totales['tl_enc'] += player['tl_enc']
                totales['tl_int'] += player['tl_int']

                try:
                    totales['rebotes'] += int(player['rebotes'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['asistencias'] += int(player['asistencias'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['valoracion'] += int(player['valoracion'])
                except (ValueError, TypeError):
                    pass

        tot_row = ET.SubElement(table, 'tr')
        tot_row.set('class', 'totales')
        ET.SubElement(tot_row, 'td')
        ET.SubElement(tot_row, 'td').text = 'Totales'
        ET.SubElement(tot_row, 'td').text = str(totales['puntos'])

        def tot_tiro_td(parent, enc, int_v):
            td = ET.SubElement(parent, 'td')
            td.text = f"{enc}-{int_v}" if int_v > 0 else ''
            return td

        tot_tiro_td(tot_row, totales['t2_enc'], totales['t2_int'])
        tot_tiro_td(tot_row, totales['t3_enc'], totales['t3_int'])
        tot_tiro_td(tot_row, totales['tl_enc'], totales['tl_int'])

        total_rebotes = totales['rebotes'] + team.get('team_rebotes_extra', 0)
        total_valoracion = totales['valoracion'] + team.get('team_valoracion_extra', 0)
        minutos_partido = 200 + team.get('num_ot', 0) * 25

        td_reb = ET.SubElement(tot_row, 'td')
        td_reb.text = str(total_rebotes) if total_rebotes > 0 else ''

        td_ast = ET.SubElement(tot_row, 'td')
        td_ast.text = str(totales['asistencias']) if totales['asistencias'] > 0 else ''

        ET.SubElement(tot_row, 'td').text = str(minutos_partido)
        ET.SubElement(tot_row, 'td').text = str(total_valoracion)
        ET.SubElement(tot_row, 'td')

        is_last_team = (team is teams_data[-1])

        entr_row = ET.SubElement(table, 'tr')
        entr_row.set('class', 'margenesfilete')
        ET.SubElement(entr_row, 'td')
        entr_lbl = ET.SubElement(entr_row, 'td')
        entr_lbl.set('class', 'negrita')
        entr_lbl.text = 'Entrenador:'
        entr_val = ET.SubElement(entr_row, 'td')
        entr_val.set('class', 'left')
        entr_val.set('colspan', '8')
        entr_val.text = f"\u2002{team.get('entrenador', '')}"
        ET.SubElement(entr_row, 'td')

        if is_last_team:
            def add_info_row(parent, label, value=''):
                row = ET.SubElement(parent, 'tr')
                row.set('class', 'margenesfilete')
                ET.SubElement(row, 'td')
                cell = ET.SubElement(row, 'td')
                cell.set('class', 'left')
                cell.set('colspan', '9')
                span = ET.SubElement(cell, 'span')
                span.set('class', 'negrita')
                span.text = label
                span.tail = value
                ET.SubElement(row, 'td')
                return row

            add_info_row(table, 'Parciales: ', info_adicional.get('parciales', ''))
            add_info_row(table, 'Árbitros: ', info_adicional.get('arbitros', ''))

            cab = ET.SubElement(table, 'tr')
            cab_cell = ET.SubElement(cab, 'td')
            cab_cell.set('class', 'rojo')
            cab_cell.set('colspan', '11')

    xml_string = ET.tostring(doc, encoding='utf-8', method='xml')
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent='\t', encoding='utf-8')
    return pretty_xml


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        match_id = str(data.get('matchId', '')).strip()

        if not match_id:
            return jsonify({'error': 'Por favor, introduce el número de partido'}), 400

        try:
            api_data = fetch_match_data(match_id)
        except Exception as e:
            return jsonify({'error': f'Error al conectar con la API de ACB: {str(e)}'}), 502

        teams_data, info_adicional = parse_api_data(api_data)

        if not teams_data:
            return jsonify({'error': 'No se encontraron datos para este partido'}), 404

        xml_content = create_xml(teams_data, info_adicional)
        xml_str = xml_content.decode('utf-8')

        return jsonify({'success': True, 'xml': xml_str})

    except Exception as e:
        return jsonify({'error': f'Error al generar el XML: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
from flask import Flask, render_template, request, jsonify
import xml.etree.ElementTree as ET
from xml.dom import minidom
import urllib.request
import json

app = Flask(__name__)

ACB_HEADERS = {
    'x-apikey': '0dd94928-6f57-4c08-a3bd-b1b2f092976e',
    'origin': 'https://live.acb.com',
    'referer': 'https://live.acb.com/',
}


def convertir_tiros_formato(enc, intentos):
    if enc == 0 and intentos == 0:
        return ''
    return f"{enc}-{intentos}"


def convertir_minutos(minutos_str):
    if ':' in minutos_str:
        parts = minutos_str.split(':')
        mins = int(parts[0])
        secs = int(parts[1]) if len(parts) > 1 else 0
        result = round(mins + secs / 60)
        if result == 0 and secs > 0:
            result = 1
        return str(result)
    return minutos_str


def extraer_apellido(first_initial_and_last):
    if '. ' in first_initial_and_last:
        return first_initial_and_last.split('. ', 1)[1]
    return first_initial_and_last


def fetch_match_data(match_id):
    url = f'https://api2.acb.com/api/matchdata/Result/boxscores?matchId={match_id}'
    req = urllib.request.Request(url)
    for k, v in ACB_HEADERS.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def parse_api_data(data):
    teams_data = []

    for team_box in data.get('teamBoxscores', []):
        team_info = team_box.get('team', {})
        team_name = team_info.get('fullName', '')

        head_coach = team_box.get('headCoach', '')

        periods = team_box.get('statsByPeriods', [])

        total_period = next((p for p in periods if p['quarter'] == 0), None)
        if total_period is None:
            continue

        team_points = total_period['stats']['total']['points']
        team_stats = total_period['stats'].get('team', {})
        team_rebotes_extra = team_stats.get('totalRebounds', 0)
        team_valoracion_extra = team_stats.get('rating', 0)

        num_ot = sum(1 for p in periods if p['quarter'] > 4)

        players_raw = total_period['stats']['players']

        starters = [p for p in players_raw if p.get('isStarted')]
        bench = [p for p in players_raw if not p.get('isStarted')]
        ordered_players = starters + bench

        players = []
        for p in ordered_players:
            play_time = p.get('playTime', '00:00')
            if play_time == '00:00' or play_time == '0:00':
                continue

            player_info = p.get('player', {})
            nombre = extraer_apellido(player_info.get('firstInitialAndLastName', ''))
            dorsal = player_info.get('shirtNumber', '')

            minutos = convertir_minutos(play_time)
            puntos = p.get('points', 0)
            t2_enc = p.get('twoPointersMade', 0)
            t2_int = p.get('twoPointersAttempted', 0)
            t3_enc = p.get('threePointersMade', 0)
            t3_int = p.get('threePointersAttempted', 0)
            tl_enc = p.get('freeThrowsMade', 0)
            tl_int = p.get('freeThrowsAttempted', 0)
            rebotes = p.get('totalRebounds', 0)
            asistencias = p.get('assists', 0)
            valoracion = p.get('rating', 0)
            titular = p.get('isStarted', False)

            players.append({
                'dorsal': dorsal,
                'nombre': nombre,
                'minutos': minutos,
                'puntos': str(puntos),
                't2_enc': t2_enc, 't2_int': t2_int,
                't3_enc': t3_enc, 't3_int': t3_int,
                'tl_enc': tl_enc, 'tl_int': tl_int,
                'rebotes': str(rebotes),
                'asistencias': str(asistencias),
                'valoracion': str(valoracion),
                'titular': titular,
            })

        teams_data.append({
            'nombre': team_name,
            'puntuacion': str(team_points),
            'jugadores': players,
            'entrenador': head_coach,
            'periods': periods,
            'team_rebotes_extra': team_rebotes_extra,
            'team_valoracion_extra': team_valoracion_extra,
            'num_ot': num_ot,
        })

    parciales_parts = []
    if len(teams_data) == 2:
        t1_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[0]['periods']}
        t2_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[1]['periods']}
        quarters = sorted(q for q in t1_periods if q > 0)
        for q in quarters:
            parciales_parts.append(f"{t1_periods[q]}-{t2_periods[q]}")

    info_adicional = {
        'parciales': ' '.join(parciales_parts),
        'arbitros': ', '.join(data.get('referees', [])),
    }

    return teams_data, info_adicional


def td_val(parent, value):
    td = ET.SubElement(parent, 'td')
    if value and value != '0':
        td.text = value
    return td


def td_tiro(parent, enc, intentos):
    td = ET.SubElement(parent, 'td')
    fmt = convertir_tiros_formato(enc, intentos)
    if fmt:
        td.text = fmt
    return td


def create_xml(teams_data, info_adicional):
    doc = ET.Element('doc')
    doc.set('xml:lang', 'es')

    story = ET.SubElement(doc, 'story')
    text_el = ET.SubElement(story, 'text')
    content = ET.SubElement(text_el, 'content')

    for team in teams_data:
        table = ET.SubElement(content, 'table')
        table.set('class', 'fichabas_auto')

        header_row = ET.SubElement(table, 'tr')
        header_cell = ET.SubElement(header_row, 'td')
        header_cell.set('colspan', '11')
        header_cell.set('class', 'cabecera')
        header_cell.text = f"{team['nombre']}, {team['puntuacion']}"

        titles_row = ET.SubElement(table, 'tr')
        titles_row.set('class', 'valores titulos')
        for title in ['', 'Jugador', 'PTS', '2P', '3P', 'TL', 'RT', 'AS', 'MJ', 'V', '']:
            td = ET.SubElement(titles_row, 'td')
            if title:
                td.text = title

        totales = {
            'puntos': 0,
            't2_enc': 0, 't2_int': 0,
            't3_enc': 0, 't3_int': 0,
            'tl_enc': 0, 'tl_int': 0,
            'rebotes': 0,
            'asistencias': 0,
            'valoracion': 0,
        }

        jugadores_con_relleno = list(team['jugadores'])
        while len(jugadores_con_relleno) < 12:
            jugadores_con_relleno.append(None)

        for player in jugadores_con_relleno:
            row = ET.SubElement(table, 'tr')
            row.set('class', 'valores')

            if player is None:
                for _ in range(11):
                    ET.SubElement(row, 'td')
            else:
                ET.SubElement(row, 'td')

                nombre_cell = ET.SubElement(row, 'td')
                if player.get('titular', False):
                    span = ET.SubElement(nombre_cell, 'span')
                    span.set('class', 'negrita jug')
                    span.text = player['nombre']
                else:
                    nombre_cell.text = player['nombre']

                td_val(row, player['puntos'])
                td_tiro(row, player['t2_enc'], player['t2_int'])
                td_tiro(row, player['t3_enc'], player['t3_int'])
                td_tiro(row, player['tl_enc'], player['tl_int'])
                td_val(row, player['rebotes'])
                td_val(row, player['asistencias'])

                mj_td = ET.SubElement(row, 'td')
                mj_td.text = player['minutos']

                val_td = ET.SubElement(row, 'td')
                val_td.text = player['valoracion']

                ET.SubElement(row, 'td')

                try:
                    totales['puntos'] += int(player['puntos'])
                except (ValueError, TypeError):
                    pass

                totales['t2_enc'] += player['t2_enc']
                totales['t2_int'] += player['t2_int']
                totales['t3_enc'] += player['t3_enc']
                totales['t3_int'] += player['t3_int']
                totales['tl_enc'] += player['tl_enc']
                totales['tl_int'] += player['tl_int']

                try:
                    totales['rebotes'] += int(player['rebotes'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['asistencias'] += int(player['asistencias'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['valoracion'] += int(player['valoracion'])
                except (ValueError, TypeError):
                    pass

        tot_row = ET.SubElement(table, 'tr')
        tot_row.set('class', 'totales')
        ET.SubElement(tot_row, 'td')
        ET.SubElement(tot_row, 'td').text = 'Totales'
        ET.SubElement(tot_row, 'td').text = str(totales['puntos'])

        def tot_tiro_td(parent, enc, int_v):
            td = ET.SubElement(parent, 'td')
            td.text = f"{enc}-{int_v}" if int_v > 0 else ''
            return td

        tot_tiro_td(tot_row, totales['t2_enc'], totales['t2_int'])
        tot_tiro_td(tot_row, totales['t3_enc'], totales['t3_int'])
        tot_tiro_td(tot_row, totales['tl_enc'], totales['tl_int'])

        total_rebotes = totales['rebotes'] + team.get('team_rebotes_extra', 0)
        total_valoracion = totales['valoracion'] + team.get('team_valoracion_extra', 0)
        minutos_partido = 200 + team.get('num_ot', 0) * 25

        td_reb = ET.SubElement(tot_row, 'td')
        td_reb.text = str(total_rebotes) if total_rebotes > 0 else ''

        td_ast = ET.SubElement(tot_row, 'td')
        td_ast.text = str(totales['asistencias']) if totales['asistencias'] > 0 else ''

        ET.SubElement(tot_row, 'td').text = str(minutos_partido)
        ET.SubElement(tot_row, 'td').text = str(total_valoracion)
        ET.SubElement(tot_row, 'td')

        is_last_team = (team is teams_data[-1])

        entr_row = ET.SubElement(table, 'tr')
        entr_row.set('class', 'margenesfilete')
        ET.SubElement(entr_row, 'td')
        entr_lbl = ET.SubElement(entr_row, 'td')
        entr_lbl.set('class', 'negrita')
        entr_lbl.text = 'Entrenador:'
        entr_val = ET.SubElement(entr_row, 'td')
        entr_val.set('class', 'left')
        entr_val.set('colspan', '8')
        entr_val.text = f"\u2002{team.get('entrenador', '')}"
        ET.SubElement(entr_row, 'td')

        if is_last_team:
            def add_info_row(parent, label, value=''):
                row = ET.SubElement(parent, 'tr')
                row.set('class', 'margenesfilete')
                ET.SubElement(row, 'td')
                cell = ET.SubElement(row, 'td')
                cell.set('class', 'left')
                cell.set('colspan', '9')
                span = ET.SubElement(cell, 'span')
                span.set('class', 'negrita')
                span.text = label
                span.tail = value
                ET.SubElement(row, 'td')
                return row

            add_info_row(table, 'Parciales: ', info_adicional.get('parciales', ''))
            add_info_row(table, 'Árbitros: ', info_adicional.get('arbitros', ''))

            cab = ET.SubElement(table, 'tr')
            cab_cell = ET.SubElement(cab, 'td')
            cab_cell.set('class', 'rojo')
            cab_cell.set('colspan', '11')

    xml_string = ET.tostring(doc, encoding='utf-8', method='xml')
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent='\t', encoding='utf-8')
    return pretty_xml


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        match_id = str(data.get('matchId', '')).strip()

        if not match_id:
            return jsonify({'error': 'Por favor, introduce el número de partido'}), 400

        try:
            api_data = fetch_match_data(match_id)
        except Exception as e:
            return jsonify({'error': f'Error al conectar con la API de ACB: {str(e)}'}), 502

        teams_data, info_adicional = parse_api_data(api_data)

        if not teams_data:
            return jsonify({'error': 'No se encontraron datos para este partido'}), 404

        xml_content = create_xml(teams_data, info_adicional)
        xml_str = xml_content.decode('utf-8')

        return jsonify({'success': True, 'xml': xml_str})

    except Exception as e:
        return jsonify({'error': f'Error al generar el XML: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
from flask import Flask, render_template, request, jsonify
import xml.etree.ElementTree as ET
from xml.dom import minidom
import urllib.request
import json

app = Flask(__name__)

ACB_HEADERS = {
    'x-apikey': '0dd94928-6f57-4c08-a3bd-b1b2f092976e',
    'origin': 'https://live.acb.com',
    'referer': 'https://live.acb.com/',
}


def convertir_tiros_formato(enc, intentos):
    if enc == 0 and intentos == 0:
        return ''
    return f"{enc}-{intentos}"


def convertir_minutos(minutos_str):
    if ':' in minutos_str:
        parts = minutos_str.split(':')
        mins = int(parts[0])
        secs = int(parts[1]) if len(parts) > 1 else 0
        result = round(mins + secs / 60)
        if result == 0 and secs > 0:
            result = 1
        return str(result)
    return minutos_str


def extraer_apellido(first_initial_and_last):
    if '. ' in first_initial_and_last:
        return first_initial_and_last.split('. ', 1)[1]
    return first_initial_and_last


def fetch_match_data(match_id):
    url = f'https://api2.acb.com/api/matchdata/Result/boxscores?matchId={match_id}'
    req = urllib.request.Request(url)
    for k, v in ACB_HEADERS.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def parse_api_data(data):
    teams_data = []

    for team_box in data.get('teamBoxscores', []):
        team_info = team_box.get('team', {})
        team_name = team_info.get('fullName', '')

        head_coach = team_box.get('headCoach', '')

        periods = team_box.get('statsByPeriods', [])

        total_period = next((p for p in periods if p['quarter'] == 0), None)
        if total_period is None:
            continue

        team_points = total_period['stats']['total']['points']
        team_stats = total_period['stats'].get('team', {})
        team_rebotes_extra = team_stats.get('totalRebounds', 0)
        team_valoracion_extra = team_stats.get('rating', 0)

        num_ot = sum(1 for p in periods if p['quarter'] > 4)

        players_raw = total_period['stats']['players']

        starters = [p for p in players_raw if p.get('isStarted')]
        bench = [p for p in players_raw if not p.get('isStarted')]
        ordered_players = starters + bench

        players = []
        for p in ordered_players:
            play_time = p.get('playTime', '00:00')
            if play_time == '00:00' or play_time == '0:00':
                continue

            player_info = p.get('player', {})
            nombre = extraer_apellido(player_info.get('firstInitialAndLastName', ''))
            dorsal = player_info.get('shirtNumber', '')

            minutos = convertir_minutos(play_time)
            puntos = p.get('points', 0)
            t2_enc = p.get('twoPointersMade', 0)
            t2_int = p.get('twoPointersAttempted', 0)
            t3_enc = p.get('threePointersMade', 0)
            t3_int = p.get('threePointersAttempted', 0)
            tl_enc = p.get('freeThrowsMade', 0)
            tl_int = p.get('freeThrowsAttempted', 0)
            rebotes = p.get('totalRebounds', 0)
            asistencias = p.get('assists', 0)
            valoracion = p.get('rating', 0)
            titular = p.get('isStarted', False)

            players.append({
                'dorsal': dorsal,
                'nombre': nombre,
                'minutos': minutos,
                'puntos': str(puntos),
                't2_enc': t2_enc, 't2_int': t2_int,
                't3_enc': t3_enc, 't3_int': t3_int,
                'tl_enc': tl_enc, 'tl_int': tl_int,
                'rebotes': str(rebotes),
                'asistencias': str(asistencias),
                'valoracion': str(valoracion),
                'titular': titular,
            })

        teams_data.append({
            'nombre': team_name,
            'puntuacion': str(team_points),
            'jugadores': players,
            'entrenador': head_coach,
            'periods': periods,
            'team_rebotes_extra': team_rebotes_extra,
            'team_valoracion_extra': team_valoracion_extra,
            'num_ot': num_ot,
        })

    parciales_parts = []
    if len(teams_data) == 2:
        t1_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[0]['periods']}
        t2_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[1]['periods']}
        quarters = sorted(q for q in t1_periods if q > 0)
        for q in quarters:
            parciales_parts.append(f"{t1_periods[q]}-{t2_periods[q]}")

    info_adicional = {
        'parciales': ' '.join(parciales_parts),
        'arbitros': ', '.join(data.get('referees', [])),
    }

    return teams_data, info_adicional


def td_val(parent, value):
    td = ET.SubElement(parent, 'td')
    if value and value != '0':
        td.text = value
    return td


def td_tiro(parent, enc, intentos):
    td = ET.SubElement(parent, 'td')
    fmt = convertir_tiros_formato(enc, intentos)
    if fmt:
        td.text = fmt
    return td


def create_xml(teams_data, info_adicional):
    doc = ET.Element('doc')
    doc.set('xml:lang', 'es')

    story = ET.SubElement(doc, 'story')
    text_el = ET.SubElement(story, 'text')
    content = ET.SubElement(text_el, 'content')

    for team in teams_data:
        table = ET.SubElement(content, 'table')
        table.set('class', 'fichabas_auto')

        header_row = ET.SubElement(table, 'tr')
        header_cell = ET.SubElement(header_row, 'td')
        header_cell.set('colspan', '11')
        header_cell.set('class', 'cabecera')
        header_cell.text = f"{team['nombre']}, {team['puntuacion']}"

        titles_row = ET.SubElement(table, 'tr')
        titles_row.set('class', 'valores titulos')
        for title in ['', 'Jugador', 'PTS', '2P', '3P', 'TL', 'RT', 'AS', 'MJ', 'V', '']:
            td = ET.SubElement(titles_row, 'td')
            if title:
                td.text = title

        totales = {
            'puntos': 0,
            't2_enc': 0, 't2_int': 0,
            't3_enc': 0, 't3_int': 0,
            'tl_enc': 0, 'tl_int': 0,
            'rebotes': 0,
            'asistencias': 0,
            'valoracion': 0,
        }

        jugadores_con_relleno = list(team['jugadores'])
        while len(jugadores_con_relleno) < 12:
            jugadores_con_relleno.append(None)

        for player in jugadores_con_relleno:
            row = ET.SubElement(table, 'tr')
            row.set('class', 'valores')

            if player is None:
                for _ in range(11):
                    ET.SubElement(row, 'td')
            else:
                ET.SubElement(row, 'td')

                nombre_cell = ET.SubElement(row, 'td')
                if player.get('titular', False):
                    span = ET.SubElement(nombre_cell, 'span')
                    span.set('class', 'negrita jug')
                    span.text = player['nombre']
                else:
                    nombre_cell.text = player['nombre']

                td_val(row, player['puntos'])
                td_tiro(row, player['t2_enc'], player['t2_int'])
                td_tiro(row, player['t3_enc'], player['t3_int'])
                td_tiro(row, player['tl_enc'], player['tl_int'])
                td_val(row, player['rebotes'])
                td_val(row, player['asistencias'])

                mj_td = ET.SubElement(row, 'td')
                mj_td.text = player['minutos']

                val_td = ET.SubElement(row, 'td')
                val_td.text = player['valoracion']

                ET.SubElement(row, 'td')

                try:
                    totales['puntos'] += int(player['puntos'])
                except (ValueError, TypeError):
                    pass

                totales['t2_enc'] += player['t2_enc']
                totales['t2_int'] += player['t2_int']
                totales['t3_enc'] += player['t3_enc']
                totales['t3_int'] += player['t3_int']
                totales['tl_enc'] += player['tl_enc']
                totales['tl_int'] += player['tl_int']

                try:
                    totales['rebotes'] += int(player['rebotes'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['asistencias'] += int(player['asistencias'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['valoracion'] += int(player['valoracion'])
                except (ValueError, TypeError):
                    pass

        tot_row = ET.SubElement(table, 'tr')
        tot_row.set('class', 'totales')
        ET.SubElement(tot_row, 'td')
        ET.SubElement(tot_row, 'td').text = 'Totales'
        ET.SubElement(tot_row, 'td').text = str(totales['puntos'])

        def tot_tiro_td(parent, enc, int_v):
            td = ET.SubElement(parent, 'td')
            td.text = f"{enc}-{int_v}" if int_v > 0 else ''
            return td

        tot_tiro_td(tot_row, totales['t2_enc'], totales['t2_int'])
        tot_tiro_td(tot_row, totales['t3_enc'], totales['t3_int'])
        tot_tiro_td(tot_row, totales['tl_enc'], totales['tl_int'])

        total_rebotes = totales['rebotes'] + team.get('team_rebotes_extra', 0)
        total_valoracion = totales['valoracion'] + team.get('team_valoracion_extra', 0)
        minutos_partido = 200 + team.get('num_ot', 0) * 25

        td_reb = ET.SubElement(tot_row, 'td')
        td_reb.text = str(total_rebotes) if total_rebotes > 0 else ''

        td_ast = ET.SubElement(tot_row, 'td')
        td_ast.text = str(totales['asistencias']) if totales['asistencias'] > 0 else ''

        ET.SubElement(tot_row, 'td').text = str(minutos_partido)
        ET.SubElement(tot_row, 'td').text = str(total_valoracion)
        ET.SubElement(tot_row, 'td')

        is_last_team = (team is teams_data[-1])

        entr_row = ET.SubElement(table, 'tr')
        entr_row.set('class', 'margenesfilete')
        ET.SubElement(entr_row, 'td')
        entr_lbl = ET.SubElement(entr_row, 'td')
        entr_lbl.set('class', 'negrita')
        entr_lbl.text = 'Entrenador:'
        entr_val = ET.SubElement(entr_row, 'td')
        entr_val.set('class', 'left')
        entr_val.set('colspan', '8')
        entr_val.text = f"\u2002{team.get('entrenador', '')}"
        ET.SubElement(entr_row, 'td')

        if is_last_team:
            def add_info_row(parent, label, value=''):
                row = ET.SubElement(parent, 'tr')
                row.set('class', 'margenesfilete')
                ET.SubElement(row, 'td')
                cell = ET.SubElement(row, 'td')
                cell.set('class', 'left')
                cell.set('colspan', '9')
                span = ET.SubElement(cell, 'span')
                span.set('class', 'negrita')
                span.text = label
                span.tail = value
                ET.SubElement(row, 'td')
                return row

            add_info_row(table, 'Parciales: ', info_adicional.get('parciales', ''))
            add_info_row(table, 'Árbitros: ', info_adicional.get('arbitros', ''))

            cab = ET.SubElement(table, 'tr')
            cab_cell = ET.SubElement(cab, 'td')
            cab_cell.set('class', 'rojo')
            cab_cell.set('colspan', '11')

    xml_string = ET.tostring(doc, encoding='utf-8', method='xml')
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent='\t', encoding='utf-8')
    return pretty_xml


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        match_id = str(data.get('matchId', '')).strip()

        if not match_id:
            return jsonify({'error': 'Por favor, introduce el número de partido'}), 400

        try:
            api_data = fetch_match_data(match_id)
        except Exception as e:
            return jsonify({'error': f'Error al conectar con la API de ACB: {str(e)}'}), 502

        teams_data, info_adicional = parse_api_data(api_data)

        if not teams_data:
            return jsonify({'error': 'No se encontraron datos para este partido'}), 404

        xml_content = create_xml(teams_data, info_adicional)
        xml_str = xml_content.decode('utf-8')

        return jsonify({'success': True, 'xml': xml_str})

    except Exception as e:
        return jsonify({'error': f'Error al generar el XML: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
from flask import Flask, render_template, request, jsonify
import xml.etree.ElementTree as ET
from xml.dom import minidom
import urllib.request
import json

app = Flask(__name__)

ACB_HEADERS = {
    'x-apikey': '0dd94928-6f57-4c08-a3bd-b1b2f092976e',
    'origin': 'https://live.acb.com',
    'referer': 'https://live.acb.com/',
}


def convertir_tiros_formato(enc, intentos):
    if enc == 0 and intentos == 0:
        return ''
    return f"{enc}-{intentos}"


def convertir_minutos(minutos_str):
    if ':' in minutos_str:
        parts = minutos_str.split(':')
        mins = int(parts[0])
        secs = int(parts[1]) if len(parts) > 1 else 0
        result = round(mins + secs / 60)
        if result == 0 and secs > 0:
            result = 1
        return str(result)
    return minutos_str


def extraer_apellido(first_initial_and_last):
    if '. ' in first_initial_and_last:
        return first_initial_and_last.split('. ', 1)[1]
    return first_initial_and_last


def fetch_match_data(match_id):
    url = f'https://api2.acb.com/api/matchdata/Result/boxscores?matchId={match_id}'
    req = urllib.request.Request(url)
    for k, v in ACB_HEADERS.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def parse_api_data(data):
    teams_data = []

    for team_box in data.get('teamBoxscores', []):
        team_info = team_box.get('team', {})
        team_name = team_info.get('fullName', '')

        head_coach = team_box.get('headCoach', '')

        periods = team_box.get('statsByPeriods', [])

        total_period = next((p for p in periods if p['quarter'] == 0), None)
        if total_period is None:
            continue

        team_points = total_period['stats']['total']['points']
        team_stats = total_period['stats'].get('team', {})
        team_rebotes_extra = team_stats.get('totalRebounds', 0)
        team_valoracion_extra = team_stats.get('rating', 0)

        num_ot = sum(1 for p in periods if p['quarter'] > 4)

        players_raw = total_period['stats']['players']

        starters = [p for p in players_raw if p.get('isStarted')]
        bench = [p for p in players_raw if not p.get('isStarted')]
        ordered_players = starters + bench

        players = []
        for p in ordered_players:
            play_time = p.get('playTime', '00:00')
            if play_time == '00:00' or play_time == '0:00':
                continue

            player_info = p.get('player', {})
            nombre = extraer_apellido(player_info.get('firstInitialAndLastName', ''))
            dorsal = player_info.get('shirtNumber', '')

            minutos = convertir_minutos(play_time)
            puntos = p.get('points', 0)
            t2_enc = p.get('twoPointersMade', 0)
            t2_int = p.get('twoPointersAttempted', 0)
            t3_enc = p.get('threePointersMade', 0)
            t3_int = p.get('threePointersAttempted', 0)
            tl_enc = p.get('freeThrowsMade', 0)
            tl_int = p.get('freeThrowsAttempted', 0)
            rebotes = p.get('totalRebounds', 0)
            asistencias = p.get('assists', 0)
            valoracion = p.get('rating', 0)
            titular = p.get('isStarted', False)

            players.append({
                'dorsal': dorsal,
                'nombre': nombre,
                'minutos': minutos,
                'puntos': str(puntos),
                't2_enc': t2_enc, 't2_int': t2_int,
                't3_enc': t3_enc, 't3_int': t3_int,
                'tl_enc': tl_enc, 'tl_int': tl_int,
                'rebotes': str(rebotes),
                'asistencias': str(asistencias),
                'valoracion': str(valoracion),
                'titular': titular,
            })

        teams_data.append({
            'nombre': team_name,
            'puntuacion': str(team_points),
            'jugadores': players,
            'entrenador': head_coach,
            'periods': periods,
            'team_rebotes_extra': team_rebotes_extra,
            'team_valoracion_extra': team_valoracion_extra,
            'num_ot': num_ot,
        })

    parciales_parts = []
    if len(teams_data) == 2:
        t1_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[0]['periods']}
        t2_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[1]['periods']}
        quarters = sorted(q for q in t1_periods if q > 0)
        for q in quarters:
            parciales_parts.append(f"{t1_periods[q]}-{t2_periods[q]}")

    info_adicional = {
        'parciales': ' '.join(parciales_parts),
        'arbitros': ', '.join(data.get('referees', [])),
    }

    return teams_data, info_adicional


def td_val(parent, value):
    td = ET.SubElement(parent, 'td')
    if value and value != '0':
        td.text = value
    return td


def td_tiro(parent, enc, intentos):
    td = ET.SubElement(parent, 'td')
    fmt = convertir_tiros_formato(enc, intentos)
    if fmt:
        td.text = fmt
    return td


def create_xml(teams_data, info_adicional):
    doc = ET.Element('doc')
    doc.set('xml:lang', 'es')

    story = ET.SubElement(doc, 'story')
    text_el = ET.SubElement(story, 'text')
    content = ET.SubElement(text_el, 'content')

    for team in teams_data:
        table = ET.SubElement(content, 'table')
        table.set('class', 'fichabas_auto')

        header_row = ET.SubElement(table, 'tr')
        header_cell = ET.SubElement(header_row, 'td')
        header_cell.set('colspan', '11')
        header_cell.set('class', 'cabecera')
        header_cell.text = f"{team['nombre']}, {team['puntuacion']}"

        titles_row = ET.SubElement(table, 'tr')
        titles_row.set('class', 'valores titulos')
        for title in ['', 'Jugador', 'PTS', '2P', '3P', 'TL', 'RT', 'AS', 'MJ', 'V', '']:
            td = ET.SubElement(titles_row, 'td')
            if title:
                td.text = title

        totales = {
            'puntos': 0,
            't2_enc': 0, 't2_int': 0,
            't3_enc': 0, 't3_int': 0,
            'tl_enc': 0, 'tl_int': 0,
            'rebotes': 0,
            'asistencias': 0,
            'valoracion': 0,
        }

        jugadores_con_relleno = list(team['jugadores'])
        while len(jugadores_con_relleno) < 12:
            jugadores_con_relleno.append(None)

        for player in jugadores_con_relleno:
            row = ET.SubElement(table, 'tr')
            row.set('class', 'valores')

            if player is None:
                for _ in range(11):
                    ET.SubElement(row, 'td')
            else:
                ET.SubElement(row, 'td')

                nombre_cell = ET.SubElement(row, 'td')
                if player.get('titular', False):
                    span = ET.SubElement(nombre_cell, 'span')
                    span.set('class', 'negrita jug')
                    span.text = player['nombre']
                else:
                    nombre_cell.text = player['nombre']

                td_val(row, player['puntos'])
                td_tiro(row, player['t2_enc'], player['t2_int'])
                td_tiro(row, player['t3_enc'], player['t3_int'])
                td_tiro(row, player['tl_enc'], player['tl_int'])
                td_val(row, player['rebotes'])
                td_val(row, player['asistencias'])

                mj_td = ET.SubElement(row, 'td')
                mj_td.text = player['minutos']

                val_td = ET.SubElement(row, 'td')
                val_td.text = player['valoracion']

                ET.SubElement(row, 'td')

                try:
                    totales['puntos'] += int(player['puntos'])
                except (ValueError, TypeError):
                    pass

                totales['t2_enc'] += player['t2_enc']
                totales['t2_int'] += player['t2_int']
                totales['t3_enc'] += player['t3_enc']
                totales['t3_int'] += player['t3_int']
                totales['tl_enc'] += player['tl_enc']
                totales['tl_int'] += player['tl_int']

                try:
                    totales['rebotes'] += int(player['rebotes'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['asistencias'] += int(player['asistencias'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['valoracion'] += int(player['valoracion'])
                except (ValueError, TypeError):
                    pass

        tot_row = ET.SubElement(table, 'tr')
        tot_row.set('class', 'totales')
        ET.SubElement(tot_row, 'td')
        ET.SubElement(tot_row, 'td').text = 'Totales'
        ET.SubElement(tot_row, 'td').text = str(totales['puntos'])

        def tot_tiro_td(parent, enc, int_v):
            td = ET.SubElement(parent, 'td')
            td.text = f"{enc}-{int_v}" if int_v > 0 else ''
            return td

        tot_tiro_td(tot_row, totales['t2_enc'], totales['t2_int'])
        tot_tiro_td(tot_row, totales['t3_enc'], totales['t3_int'])
        tot_tiro_td(tot_row, totales['tl_enc'], totales['tl_int'])

        total_rebotes = totales['rebotes'] + team.get('team_rebotes_extra', 0)
        total_valoracion = totales['valoracion'] + team.get('team_valoracion_extra', 0)
        minutos_partido = 200 + team.get('num_ot', 0) * 25

        td_reb = ET.SubElement(tot_row, 'td')
        td_reb.text = str(total_rebotes) if total_rebotes > 0 else ''

        td_ast = ET.SubElement(tot_row, 'td')
        td_ast.text = str(totales['asistencias']) if totales['asistencias'] > 0 else ''

        ET.SubElement(tot_row, 'td').text = str(minutos_partido)
        ET.SubElement(tot_row, 'td').text = str(total_valoracion)
        ET.SubElement(tot_row, 'td')

        is_last_team = (team is teams_data[-1])

        entr_row = ET.SubElement(table, 'tr')
        entr_row.set('class', 'margenesfilete')
        ET.SubElement(entr_row, 'td')
        entr_lbl = ET.SubElement(entr_row, 'td')
        entr_lbl.set('class', 'negrita')
        entr_lbl.text = 'Entrenador:'
        entr_val = ET.SubElement(entr_row, 'td')
        entr_val.set('class', 'left')
        entr_val.set('colspan', '8')
        entr_val.text = f"\u2002{team.get('entrenador', '')}"
        ET.SubElement(entr_row, 'td')

        if is_last_team:
            def add_info_row(parent, label, value=''):
                row = ET.SubElement(parent, 'tr')
                row.set('class', 'margenesfilete')
                ET.SubElement(row, 'td')
                cell = ET.SubElement(row, 'td')
                cell.set('class', 'left')
                cell.set('colspan', '9')
                span = ET.SubElement(cell, 'span')
                span.set('class', 'negrita')
                span.text = label
                span.tail = value
                ET.SubElement(row, 'td')
                return row

            add_info_row(table, 'Parciales: ', info_adicional.get('parciales', ''))
            add_info_row(table, 'Árbitros: ', info_adicional.get('arbitros', ''))

            cab = ET.SubElement(table, 'tr')
            cab_cell = ET.SubElement(cab, 'td')
            cab_cell.set('class', 'rojo')
            cab_cell.set('colspan', '11')

    xml_string = ET.tostring(doc, encoding='utf-8', method='xml')
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent='\t', encoding='utf-8')
    return pretty_xml


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        match_id = str(data.get('matchId', '')).strip()

        if not match_id:
            return jsonify({'error': 'Por favor, introduce el número de partido'}), 400

        try:
            api_data = fetch_match_data(match_id)
        except Exception as e:
            return jsonify({'error': f'Error al conectar con la API de ACB: {str(e)}'}), 502

        teams_data, info_adicional = parse_api_data(api_data)

        if not teams_data:
            return jsonify({'error': 'No se encontraron datos para este partido'}), 404

        xml_content = create_xml(teams_data, info_adicional)
        xml_str = xml_content.decode('utf-8')

        return jsonify({'success': True, 'xml': xml_str})

    except Exception as e:
        return jsonify({'error': f'Error al generar el XML: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
from flask import Flask, render_template, request, jsonify
import xml.etree.ElementTree as ET
from xml.dom import minidom
import urllib.request
import json

app = Flask(__name__)

ACB_HEADERS = {
    'x-apikey': '0dd94928-6f57-4c08-a3bd-b1b2f092976e',
    'origin': 'https://live.acb.com',
    'referer': 'https://live.acb.com/',
}


def convertir_tiros_formato(enc, intentos):
    if enc == 0 and intentos == 0:
        return ''
    return f"{enc}-{intentos}"


def convertir_minutos(minutos_str):
    if ':' in minutos_str:
        parts = minutos_str.split(':')
        mins = int(parts[0])
        secs = int(parts[1]) if len(parts) > 1 else 0
        result = round(mins + secs / 60)
        if result == 0 and secs > 0:
            result = 1
        return str(result)
    return minutos_str


def extraer_apellido(first_initial_and_last):
    if '. ' in first_initial_and_last:
        return first_initial_and_last.split('. ', 1)[1]
    return first_initial_and_last


def fetch_match_data(match_id):
    url = f'https://api2.acb.com/api/matchdata/Result/boxscores?matchId={match_id}'
    req = urllib.request.Request(url)
    for k, v in ACB_HEADERS.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def parse_api_data(data):
    teams_data = []

    for team_box in data.get('teamBoxscores', []):
        team_info = team_box.get('team', {})
        team_name = team_info.get('fullName', '')

        head_coach = team_box.get('headCoach', '')

        periods = team_box.get('statsByPeriods', [])

        total_period = next((p for p in periods if p['quarter'] == 0), None)
        if total_period is None:
            continue

        team_points = total_period['stats']['total']['points']
        team_stats = total_period['stats'].get('team', {})
        team_rebotes_extra = team_stats.get('totalRebounds', 0)
        team_valoracion_extra = team_stats.get('rating', 0)

        num_ot = sum(1 for p in periods if p['quarter'] > 4)

        players_raw = total_period['stats']['players']

        starters = [p for p in players_raw if p.get('isStarted')]
        bench = [p for p in players_raw if not p.get('isStarted')]
        ordered_players = starters + bench

        players = []
        for p in ordered_players:
            play_time = p.get('playTime', '00:00')
            if play_time == '00:00' or play_time == '0:00':
                continue

            player_info = p.get('player', {})
            nombre = extraer_apellido(player_info.get('firstInitialAndLastName', ''))
            dorsal = player_info.get('shirtNumber', '')

            minutos = convertir_minutos(play_time)
            puntos = p.get('points', 0)
            t2_enc = p.get('twoPointersMade', 0)
            t2_int = p.get('twoPointersAttempted', 0)
            t3_enc = p.get('threePointersMade', 0)
            t3_int = p.get('threePointersAttempted', 0)
            tl_enc = p.get('freeThrowsMade', 0)
            tl_int = p.get('freeThrowsAttempted', 0)
            rebotes = p.get('totalRebounds', 0)
            asistencias = p.get('assists', 0)
            valoracion = p.get('rating', 0)
            titular = p.get('isStarted', False)

            players.append({
                'dorsal': dorsal,
                'nombre': nombre,
                'minutos': minutos,
                'puntos': str(puntos),
                't2_enc': t2_enc, 't2_int': t2_int,
                't3_enc': t3_enc, 't3_int': t3_int,
                'tl_enc': tl_enc, 'tl_int': tl_int,
                'rebotes': str(rebotes),
                'asistencias': str(asistencias),
                'valoracion': str(valoracion),
                'titular': titular,
            })

        teams_data.append({
            'nombre': team_name,
            'puntuacion': str(team_points),
            'jugadores': players,
            'entrenador': head_coach,
            'periods': periods,
            'team_rebotes_extra': team_rebotes_extra,
            'team_valoracion_extra': team_valoracion_extra,
            'num_ot': num_ot,
        })

    parciales_parts = []
    if len(teams_data) == 2:
        t1_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[0]['periods']}
        t2_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[1]['periods']}
        quarters = sorted(q for q in t1_periods if q > 0)
        for q in quarters:
            parciales_parts.append(f"{t1_periods[q]}-{t2_periods[q]}")

    info_adicional = {
        'parciales': ' '.join(parciales_parts),
        'arbitros': ', '.join(data.get('referees', [])),
    }

    return teams_data, info_adicional


def td_val(parent, value):
    td = ET.SubElement(parent, 'td')
    if value and value != '0':
        td.text = value
    return td


def td_tiro(parent, enc, intentos):
    td = ET.SubElement(parent, 'td')
    fmt = convertir_tiros_formato(enc, intentos)
    if fmt:
        td.text = fmt
    return td


def create_xml(teams_data, info_adicional):
    doc = ET.Element('doc')
    doc.set('xml:lang', 'es')

    story = ET.SubElement(doc, 'story')
    text_el = ET.SubElement(story, 'text')
    content = ET.SubElement(text_el, 'content')

    for team in teams_data:
        table = ET.SubElement(content, 'table')
        table.set('class', 'fichabas_auto')

        header_row = ET.SubElement(table, 'tr')
        header_cell = ET.SubElement(header_row, 'td')
        header_cell.set('colspan', '11')
        header_cell.set('class', 'cabecera')
        header_cell.text = f"{team['nombre']}, {team['puntuacion']}"

        titles_row = ET.SubElement(table, 'tr')
        titles_row.set('class', 'valores titulos')
        for title in ['', 'Jugador', 'PTS', '2P', '3P', 'TL', 'RT', 'AS', 'MJ', 'V', '']:
            td = ET.SubElement(titles_row, 'td')
            if title:
                td.text = title

        totales = {
            'puntos': 0,
            't2_enc': 0, 't2_int': 0,
            't3_enc': 0, 't3_int': 0,
            'tl_enc': 0, 'tl_int': 0,
            'rebotes': 0,
            'asistencias': 0,
            'valoracion': 0,
        }

        jugadores_con_relleno = list(team['jugadores'])
        while len(jugadores_con_relleno) < 12:
            jugadores_con_relleno.append(None)

        for player in jugadores_con_relleno:
            row = ET.SubElement(table, 'tr')
            row.set('class', 'valores')

            if player is None:
                for _ in range(11):
                    ET.SubElement(row, 'td')
            else:
                ET.SubElement(row, 'td')

                nombre_cell = ET.SubElement(row, 'td')
                if player.get('titular', False):
                    span = ET.SubElement(nombre_cell, 'span')
                    span.set('class', 'negrita jug')
                    span.text = player['nombre']
                else:
                    nombre_cell.text = player['nombre']

                td_val(row, player['puntos'])
                td_tiro(row, player['t2_enc'], player['t2_int'])
                td_tiro(row, player['t3_enc'], player['t3_int'])
                td_tiro(row, player['tl_enc'], player['tl_int'])
                td_val(row, player['rebotes'])
                td_val(row, player['asistencias'])

                mj_td = ET.SubElement(row, 'td')
                mj_td.text = player['minutos']

                val_td = ET.SubElement(row, 'td')
                val_td.text = player['valoracion']

                ET.SubElement(row, 'td')

                try:
                    totales['puntos'] += int(player['puntos'])
                except (ValueError, TypeError):
                    pass

                totales['t2_enc'] += player['t2_enc']
                totales['t2_int'] += player['t2_int']
                totales['t3_enc'] += player['t3_enc']
                totales['t3_int'] += player['t3_int']
                totales['tl_enc'] += player['tl_enc']
                totales['tl_int'] += player['tl_int']

                try:
                    totales['rebotes'] += int(player['rebotes'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['asistencias'] += int(player['asistencias'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['valoracion'] += int(player['valoracion'])
                except (ValueError, TypeError):
                    pass

        tot_row = ET.SubElement(table, 'tr')
        tot_row.set('class', 'totales')
        ET.SubElement(tot_row, 'td')
        ET.SubElement(tot_row, 'td').text = 'Totales'
        ET.SubElement(tot_row, 'td').text = str(totales['puntos'])

        def tot_tiro_td(parent, enc, int_v):
            td = ET.SubElement(parent, 'td')
            td.text = f"{enc}-{int_v}" if int_v > 0 else ''
            return td

        tot_tiro_td(tot_row, totales['t2_enc'], totales['t2_int'])
        tot_tiro_td(tot_row, totales['t3_enc'], totales['t3_int'])
        tot_tiro_td(tot_row, totales['tl_enc'], totales['tl_int'])

        total_rebotes = totales['rebotes'] + team.get('team_rebotes_extra', 0)
        total_valoracion = totales['valoracion'] + team.get('team_valoracion_extra', 0)
        minutos_partido = 200 + team.get('num_ot', 0) * 25

        td_reb = ET.SubElement(tot_row, 'td')
        td_reb.text = str(total_rebotes) if total_rebotes > 0 else ''

        td_ast = ET.SubElement(tot_row, 'td')
        td_ast.text = str(totales['asistencias']) if totales['asistencias'] > 0 else ''

        ET.SubElement(tot_row, 'td').text = str(minutos_partido)
        ET.SubElement(tot_row, 'td').text = str(total_valoracion)
        ET.SubElement(tot_row, 'td')

        is_last_team = (team is teams_data[-1])

        entr_row = ET.SubElement(table, 'tr')
        entr_row.set('class', 'margenesfilete')
        ET.SubElement(entr_row, 'td')
        entr_lbl = ET.SubElement(entr_row, 'td')
        entr_lbl.set('class', 'negrita')
        entr_lbl.text = 'Entrenador:'
        entr_val = ET.SubElement(entr_row, 'td')
        entr_val.set('class', 'left')
        entr_val.set('colspan', '8')
        entr_val.text = f"\u2002{team.get('entrenador', '')}"
        ET.SubElement(entr_row, 'td')

        if is_last_team:
            def add_info_row(parent, label, value=''):
                row = ET.SubElement(parent, 'tr')
                row.set('class', 'margenesfilete')
                ET.SubElement(row, 'td')
                cell = ET.SubElement(row, 'td')
                cell.set('class', 'left')
                cell.set('colspan', '9')
                span = ET.SubElement(cell, 'span')
                span.set('class', 'negrita')
                span.text = label
                span.tail = value
                ET.SubElement(row, 'td')
                return row

            add_info_row(table, 'Parciales: ', info_adicional.get('parciales', ''))
            add_info_row(table, 'Árbitros: ', info_adicional.get('arbitros', ''))

            cab = ET.SubElement(table, 'tr')
            cab_cell = ET.SubElement(cab, 'td')
            cab_cell.set('class', 'rojo')
            cab_cell.set('colspan', '11')

    xml_string = ET.tostring(doc, encoding='utf-8', method='xml')
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent='\t', encoding='utf-8')
    return pretty_xml


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        match_id = str(data.get('matchId', '')).strip()

        if not match_id:
            return jsonify({'error': 'Por favor, introduce el número de partido'}), 400

        try:
            api_data = fetch_match_data(match_id)
        except Exception as e:
            return jsonify({'error': f'Error al conectar con la API de ACB: {str(e)}'}), 502

        teams_data, info_adicional = parse_api_data(api_data)

        if not teams_data:
            return jsonify({'error': 'No se encontraron datos para este partido'}), 404

        xml_content = create_xml(teams_data, info_adicional)
        xml_str = xml_content.decode('utf-8')

        return jsonify({'success': True, 'xml': xml_str})

    except Exception as e:
        return jsonify({'error': f'Error al generar el XML: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
from flask import Flask, render_template, request, jsonify
import xml.etree.ElementTree as ET
from xml.dom import minidom
import urllib.request
import json

app = Flask(__name__)

ACB_HEADERS = {
    'x-apikey': '0dd94928-6f57-4c08-a3bd-b1b2f092976e',
    'origin': 'https://live.acb.com',
    'referer': 'https://live.acb.com/',
}


def convertir_tiros_formato(enc, intentos):
    if enc == 0 and intentos == 0:
        return ''
    return f"{enc}-{intentos}"


def convertir_minutos(minutos_str):
    if ':' in minutos_str:
        parts = minutos_str.split(':')
        mins = int(parts[0])
        secs = int(parts[1]) if len(parts) > 1 else 0
        result = round(mins + secs / 60)
        if result == 0 and secs > 0:
            result = 1
        return str(result)
    return minutos_str


def extraer_apellido(first_initial_and_last):
    if '. ' in first_initial_and_last:
        return first_initial_and_last.split('. ', 1)[1]
    return first_initial_and_last


def fetch_match_data(match_id):
    url = f'https://api2.acb.com/api/matchdata/Result/boxscores?matchId={match_id}'
    req = urllib.request.Request(url)
    for k, v in ACB_HEADERS.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def parse_api_data(data):
    teams_data = []

    for team_box in data.get('teamBoxscores', []):
        team_info = team_box.get('team', {})
        team_name = team_info.get('fullName', '')

        head_coach = team_box.get('headCoach', '')

        periods = team_box.get('statsByPeriods', [])

        total_period = next((p for p in periods if p['quarter'] == 0), None)
        if total_period is None:
            continue

        team_points = total_period['stats']['total']['points']
        team_stats = total_period['stats'].get('team', {})
        team_rebotes_extra = team_stats.get('totalRebounds', 0)
        team_valoracion_extra = team_stats.get('rating', 0)

        num_ot = sum(1 for p in periods if p['quarter'] > 4)

        players_raw = total_period['stats']['players']

        starters = [p for p in players_raw if p.get('isStarted')]
        bench = [p for p in players_raw if not p.get('isStarted')]
        ordered_players = starters + bench

        players = []
        for p in ordered_players:
            play_time = p.get('playTime', '00:00')
            if play_time == '00:00' or play_time == '0:00':
                continue

            player_info = p.get('player', {})
            nombre = extraer_apellido(player_info.get('firstInitialAndLastName', ''))
            dorsal = player_info.get('shirtNumber', '')

            minutos = convertir_minutos(play_time)
            puntos = p.get('points', 0)
            t2_enc = p.get('twoPointersMade', 0)
            t2_int = p.get('twoPointersAttempted', 0)
            t3_enc = p.get('threePointersMade', 0)
            t3_int = p.get('threePointersAttempted', 0)
            tl_enc = p.get('freeThrowsMade', 0)
            tl_int = p.get('freeThrowsAttempted', 0)
            rebotes = p.get('totalRebounds', 0)
            asistencias = p.get('assists', 0)
            valoracion = p.get('rating', 0)
            titular = p.get('isStarted', False)

            players.append({
                'dorsal': dorsal,
                'nombre': nombre,
                'minutos': minutos,
                'puntos': str(puntos),
                't2_enc': t2_enc, 't2_int': t2_int,
                't3_enc': t3_enc, 't3_int': t3_int,
                'tl_enc': tl_enc, 'tl_int': tl_int,
                'rebotes': str(rebotes),
                'asistencias': str(asistencias),
                'valoracion': str(valoracion),
                'titular': titular,
            })

        teams_data.append({
            'nombre': team_name,
            'puntuacion': str(team_points),
            'jugadores': players,
            'entrenador': head_coach,
            'periods': periods,
            'team_rebotes_extra': team_rebotes_extra,
            'team_valoracion_extra': team_valoracion_extra,
            'num_ot': num_ot,
        })

    parciales_parts = []
    if len(teams_data) == 2:
        t1_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[0]['periods']}
        t2_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[1]['periods']}
        quarters = sorted(q for q in t1_periods if q > 0)
        for q in quarters:
            parciales_parts.append(f"{t1_periods[q]}-{t2_periods[q]}")

    info_adicional = {
        'parciales': ' '.join(parciales_parts),
        'arbitros': ', '.join(data.get('referees', [])),
    }

    return teams_data, info_adicional


def td_val(parent, value):
    td = ET.SubElement(parent, 'td')
    if value and value != '0':
        td.text = value
    return td


def td_tiro(parent, enc, intentos):
    td = ET.SubElement(parent, 'td')
    fmt = convertir_tiros_formato(enc, intentos)
    if fmt:
        td.text = fmt
    return td


def create_xml(teams_data, info_adicional):
    doc = ET.Element('doc')
    doc.set('xml:lang', 'es')

    story = ET.SubElement(doc, 'story')
    text_el = ET.SubElement(story, 'text')
    content = ET.SubElement(text_el, 'content')

    for team in teams_data:
        table = ET.SubElement(content, 'table')
        table.set('class', 'fichabas_auto')

        header_row = ET.SubElement(table, 'tr')
        header_cell = ET.SubElement(header_row, 'td')
        header_cell.set('colspan', '11')
        header_cell.set('class', 'cabecera')
        header_cell.text = f"{team['nombre']}, {team['puntuacion']}"

        titles_row = ET.SubElement(table, 'tr')
        titles_row.set('class', 'valores titulos')
        for title in ['', 'Jugador', 'PTS', '2P', '3P', 'TL', 'RT', 'AS', 'MJ', 'V', '']:
            td = ET.SubElement(titles_row, 'td')
            if title:
                td.text = title

        totales = {
            'puntos': 0,
            't2_enc': 0, 't2_int': 0,
            't3_enc': 0, 't3_int': 0,
            'tl_enc': 0, 'tl_int': 0,
            'rebotes': 0,
            'asistencias': 0,
            'valoracion': 0,
        }

        jugadores_con_relleno = list(team['jugadores'])
        while len(jugadores_con_relleno) < 12:
            jugadores_con_relleno.append(None)

        for player in jugadores_con_relleno:
            row = ET.SubElement(table, 'tr')
            row.set('class', 'valores')

            if player is None:
                for _ in range(11):
                    ET.SubElement(row, 'td')
            else:
                ET.SubElement(row, 'td')

                nombre_cell = ET.SubElement(row, 'td')
                if player.get('titular', False):
                    span = ET.SubElement(nombre_cell, 'span')
                    span.set('class', 'negrita jug')
                    span.text = player['nombre']
                else:
                    nombre_cell.text = player['nombre']

                td_val(row, player['puntos'])
                td_tiro(row, player['t2_enc'], player['t2_int'])
                td_tiro(row, player['t3_enc'], player['t3_int'])
                td_tiro(row, player['tl_enc'], player['tl_int'])
                td_val(row, player['rebotes'])
                td_val(row, player['asistencias'])

                mj_td = ET.SubElement(row, 'td')
                mj_td.text = player['minutos']

                val_td = ET.SubElement(row, 'td')
                val_td.text = player['valoracion']

                ET.SubElement(row, 'td')

                try:
                    totales['puntos'] += int(player['puntos'])
                except (ValueError, TypeError):
                    pass

                totales['t2_enc'] += player['t2_enc']
                totales['t2_int'] += player['t2_int']
                totales['t3_enc'] += player['t3_enc']
                totales['t3_int'] += player['t3_int']
                totales['tl_enc'] += player['tl_enc']
                totales['tl_int'] += player['tl_int']

                try:
                    totales['rebotes'] += int(player['rebotes'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['asistencias'] += int(player['asistencias'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['valoracion'] += int(player['valoracion'])
                except (ValueError, TypeError):
                    pass

        tot_row = ET.SubElement(table, 'tr')
        tot_row.set('class', 'totales')
        ET.SubElement(tot_row, 'td')
        ET.SubElement(tot_row, 'td').text = 'Totales'
        ET.SubElement(tot_row, 'td').text = str(totales['puntos'])

        def tot_tiro_td(parent, enc, int_v):
            td = ET.SubElement(parent, 'td')
            td.text = f"{enc}-{int_v}" if int_v > 0 else ''
            return td

        tot_tiro_td(tot_row, totales['t2_enc'], totales['t2_int'])
        tot_tiro_td(tot_row, totales['t3_enc'], totales['t3_int'])
        tot_tiro_td(tot_row, totales['tl_enc'], totales['tl_int'])

        total_rebotes = totales['rebotes'] + team.get('team_rebotes_extra', 0)
        total_valoracion = totales['valoracion'] + team.get('team_valoracion_extra', 0)
        minutos_partido = 200 + team.get('num_ot', 0) * 25

        td_reb = ET.SubElement(tot_row, 'td')
        td_reb.text = str(total_rebotes) if total_rebotes > 0 else ''

        td_ast = ET.SubElement(tot_row, 'td')
        td_ast.text = str(totales['asistencias']) if totales['asistencias'] > 0 else ''

        ET.SubElement(tot_row, 'td').text = str(minutos_partido)
        ET.SubElement(tot_row, 'td').text = str(total_valoracion)
        ET.SubElement(tot_row, 'td')

        is_last_team = (team is teams_data[-1])

        entr_row = ET.SubElement(table, 'tr')
        entr_row.set('class', 'margenesfilete')
        ET.SubElement(entr_row, 'td')
        entr_lbl = ET.SubElement(entr_row, 'td')
        entr_lbl.set('class', 'negrita')
        entr_lbl.text = 'Entrenador:'
        entr_val = ET.SubElement(entr_row, 'td')
        entr_val.set('class', 'left')
        entr_val.set('colspan', '8')
        entr_val.text = f"\u2002{team.get('entrenador', '')}"
        ET.SubElement(entr_row, 'td')

        if is_last_team:
            def add_info_row(parent, label, value=''):
                row = ET.SubElement(parent, 'tr')
                row.set('class', 'margenesfilete')
                ET.SubElement(row, 'td')
                cell = ET.SubElement(row, 'td')
                cell.set('class', 'left')
                cell.set('colspan', '9')
                span = ET.SubElement(cell, 'span')
                span.set('class', 'negrita')
                span.text = label
                span.tail = value
                ET.SubElement(row, 'td')
                return row

            add_info_row(table, 'Parciales: ', info_adicional.get('parciales', ''))
            add_info_row(table, 'Árbitros: ', info_adicional.get('arbitros', ''))

            cab = ET.SubElement(table, 'tr')
            cab_cell = ET.SubElement(cab, 'td')
            cab_cell.set('class', 'rojo')
            cab_cell.set('colspan', '11')

    xml_string = ET.tostring(doc, encoding='utf-8', method='xml')
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent='\t', encoding='utf-8')
    return pretty_xml


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        match_id = str(data.get('matchId', '')).strip()

        if not match_id:
            return jsonify({'error': 'Por favor, introduce el número de partido'}), 400

        try:
            api_data = fetch_match_data(match_id)
        except Exception as e:
            return jsonify({'error': f'Error al conectar con la API de ACB: {str(e)}'}), 502

        teams_data, info_adicional = parse_api_data(api_data)

        if not teams_data:
            return jsonify({'error': 'No se encontraron datos para este partido'}), 404

        xml_content = create_xml(teams_data, info_adicional)
        xml_str = xml_content.decode('utf-8')

        return jsonify({'success': True, 'xml': xml_str})

    except Exception as e:
        return jsonify({'error': f'Error al generar el XML: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
from flask import Flask, render_template, request, jsonify
import xml.etree.ElementTree as ET
from xml.dom import minidom
import urllib.request
import json

app = Flask(__name__)

ACB_HEADERS = {
    'x-apikey': '0dd94928-6f57-4c08-a3bd-b1b2f092976e',
    'origin': 'https://live.acb.com',
    'referer': 'https://live.acb.com/',
}


def convertir_tiros_formato(enc, intentos):
    if enc == 0 and intentos == 0:
        return ''
    return f"{enc}-{intentos}"


def convertir_minutos(minutos_str):
    if ':' in minutos_str:
        parts = minutos_str.split(':')
        mins = int(parts[0])
        secs = int(parts[1]) if len(parts) > 1 else 0
        result = round(mins + secs / 60)
        if result == 0 and secs > 0:
            result = 1
        return str(result)
    return minutos_str


def extraer_apellido(first_initial_and_last):
    if '. ' in first_initial_and_last:
        return first_initial_and_last.split('. ', 1)[1]
    return first_initial_and_last


def fetch_match_data(match_id):
    url = f'https://api2.acb.com/api/matchdata/Result/boxscores?matchId={match_id}'
    req = urllib.request.Request(url)
    for k, v in ACB_HEADERS.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def parse_api_data(data):
    teams_data = []

    for team_box in data.get('teamBoxscores', []):
        team_info = team_box.get('team', {})
        team_name = team_info.get('fullName', '')

        head_coach = team_box.get('headCoach', '')

        periods = team_box.get('statsByPeriods', [])

        total_period = next((p for p in periods if p['quarter'] == 0), None)
        if total_period is None:
            continue

        team_points = total_period['stats']['total']['points']
        team_stats = total_period['stats'].get('team', {})
        team_rebotes_extra = team_stats.get('totalRebounds', 0)
        team_valoracion_extra = team_stats.get('rating', 0)

        num_ot = sum(1 for p in periods if p['quarter'] > 4)

        players_raw = total_period['stats']['players']

        starters = [p for p in players_raw if p.get('isStarted')]
        bench = [p for p in players_raw if not p.get('isStarted')]
        ordered_players = starters + bench

        players = []
        for p in ordered_players:
            play_time = p.get('playTime', '00:00')
            if play_time == '00:00' or play_time == '0:00':
                continue

            player_info = p.get('player', {})
            nombre = extraer_apellido(player_info.get('firstInitialAndLastName', ''))
            dorsal = player_info.get('shirtNumber', '')

            minutos = convertir_minutos(play_time)
            puntos = p.get('points', 0)
            t2_enc = p.get('twoPointersMade', 0)
            t2_int = p.get('twoPointersAttempted', 0)
            t3_enc = p.get('threePointersMade', 0)
            t3_int = p.get('threePointersAttempted', 0)
            tl_enc = p.get('freeThrowsMade', 0)
            tl_int = p.get('freeThrowsAttempted', 0)
            rebotes = p.get('totalRebounds', 0)
            asistencias = p.get('assists', 0)
            valoracion = p.get('rating', 0)
            titular = p.get('isStarted', False)

            players.append({
                'dorsal': dorsal,
                'nombre': nombre,
                'minutos': minutos,
                'puntos': str(puntos),
                't2_enc': t2_enc, 't2_int': t2_int,
                't3_enc': t3_enc, 't3_int': t3_int,
                'tl_enc': tl_enc, 'tl_int': tl_int,
                'rebotes': str(rebotes),
                'asistencias': str(asistencias),
                'valoracion': str(valoracion),
                'titular': titular,
            })

        teams_data.append({
            'nombre': team_name,
            'puntuacion': str(team_points),
            'jugadores': players,
            'entrenador': head_coach,
            'periods': periods,
            'team_rebotes_extra': team_rebotes_extra,
            'team_valoracion_extra': team_valoracion_extra,
            'num_ot': num_ot,
        })

    parciales_parts = []
    if len(teams_data) == 2:
        t1_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[0]['periods']}
        t2_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[1]['periods']}
        quarters = sorted(q for q in t1_periods if q > 0)
        for q in quarters:
            parciales_parts.append(f"{t1_periods[q]}-{t2_periods[q]}")

    info_adicional = {
        'parciales': ' '.join(parciales_parts),
        'arbitros': ', '.join(data.get('referees', [])),
    }

    return teams_data, info_adicional


def td_val(parent, value):
    td = ET.SubElement(parent, 'td')
    if value and value != '0':
        td.text = value
    return td


def td_tiro(parent, enc, intentos):
    td = ET.SubElement(parent, 'td')
    fmt = convertir_tiros_formato(enc, intentos)
    if fmt:
        td.text = fmt
    return td


def create_xml(teams_data, info_adicional):
    doc = ET.Element('doc')
    doc.set('xml:lang', 'es')

    story = ET.SubElement(doc, 'story')
    text_el = ET.SubElement(story, 'text')
    content = ET.SubElement(text_el, 'content')

    for team in teams_data:
        table = ET.SubElement(content, 'table')
        table.set('class', 'fichabas_auto')

        header_row = ET.SubElement(table, 'tr')
        header_cell = ET.SubElement(header_row, 'td')
        header_cell.set('colspan', '11')
        header_cell.set('class', 'cabecera')
        header_cell.text = f"{team['nombre']}, {team['puntuacion']}"

        titles_row = ET.SubElement(table, 'tr')
        titles_row.set('class', 'valores titulos')
        for title in ['', 'Jugador', 'PTS', '2P', '3P', 'TL', 'RT', 'AS', 'MJ', 'V', '']:
            td = ET.SubElement(titles_row, 'td')
            if title:
                td.text = title

        totales = {
            'puntos': 0,
            't2_enc': 0, 't2_int': 0,
            't3_enc': 0, 't3_int': 0,
            'tl_enc': 0, 'tl_int': 0,
            'rebotes': 0,
            'asistencias': 0,
            'valoracion': 0,
        }

        jugadores_con_relleno = list(team['jugadores'])
        while len(jugadores_con_relleno) < 12:
            jugadores_con_relleno.append(None)

        for player in jugadores_con_relleno:
            row = ET.SubElement(table, 'tr')
            row.set('class', 'valores')

            if player is None:
                for _ in range(11):
                    ET.SubElement(row, 'td')
            else:
                ET.SubElement(row, 'td')

                nombre_cell = ET.SubElement(row, 'td')
                if player.get('titular', False):
                    span = ET.SubElement(nombre_cell, 'span')
                    span.set('class', 'negrita jug')
                    span.text = player['nombre']
                else:
                    nombre_cell.text = player['nombre']

                td_val(row, player['puntos'])
                td_tiro(row, player['t2_enc'], player['t2_int'])
                td_tiro(row, player['t3_enc'], player['t3_int'])
                td_tiro(row, player['tl_enc'], player['tl_int'])
                td_val(row, player['rebotes'])
                td_val(row, player['asistencias'])

                mj_td = ET.SubElement(row, 'td')
                mj_td.text = player['minutos']

                val_td = ET.SubElement(row, 'td')
                val_td.text = player['valoracion']

                ET.SubElement(row, 'td')

                try:
                    totales['puntos'] += int(player['puntos'])
                except (ValueError, TypeError):
                    pass

                totales['t2_enc'] += player['t2_enc']
                totales['t2_int'] += player['t2_int']
                totales['t3_enc'] += player['t3_enc']
                totales['t3_int'] += player['t3_int']
                totales['tl_enc'] += player['tl_enc']
                totales['tl_int'] += player['tl_int']

                try:
                    totales['rebotes'] += int(player['rebotes'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['asistencias'] += int(player['asistencias'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['valoracion'] += int(player['valoracion'])
                except (ValueError, TypeError):
                    pass

        tot_row = ET.SubElement(table, 'tr')
        tot_row.set('class', 'totales')
        ET.SubElement(tot_row, 'td')
        ET.SubElement(tot_row, 'td').text = 'Totales'
        ET.SubElement(tot_row, 'td').text = str(totales['puntos'])

        def tot_tiro_td(parent, enc, int_v):
            td = ET.SubElement(parent, 'td')
            td.text = f"{enc}-{int_v}" if int_v > 0 else ''
            return td

        tot_tiro_td(tot_row, totales['t2_enc'], totales['t2_int'])
        tot_tiro_td(tot_row, totales['t3_enc'], totales['t3_int'])
        tot_tiro_td(tot_row, totales['tl_enc'], totales['tl_int'])

        total_rebotes = totales['rebotes'] + team.get('team_rebotes_extra', 0)
        total_valoracion = totales['valoracion'] + team.get('team_valoracion_extra', 0)
        minutos_partido = 200 + team.get('num_ot', 0) * 25

        td_reb = ET.SubElement(tot_row, 'td')
        td_reb.text = str(total_rebotes) if total_rebotes > 0 else ''

        td_ast = ET.SubElement(tot_row, 'td')
        td_ast.text = str(totales['asistencias']) if totales['asistencias'] > 0 else ''

        ET.SubElement(tot_row, 'td').text = str(minutos_partido)
        ET.SubElement(tot_row, 'td').text = str(total_valoracion)
        ET.SubElement(tot_row, 'td')

        is_last_team = (team is teams_data[-1])

        entr_row = ET.SubElement(table, 'tr')
        entr_row.set('class', 'margenesfilete')
        ET.SubElement(entr_row, 'td')
        entr_lbl = ET.SubElement(entr_row, 'td')
        entr_lbl.set('class', 'negrita')
        entr_lbl.text = 'Entrenador:'
        entr_val = ET.SubElement(entr_row, 'td')
        entr_val.set('class', 'left')
        entr_val.set('colspan', '8')
        entr_val.text = f"\u2002{team.get('entrenador', '')}"
        ET.SubElement(entr_row, 'td')

        if is_last_team:
            def add_info_row(parent, label, value=''):
                row = ET.SubElement(parent, 'tr')
                row.set('class', 'margenesfilete')
                ET.SubElement(row, 'td')
                cell = ET.SubElement(row, 'td')
                cell.set('class', 'left')
                cell.set('colspan', '9')
                span = ET.SubElement(cell, 'span')
                span.set('class', 'negrita')
                span.text = label
                span.tail = value
                ET.SubElement(row, 'td')
                return row

            add_info_row(table, 'Parciales: ', info_adicional.get('parciales', ''))
            add_info_row(table, 'Árbitros: ', info_adicional.get('arbitros', ''))

            cab = ET.SubElement(table, 'tr')
            cab_cell = ET.SubElement(cab, 'td')
            cab_cell.set('class', 'rojo')
            cab_cell.set('colspan', '11')

    xml_string = ET.tostring(doc, encoding='utf-8', method='xml')
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent='\t', encoding='utf-8')
    return pretty_xml


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        match_id = str(data.get('matchId', '')).strip()

        if not match_id:
            return jsonify({'error': 'Por favor, introduce el número de partido'}), 400

        try:
            api_data = fetch_match_data(match_id)
        except Exception as e:
            return jsonify({'error': f'Error al conectar con la API de ACB: {str(e)}'}), 502

        teams_data, info_adicional = parse_api_data(api_data)

        if not teams_data:
            return jsonify({'error': 'No se encontraron datos para este partido'}), 404

        xml_content = create_xml(teams_data, info_adicional)
        xml_str = xml_content.decode('utf-8')

        return jsonify({'success': True, 'xml': xml_str})

    except Exception as e:
        return jsonify({'error': f'Error al generar el XML: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
from flask import Flask, render_template, request, jsonify
import xml.etree.ElementTree as ET
from xml.dom import minidom
import urllib.request
import json

app = Flask(__name__)

ACB_HEADERS = {
    'x-apikey': '0dd94928-6f57-4c08-a3bd-b1b2f092976e',
    'origin': 'https://live.acb.com',
    'referer': 'https://live.acb.com/',
}


def convertir_tiros_formato(enc, intentos):
    if enc == 0 and intentos == 0:
        return ''
    return f"{enc}-{intentos}"


def convertir_minutos(minutos_str):
    if ':' in minutos_str:
        parts = minutos_str.split(':')
        mins = int(parts[0])
        secs = int(parts[1]) if len(parts) > 1 else 0
        result = round(mins + secs / 60)
        if result == 0 and secs > 0:
            result = 1
        return str(result)
    return minutos_str


def extraer_apellido(first_initial_and_last):
    if '. ' in first_initial_and_last:
        return first_initial_and_last.split('. ', 1)[1]
    return first_initial_and_last


def fetch_match_data(match_id):
    url = f'https://api2.acb.com/api/matchdata/Result/boxscores?matchId={match_id}'
    req = urllib.request.Request(url)
    for k, v in ACB_HEADERS.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def parse_api_data(data):
    teams_data = []

    for team_box in data.get('teamBoxscores', []):
        team_info = team_box.get('team', {})
        team_name = team_info.get('fullName', '')

        head_coach = team_box.get('headCoach', '')

        periods = team_box.get('statsByPeriods', [])

        total_period = next((p for p in periods if p['quarter'] == 0), None)
        if total_period is None:
            continue

        team_points = total_period['stats']['total']['points']
        team_stats = total_period['stats'].get('team', {})
        team_rebotes_extra = team_stats.get('totalRebounds', 0)
        team_valoracion_extra = team_stats.get('rating', 0)

        num_ot = sum(1 for p in periods if p['quarter'] > 4)

        players_raw = total_period['stats']['players']

        starters = [p for p in players_raw if p.get('isStarted')]
        bench = [p for p in players_raw if not p.get('isStarted')]
        ordered_players = starters + bench

        players = []
        for p in ordered_players:
            play_time = p.get('playTime', '00:00')
            if play_time == '00:00' or play_time == '0:00':
                continue

            player_info = p.get('player', {})
            nombre = extraer_apellido(player_info.get('firstInitialAndLastName', ''))
            dorsal = player_info.get('shirtNumber', '')

            minutos = convertir_minutos(play_time)
            puntos = p.get('points', 0)
            t2_enc = p.get('twoPointersMade', 0)
            t2_int = p.get('twoPointersAttempted', 0)
            t3_enc = p.get('threePointersMade', 0)
            t3_int = p.get('threePointersAttempted', 0)
            tl_enc = p.get('freeThrowsMade', 0)
            tl_int = p.get('freeThrowsAttempted', 0)
            rebotes = p.get('totalRebounds', 0)
            asistencias = p.get('assists', 0)
            valoracion = p.get('rating', 0)
            titular = p.get('isStarted', False)

            players.append({
                'dorsal': dorsal,
                'nombre': nombre,
                'minutos': minutos,
                'puntos': str(puntos),
                't2_enc': t2_enc, 't2_int': t2_int,
                't3_enc': t3_enc, 't3_int': t3_int,
                'tl_enc': tl_enc, 'tl_int': tl_int,
                'rebotes': str(rebotes),
                'asistencias': str(asistencias),
                'valoracion': str(valoracion),
                'titular': titular,
            })

        teams_data.append({
            'nombre': team_name,
            'puntuacion': str(team_points),
            'jugadores': players,
            'entrenador': head_coach,
            'periods': periods,
            'team_rebotes_extra': team_rebotes_extra,
            'team_valoracion_extra': team_valoracion_extra,
            'num_ot': num_ot,
        })

    parciales_parts = []
    if len(teams_data) == 2:
        t1_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[0]['periods']}
        t2_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[1]['periods']}
        quarters = sorted(q for q in t1_periods if q > 0)
        for q in quarters:
            parciales_parts.append(f"{t1_periods[q]}-{t2_periods[q]}")

    info_adicional = {
        'parciales': ' '.join(parciales_parts),
        'arbitros': ', '.join(data.get('referees', [])),
    }

    return teams_data, info_adicional


def td_val(parent, value):
    td = ET.SubElement(parent, 'td')
    if value and value != '0':
        td.text = value
    return td


def td_tiro(parent, enc, intentos):
    td = ET.SubElement(parent, 'td')
    fmt = convertir_tiros_formato(enc, intentos)
    if fmt:
        td.text = fmt
    return td


def create_xml(teams_data, info_adicional):
    doc = ET.Element('doc')
    doc.set('xml:lang', 'es')

    story = ET.SubElement(doc, 'story')
    text_el = ET.SubElement(story, 'text')
    content = ET.SubElement(text_el, 'content')

    for team in teams_data:
        table = ET.SubElement(content, 'table')
        table.set('class', 'fichabas_auto')

        header_row = ET.SubElement(table, 'tr')
        header_cell = ET.SubElement(header_row, 'td')
        header_cell.set('colspan', '11')
        header_cell.set('class', 'cabecera')
        header_cell.text = f"{team['nombre']}, {team['puntuacion']}"

        titles_row = ET.SubElement(table, 'tr')
        titles_row.set('class', 'valores titulos')
        for title in ['', 'Jugador', 'PTS', '2P', '3P', 'TL', 'RT', 'AS', 'MJ', 'V', '']:
            td = ET.SubElement(titles_row, 'td')
            if title:
                td.text = title

        totales = {
            'puntos': 0,
            't2_enc': 0, 't2_int': 0,
            't3_enc': 0, 't3_int': 0,
            'tl_enc': 0, 'tl_int': 0,
            'rebotes': 0,
            'asistencias': 0,
            'valoracion': 0,
        }

        jugadores_con_relleno = list(team['jugadores'])
        while len(jugadores_con_relleno) < 12:
            jugadores_con_relleno.append(None)

        for player in jugadores_con_relleno:
            row = ET.SubElement(table, 'tr')
            row.set('class', 'valores')

            if player is None:
                for _ in range(11):
                    ET.SubElement(row, 'td')
            else:
                ET.SubElement(row, 'td')

                nombre_cell = ET.SubElement(row, 'td')
                if player.get('titular', False):
                    span = ET.SubElement(nombre_cell, 'span')
                    span.set('class', 'negrita jug')
                    span.text = player['nombre']
                else:
                    nombre_cell.text = player['nombre']

                td_val(row, player['puntos'])
                td_tiro(row, player['t2_enc'], player['t2_int'])
                td_tiro(row, player['t3_enc'], player['t3_int'])
                td_tiro(row, player['tl_enc'], player['tl_int'])
                td_val(row, player['rebotes'])
                td_val(row, player['asistencias'])

                mj_td = ET.SubElement(row, 'td')
                mj_td.text = player['minutos']

                val_td = ET.SubElement(row, 'td')
                val_td.text = player['valoracion']

                ET.SubElement(row, 'td')

                try:
                    totales['puntos'] += int(player['puntos'])
                except (ValueError, TypeError):
                    pass

                totales['t2_enc'] += player['t2_enc']
                totales['t2_int'] += player['t2_int']
                totales['t3_enc'] += player['t3_enc']
                totales['t3_int'] += player['t3_int']
                totales['tl_enc'] += player['tl_enc']
                totales['tl_int'] += player['tl_int']

                try:
                    totales['rebotes'] += int(player['rebotes'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['asistencias'] += int(player['asistencias'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['valoracion'] += int(player['valoracion'])
                except (ValueError, TypeError):
                    pass

        tot_row = ET.SubElement(table, 'tr')
        tot_row.set('class', 'totales')
        ET.SubElement(tot_row, 'td')
        ET.SubElement(tot_row, 'td').text = 'Totales'
        ET.SubElement(tot_row, 'td').text = str(totales['puntos'])

        def tot_tiro_td(parent, enc, int_v):
            td = ET.SubElement(parent, 'td')
            td.text = f"{enc}-{int_v}" if int_v > 0 else ''
            return td

        tot_tiro_td(tot_row, totales['t2_enc'], totales['t2_int'])
        tot_tiro_td(tot_row, totales['t3_enc'], totales['t3_int'])
        tot_tiro_td(tot_row, totales['tl_enc'], totales['tl_int'])

        total_rebotes = totales['rebotes'] + team.get('team_rebotes_extra', 0)
        total_valoracion = totales['valoracion'] + team.get('team_valoracion_extra', 0)
        minutos_partido = 200 + team.get('num_ot', 0) * 25

        td_reb = ET.SubElement(tot_row, 'td')
        td_reb.text = str(total_rebotes) if total_rebotes > 0 else ''

        td_ast = ET.SubElement(tot_row, 'td')
        td_ast.text = str(totales['asistencias']) if totales['asistencias'] > 0 else ''

        ET.SubElement(tot_row, 'td').text = str(minutos_partido)
        ET.SubElement(tot_row, 'td').text = str(total_valoracion)
        ET.SubElement(tot_row, 'td')

        is_last_team = (team is teams_data[-1])

        entr_row = ET.SubElement(table, 'tr')
        entr_row.set('class', 'margenesfilete')
        ET.SubElement(entr_row, 'td')
        entr_lbl = ET.SubElement(entr_row, 'td')
        entr_lbl.set('class', 'negrita')
        entr_lbl.text = 'Entrenador:'
        entr_val = ET.SubElement(entr_row, 'td')
        entr_val.set('class', 'left')
        entr_val.set('colspan', '8')
        entr_val.text = f"\u2002{team.get('entrenador', '')}"
        ET.SubElement(entr_row, 'td')

        if is_last_team:
            def add_info_row(parent, label, value=''):
                row = ET.SubElement(parent, 'tr')
                row.set('class', 'margenesfilete')
                ET.SubElement(row, 'td')
                cell = ET.SubElement(row, 'td')
                cell.set('class', 'left')
                cell.set('colspan', '9')
                span = ET.SubElement(cell, 'span')
                span.set('class', 'negrita')
                span.text = label
                span.tail = value
                ET.SubElement(row, 'td')
                return row

            add_info_row(table, 'Parciales: ', info_adicional.get('parciales', ''))
            add_info_row(table, 'Árbitros: ', info_adicional.get('arbitros', ''))

            cab = ET.SubElement(table, 'tr')
            cab_cell = ET.SubElement(cab, 'td')
            cab_cell.set('class', 'rojo')
            cab_cell.set('colspan', '11')

    xml_string = ET.tostring(doc, encoding='utf-8', method='xml')
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent='\t', encoding='utf-8')
    return pretty_xml


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        match_id = str(data.get('matchId', '')).strip()

        if not match_id:
            return jsonify({'error': 'Por favor, introduce el número de partido'}), 400

        try:
            api_data = fetch_match_data(match_id)
        except Exception as e:
            return jsonify({'error': f'Error al conectar con la API de ACB: {str(e)}'}), 502

        teams_data, info_adicional = parse_api_data(api_data)

        if not teams_data:
            return jsonify({'error': 'No se encontraron datos para este partido'}), 404

        xml_content = create_xml(teams_data, info_adicional)
        xml_str = xml_content.decode('utf-8')

        return jsonify({'success': True, 'xml': xml_str})

    except Exception as e:
        return jsonify({'error': f'Error al generar el XML: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
from flask import Flask, render_template, request, jsonify
import xml.etree.ElementTree as ET
from xml.dom import minidom
import urllib.request
import json

app = Flask(__name__)

ACB_HEADERS = {
    'x-apikey': '0dd94928-6f57-4c08-a3bd-b1b2f092976e',
    'origin': 'https://live.acb.com',
    'referer': 'https://live.acb.com/',
}


def convertir_tiros_formato(enc, intentos):
    if enc == 0 and intentos == 0:
        return ''
    return f"{enc}-{intentos}"


def convertir_minutos(minutos_str):
    if ':' in minutos_str:
        parts = minutos_str.split(':')
        mins = int(parts[0])
        secs = int(parts[1]) if len(parts) > 1 else 0
        result = round(mins + secs / 60)
        if result == 0 and secs > 0:
            result = 1
        return str(result)
    return minutos_str


def extraer_apellido(first_initial_and_last):
    if '. ' in first_initial_and_last:
        return first_initial_and_last.split('. ', 1)[1]
    return first_initial_and_last


def fetch_match_data(match_id):
    url = f'https://api2.acb.com/api/matchdata/Result/boxscores?matchId={match_id}'
    req = urllib.request.Request(url)
    for k, v in ACB_HEADERS.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def parse_api_data(data):
    teams_data = []

    for team_box in data.get('teamBoxscores', []):
        team_info = team_box.get('team', {})
        team_name = team_info.get('fullName', '')

        head_coach = team_box.get('headCoach', '')

        periods = team_box.get('statsByPeriods', [])

        total_period = next((p for p in periods if p['quarter'] == 0), None)
        if total_period is None:
            continue

        team_points = total_period['stats']['total']['points']
        team_stats = total_period['stats'].get('team', {})
        team_rebotes_extra = team_stats.get('totalRebounds', 0)
        team_valoracion_extra = team_stats.get('rating', 0)

        num_ot = sum(1 for p in periods if p['quarter'] > 4)

        players_raw = total_period['stats']['players']

        starters = [p for p in players_raw if p.get('isStarted')]
        bench = [p for p in players_raw if not p.get('isStarted')]
        ordered_players = starters + bench

        players = []
        for p in ordered_players:
            play_time = p.get('playTime', '00:00')
            if play_time == '00:00' or play_time == '0:00':
                continue

            player_info = p.get('player', {})
            nombre = extraer_apellido(player_info.get('firstInitialAndLastName', ''))
            dorsal = player_info.get('shirtNumber', '')

            minutos = convertir_minutos(play_time)
            puntos = p.get('points', 0)
            t2_enc = p.get('twoPointersMade', 0)
            t2_int = p.get('twoPointersAttempted', 0)
            t3_enc = p.get('threePointersMade', 0)
            t3_int = p.get('threePointersAttempted', 0)
            tl_enc = p.get('freeThrowsMade', 0)
            tl_int = p.get('freeThrowsAttempted', 0)
            rebotes = p.get('totalRebounds', 0)
            asistencias = p.get('assists', 0)
            valoracion = p.get('rating', 0)
            titular = p.get('isStarted', False)

            players.append({
                'dorsal': dorsal,
                'nombre': nombre,
                'minutos': minutos,
                'puntos': str(puntos),
                't2_enc': t2_enc, 't2_int': t2_int,
                't3_enc': t3_enc, 't3_int': t3_int,
                'tl_enc': tl_enc, 'tl_int': tl_int,
                'rebotes': str(rebotes),
                'asistencias': str(asistencias),
                'valoracion': str(valoracion),
                'titular': titular,
            })

        teams_data.append({
            'nombre': team_name,
            'puntuacion': str(team_points),
            'jugadores': players,
            'entrenador': head_coach,
            'periods': periods,
            'team_rebotes_extra': team_rebotes_extra,
            'team_valoracion_extra': team_valoracion_extra,
            'num_ot': num_ot,
        })

    parciales_parts = []
    if len(teams_data) == 2:
        t1_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[0]['periods']}
        t2_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[1]['periods']}
        quarters = sorted(q for q in t1_periods if q > 0)
        for q in quarters:
            parciales_parts.append(f"{t1_periods[q]}-{t2_periods[q]}")

    info_adicional = {
        'parciales': ' '.join(parciales_parts),
        'arbitros': ', '.join(data.get('referees', [])),
    }

    return teams_data, info_adicional


def td_val(parent, value):
    td = ET.SubElement(parent, 'td')
    if value and value != '0':
        td.text = value
    return td


def td_tiro(parent, enc, intentos):
    td = ET.SubElement(parent, 'td')
    fmt = convertir_tiros_formato(enc, intentos)
    if fmt:
        td.text = fmt
    return td


def create_xml(teams_data, info_adicional):
    doc = ET.Element('doc')
    doc.set('xml:lang', 'es')

    story = ET.SubElement(doc, 'story')
    text_el = ET.SubElement(story, 'text')
    content = ET.SubElement(text_el, 'content')

    for team in teams_data:
        table = ET.SubElement(content, 'table')
        table.set('class', 'fichabas_auto')

        header_row = ET.SubElement(table, 'tr')
        header_cell = ET.SubElement(header_row, 'td')
        header_cell.set('colspan', '11')
        header_cell.set('class', 'cabecera')
        header_cell.text = f"{team['nombre']}, {team['puntuacion']}"

        titles_row = ET.SubElement(table, 'tr')
        titles_row.set('class', 'valores titulos')
        for title in ['', 'Jugador', 'PTS', '2P', '3P', 'TL', 'RT', 'AS', 'MJ', 'V', '']:
            td = ET.SubElement(titles_row, 'td')
            if title:
                td.text = title

        totales = {
            'puntos': 0,
            't2_enc': 0, 't2_int': 0,
            't3_enc': 0, 't3_int': 0,
            'tl_enc': 0, 'tl_int': 0,
            'rebotes': 0,
            'asistencias': 0,
            'valoracion': 0,
        }

        jugadores_con_relleno = list(team['jugadores'])
        while len(jugadores_con_relleno) < 12:
            jugadores_con_relleno.append(None)

        for player in jugadores_con_relleno:
            row = ET.SubElement(table, 'tr')
            row.set('class', 'valores')

            if player is None:
                for _ in range(11):
                    ET.SubElement(row, 'td')
            else:
                ET.SubElement(row, 'td')

                nombre_cell = ET.SubElement(row, 'td')
                if player.get('titular', False):
                    span = ET.SubElement(nombre_cell, 'span')
                    span.set('class', 'negrita jug')
                    span.text = player['nombre']
                else:
                    nombre_cell.text = player['nombre']

                td_val(row, player['puntos'])
                td_tiro(row, player['t2_enc'], player['t2_int'])
                td_tiro(row, player['t3_enc'], player['t3_int'])
                td_tiro(row, player['tl_enc'], player['tl_int'])
                td_val(row, player['rebotes'])
                td_val(row, player['asistencias'])

                mj_td = ET.SubElement(row, 'td')
                mj_td.text = player['minutos']

                val_td = ET.SubElement(row, 'td')
                val_td.text = player['valoracion']

                ET.SubElement(row, 'td')

                try:
                    totales['puntos'] += int(player['puntos'])
                except (ValueError, TypeError):
                    pass

                totales['t2_enc'] += player['t2_enc']
                totales['t2_int'] += player['t2_int']
                totales['t3_enc'] += player['t3_enc']
                totales['t3_int'] += player['t3_int']
                totales['tl_enc'] += player['tl_enc']
                totales['tl_int'] += player['tl_int']

                try:
                    totales['rebotes'] += int(player['rebotes'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['asistencias'] += int(player['asistencias'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['valoracion'] += int(player['valoracion'])
                except (ValueError, TypeError):
                    pass

        tot_row = ET.SubElement(table, 'tr')
        tot_row.set('class', 'totales')
        ET.SubElement(tot_row, 'td')
        ET.SubElement(tot_row, 'td').text = 'Totales'
        ET.SubElement(tot_row, 'td').text = str(totales['puntos'])

        def tot_tiro_td(parent, enc, int_v):
            td = ET.SubElement(parent, 'td')
            td.text = f"{enc}-{int_v}" if int_v > 0 else ''
            return td

        tot_tiro_td(tot_row, totales['t2_enc'], totales['t2_int'])
        tot_tiro_td(tot_row, totales['t3_enc'], totales['t3_int'])
        tot_tiro_td(tot_row, totales['tl_enc'], totales['tl_int'])

        total_rebotes = totales['rebotes'] + team.get('team_rebotes_extra', 0)
        total_valoracion = totales['valoracion'] + team.get('team_valoracion_extra', 0)
        minutos_partido = 200 + team.get('num_ot', 0) * 25

        td_reb = ET.SubElement(tot_row, 'td')
        td_reb.text = str(total_rebotes) if total_rebotes > 0 else ''

        td_ast = ET.SubElement(tot_row, 'td')
        td_ast.text = str(totales['asistencias']) if totales['asistencias'] > 0 else ''

        ET.SubElement(tot_row, 'td').text = str(minutos_partido)
        ET.SubElement(tot_row, 'td').text = str(total_valoracion)
        ET.SubElement(tot_row, 'td')

        is_last_team = (team is teams_data[-1])

        entr_row = ET.SubElement(table, 'tr')
        entr_row.set('class', 'margenesfilete')
        ET.SubElement(entr_row, 'td')
        entr_lbl = ET.SubElement(entr_row, 'td')
        entr_lbl.set('class', 'negrita')
        entr_lbl.text = 'Entrenador:'
        entr_val = ET.SubElement(entr_row, 'td')
        entr_val.set('class', 'left')
        entr_val.set('colspan', '8')
        entr_val.text = f"\u2002{team.get('entrenador', '')}"
        ET.SubElement(entr_row, 'td')

        if is_last_team:
            def add_info_row(parent, label, value=''):
                row = ET.SubElement(parent, 'tr')
                row.set('class', 'margenesfilete')
                ET.SubElement(row, 'td')
                cell = ET.SubElement(row, 'td')
                cell.set('class', 'left')
                cell.set('colspan', '9')
                span = ET.SubElement(cell, 'span')
                span.set('class', 'negrita')
                span.text = label
                span.tail = value
                ET.SubElement(row, 'td')
                return row

            add_info_row(table, 'Parciales: ', info_adicional.get('parciales', ''))
            add_info_row(table, 'Árbitros: ', info_adicional.get('arbitros', ''))

            cab = ET.SubElement(table, 'tr')
            cab_cell = ET.SubElement(cab, 'td')
            cab_cell.set('class', 'rojo')
            cab_cell.set('colspan', '11')

    xml_string = ET.tostring(doc, encoding='utf-8', method='xml')
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent='\t', encoding='utf-8')
    return pretty_xml


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        match_id = str(data.get('matchId', '')).strip()

        if not match_id:
            return jsonify({'error': 'Por favor, introduce el número de partido'}), 400

        try:
            api_data = fetch_match_data(match_id)
        except Exception as e:
            return jsonify({'error': f'Error al conectar con la API de ACB: {str(e)}'}), 502

        teams_data, info_adicional = parse_api_data(api_data)

        if not teams_data:
            return jsonify({'error': 'No se encontraron datos para este partido'}), 404

        xml_content = create_xml(teams_data, info_adicional)
        xml_str = xml_content.decode('utf-8')

        return jsonify({'success': True, 'xml': xml_str})

    except Exception as e:
        return jsonify({'error': f'Error al generar el XML: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
from flask import Flask, render_template, request, jsonify
import xml.etree.ElementTree as ET
from xml.dom import minidom
import urllib.request
import json

app = Flask(__name__)

ACB_HEADERS = {
    'x-apikey': '0dd94928-6f57-4c08-a3bd-b1b2f092976e',
    'origin': 'https://live.acb.com',
    'referer': 'https://live.acb.com/',
}


def convertir_tiros_formato(enc, intentos):
    if enc == 0 and intentos == 0:
        return ''
    return f"{enc}-{intentos}"


def convertir_minutos(minutos_str):
    if ':' in minutos_str:
        parts = minutos_str.split(':')
        mins = int(parts[0])
        secs = int(parts[1]) if len(parts) > 1 else 0
        result = round(mins + secs / 60)
        if result == 0 and secs > 0:
            result = 1
        return str(result)
    return minutos_str


def extraer_apellido(first_initial_and_last):
    if '. ' in first_initial_and_last:
        return first_initial_and_last.split('. ', 1)[1]
    return first_initial_and_last


def fetch_match_data(match_id):
    url = f'https://api2.acb.com/api/matchdata/Result/boxscores?matchId={match_id}'
    req = urllib.request.Request(url)
    for k, v in ACB_HEADERS.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def parse_api_data(data):
    teams_data = []

    for team_box in data.get('teamBoxscores', []):
        team_info = team_box.get('team', {})
        team_name = team_info.get('fullName', '')

        head_coach = team_box.get('headCoach', '')

        periods = team_box.get('statsByPeriods', [])

        total_period = next((p for p in periods if p['quarter'] == 0), None)
        if total_period is None:
            continue

        team_points = total_period['stats']['total']['points']
        team_stats = total_period['stats'].get('team', {})
        team_rebotes_extra = team_stats.get('totalRebounds', 0)
        team_valoracion_extra = team_stats.get('rating', 0)

        num_ot = sum(1 for p in periods if p['quarter'] > 4)

        players_raw = total_period['stats']['players']

        starters = [p for p in players_raw if p.get('isStarted')]
        bench = [p for p in players_raw if not p.get('isStarted')]
        ordered_players = starters + bench

        players = []
        for p in ordered_players:
            play_time = p.get('playTime', '00:00')
            if play_time == '00:00' or play_time == '0:00':
                continue

            player_info = p.get('player', {})
            nombre = extraer_apellido(player_info.get('firstInitialAndLastName', ''))
            dorsal = player_info.get('shirtNumber', '')

            minutos = convertir_minutos(play_time)
            puntos = p.get('points', 0)
            t2_enc = p.get('twoPointersMade', 0)
            t2_int = p.get('twoPointersAttempted', 0)
            t3_enc = p.get('threePointersMade', 0)
            t3_int = p.get('threePointersAttempted', 0)
            tl_enc = p.get('freeThrowsMade', 0)
            tl_int = p.get('freeThrowsAttempted', 0)
            rebotes = p.get('totalRebounds', 0)
            asistencias = p.get('assists', 0)
            valoracion = p.get('rating', 0)
            titular = p.get('isStarted', False)

            players.append({
                'dorsal': dorsal,
                'nombre': nombre,
                'minutos': minutos,
                'puntos': str(puntos),
                't2_enc': t2_enc, 't2_int': t2_int,
                't3_enc': t3_enc, 't3_int': t3_int,
                'tl_enc': tl_enc, 'tl_int': tl_int,
                'rebotes': str(rebotes),
                'asistencias': str(asistencias),
                'valoracion': str(valoracion),
                'titular': titular,
            })

        teams_data.append({
            'nombre': team_name,
            'puntuacion': str(team_points),
            'jugadores': players,
            'entrenador': head_coach,
            'periods': periods,
            'team_rebotes_extra': team_rebotes_extra,
            'team_valoracion_extra': team_valoracion_extra,
            'num_ot': num_ot,
        })

    parciales_parts = []
    if len(teams_data) == 2:
        t1_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[0]['periods']}
        t2_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[1]['periods']}
        quarters = sorted(q for q in t1_periods if q > 0)
        for q in quarters:
            parciales_parts.append(f"{t1_periods[q]}-{t2_periods[q]}")

    info_adicional = {
        'parciales': ' '.join(parciales_parts),
        'arbitros': ', '.join(data.get('referees', [])),
    }

    return teams_data, info_adicional


def td_val(parent, value):
    td = ET.SubElement(parent, 'td')
    if value and value != '0':
        td.text = value
    return td


def td_tiro(parent, enc, intentos):
    td = ET.SubElement(parent, 'td')
    fmt = convertir_tiros_formato(enc, intentos)
    if fmt:
        td.text = fmt
    return td


def create_xml(teams_data, info_adicional):
    doc = ET.Element('doc')
    doc.set('xml:lang', 'es')

    story = ET.SubElement(doc, 'story')
    text_el = ET.SubElement(story, 'text')
    content = ET.SubElement(text_el, 'content')

    for team in teams_data:
        table = ET.SubElement(content, 'table')
        table.set('class', 'fichabas_auto')

        header_row = ET.SubElement(table, 'tr')
        header_cell = ET.SubElement(header_row, 'td')
        header_cell.set('colspan', '11')
        header_cell.set('class', 'cabecera')
        header_cell.text = f"{team['nombre']}, {team['puntuacion']}"

        titles_row = ET.SubElement(table, 'tr')
        titles_row.set('class', 'valores titulos')
        for title in ['', 'Jugador', 'PTS', '2P', '3P', 'TL', 'RT', 'AS', 'MJ', 'V', '']:
            td = ET.SubElement(titles_row, 'td')
            if title:
                td.text = title

        totales = {
            'puntos': 0,
            't2_enc': 0, 't2_int': 0,
            't3_enc': 0, 't3_int': 0,
            'tl_enc': 0, 'tl_int': 0,
            'rebotes': 0,
            'asistencias': 0,
            'valoracion': 0,
        }

        jugadores_con_relleno = list(team['jugadores'])
        while len(jugadores_con_relleno) < 12:
            jugadores_con_relleno.append(None)

        for player in jugadores_con_relleno:
            row = ET.SubElement(table, 'tr')
            row.set('class', 'valores')

            if player is None:
                for _ in range(11):
                    ET.SubElement(row, 'td')
            else:
                ET.SubElement(row, 'td')

                nombre_cell = ET.SubElement(row, 'td')
                if player.get('titular', False):
                    span = ET.SubElement(nombre_cell, 'span')
                    span.set('class', 'negrita jug')
                    span.text = player['nombre']
                else:
                    nombre_cell.text = player['nombre']

                td_val(row, player['puntos'])
                td_tiro(row, player['t2_enc'], player['t2_int'])
                td_tiro(row, player['t3_enc'], player['t3_int'])
                td_tiro(row, player['tl_enc'], player['tl_int'])
                td_val(row, player['rebotes'])
                td_val(row, player['asistencias'])

                mj_td = ET.SubElement(row, 'td')
                mj_td.text = player['minutos']

                val_td = ET.SubElement(row, 'td')
                val_td.text = player['valoracion']

                ET.SubElement(row, 'td')

                try:
                    totales['puntos'] += int(player['puntos'])
                except (ValueError, TypeError):
                    pass

                totales['t2_enc'] += player['t2_enc']
                totales['t2_int'] += player['t2_int']
                totales['t3_enc'] += player['t3_enc']
                totales['t3_int'] += player['t3_int']
                totales['tl_enc'] += player['tl_enc']
                totales['tl_int'] += player['tl_int']

                try:
                    totales['rebotes'] += int(player['rebotes'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['asistencias'] += int(player['asistencias'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['valoracion'] += int(player['valoracion'])
                except (ValueError, TypeError):
                    pass

        tot_row = ET.SubElement(table, 'tr')
        tot_row.set('class', 'totales')
        ET.SubElement(tot_row, 'td')
        ET.SubElement(tot_row, 'td').text = 'Totales'
        ET.SubElement(tot_row, 'td').text = str(totales['puntos'])

        def tot_tiro_td(parent, enc, int_v):
            td = ET.SubElement(parent, 'td')
            td.text = f"{enc}-{int_v}" if int_v > 0 else ''
            return td

        tot_tiro_td(tot_row, totales['t2_enc'], totales['t2_int'])
        tot_tiro_td(tot_row, totales['t3_enc'], totales['t3_int'])
        tot_tiro_td(tot_row, totales['tl_enc'], totales['tl_int'])

        total_rebotes = totales['rebotes'] + team.get('team_rebotes_extra', 0)
        total_valoracion = totales['valoracion'] + team.get('team_valoracion_extra', 0)
        minutos_partido = 200 + team.get('num_ot', 0) * 25

        td_reb = ET.SubElement(tot_row, 'td')
        td_reb.text = str(total_rebotes) if total_rebotes > 0 else ''

        td_ast = ET.SubElement(tot_row, 'td')
        td_ast.text = str(totales['asistencias']) if totales['asistencias'] > 0 else ''

        ET.SubElement(tot_row, 'td').text = str(minutos_partido)
        ET.SubElement(tot_row, 'td').text = str(total_valoracion)
        ET.SubElement(tot_row, 'td')

        is_last_team = (team is teams_data[-1])

        entr_row = ET.SubElement(table, 'tr')
        entr_row.set('class', 'margenesfilete')
        ET.SubElement(entr_row, 'td')
        entr_lbl = ET.SubElement(entr_row, 'td')
        entr_lbl.set('class', 'negrita')
        entr_lbl.text = 'Entrenador:'
        entr_val = ET.SubElement(entr_row, 'td')
        entr_val.set('class', 'left')
        entr_val.set('colspan', '8')
        entr_val.text = f"\u2002{team.get('entrenador', '')}"
        ET.SubElement(entr_row, 'td')

        if is_last_team:
            def add_info_row(parent, label, value=''):
                row = ET.SubElement(parent, 'tr')
                row.set('class', 'margenesfilete')
                ET.SubElement(row, 'td')
                cell = ET.SubElement(row, 'td')
                cell.set('class', 'left')
                cell.set('colspan', '9')
                span = ET.SubElement(cell, 'span')
                span.set('class', 'negrita')
                span.text = label
                span.tail = value
                ET.SubElement(row, 'td')
                return row

            add_info_row(table, 'Parciales: ', info_adicional.get('parciales', ''))
            add_info_row(table, 'Árbitros: ', info_adicional.get('arbitros', ''))

            cab = ET.SubElement(table, 'tr')
            cab_cell = ET.SubElement(cab, 'td')
            cab_cell.set('class', 'rojo')
            cab_cell.set('colspan', '11')

    xml_string = ET.tostring(doc, encoding='utf-8', method='xml')
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent='\t', encoding='utf-8')
    return pretty_xml


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        match_id = str(data.get('matchId', '')).strip()

        if not match_id:
            return jsonify({'error': 'Por favor, introduce el número de partido'}), 400

        try:
            api_data = fetch_match_data(match_id)
        except Exception as e:
            return jsonify({'error': f'Error al conectar con la API de ACB: {str(e)}'}), 502

        teams_data, info_adicional = parse_api_data(api_data)

        if not teams_data:
            return jsonify({'error': 'No se encontraron datos para este partido'}), 404

        xml_content = create_xml(teams_data, info_adicional)
        xml_str = xml_content.decode('utf-8')

        return jsonify({'success': True, 'xml': xml_str})

    except Exception as e:
        return jsonify({'error': f'Error al generar el XML: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
from flask import Flask, render_template, request, jsonify
import xml.etree.ElementTree as ET
from xml.dom import minidom
import urllib.request
import json

app = Flask(__name__)

ACB_HEADERS = {
    'x-apikey': '0dd94928-6f57-4c08-a3bd-b1b2f092976e',
    'origin': 'https://live.acb.com',
    'referer': 'https://live.acb.com/',
}


def convertir_tiros_formato(enc, intentos):
    if enc == 0 and intentos == 0:
        return ''
    return f"{enc}-{intentos}"


def convertir_minutos(minutos_str):
    if ':' in minutos_str:
        parts = minutos_str.split(':')
        mins = int(parts[0])
        secs = int(parts[1]) if len(parts) > 1 else 0
        result = round(mins + secs / 60)
        if result == 0 and secs > 0:
            result = 1
        return str(result)
    return minutos_str


def extraer_apellido(first_initial_and_last):
    if '. ' in first_initial_and_last:
        return first_initial_and_last.split('. ', 1)[1]
    return first_initial_and_last


def fetch_match_data(match_id):
    url = f'https://api2.acb.com/api/matchdata/Result/boxscores?matchId={match_id}'
    req = urllib.request.Request(url)
    for k, v in ACB_HEADERS.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def parse_api_data(data):
    teams_data = []

    for team_box in data.get('teamBoxscores', []):
        team_info = team_box.get('team', {})
        team_name = team_info.get('fullName', '')

        head_coach = team_box.get('headCoach', '')

        periods = team_box.get('statsByPeriods', [])

        total_period = next((p for p in periods if p['quarter'] == 0), None)
        if total_period is None:
            continue

        team_points = total_period['stats']['total']['points']
        team_stats = total_period['stats'].get('team', {})
        team_rebotes_extra = team_stats.get('totalRebounds', 0)
        team_valoracion_extra = team_stats.get('rating', 0)

        num_ot = sum(1 for p in periods if p['quarter'] > 4)

        players_raw = total_period['stats']['players']

        starters = [p for p in players_raw if p.get('isStarted')]
        bench = [p for p in players_raw if not p.get('isStarted')]
        ordered_players = starters + bench

        players = []
        for p in ordered_players:
            play_time = p.get('playTime', '00:00')
            if play_time == '00:00' or play_time == '0:00':
                continue

            player_info = p.get('player', {})
            nombre = extraer_apellido(player_info.get('firstInitialAndLastName', ''))
            dorsal = player_info.get('shirtNumber', '')

            minutos = convertir_minutos(play_time)
            puntos = p.get('points', 0)
            t2_enc = p.get('twoPointersMade', 0)
            t2_int = p.get('twoPointersAttempted', 0)
            t3_enc = p.get('threePointersMade', 0)
            t3_int = p.get('threePointersAttempted', 0)
            tl_enc = p.get('freeThrowsMade', 0)
            tl_int = p.get('freeThrowsAttempted', 0)
            rebotes = p.get('totalRebounds', 0)
            asistencias = p.get('assists', 0)
            valoracion = p.get('rating', 0)
            titular = p.get('isStarted', False)

            players.append({
                'dorsal': dorsal,
                'nombre': nombre,
                'minutos': minutos,
                'puntos': str(puntos),
                't2_enc': t2_enc, 't2_int': t2_int,
                't3_enc': t3_enc, 't3_int': t3_int,
                'tl_enc': tl_enc, 'tl_int': tl_int,
                'rebotes': str(rebotes),
                'asistencias': str(asistencias),
                'valoracion': str(valoracion),
                'titular': titular,
            })

        teams_data.append({
            'nombre': team_name,
            'puntuacion': str(team_points),
            'jugadores': players,
            'entrenador': head_coach,
            'periods': periods,
            'team_rebotes_extra': team_rebotes_extra,
            'team_valoracion_extra': team_valoracion_extra,
            'num_ot': num_ot,
        })

    parciales_parts = []
    if len(teams_data) == 2:
        t1_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[0]['periods']}
        t2_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[1]['periods']}
        quarters = sorted(q for q in t1_periods if q > 0)
        for q in quarters:
            parciales_parts.append(f"{t1_periods[q]}-{t2_periods[q]}")

    info_adicional = {
        'parciales': ' '.join(parciales_parts),
        'arbitros': ', '.join(data.get('referees', [])),
    }

    return teams_data, info_adicional


def td_val(parent, value):
    td = ET.SubElement(parent, 'td')
    if value and value != '0':
        td.text = value
    return td


def td_tiro(parent, enc, intentos):
    td = ET.SubElement(parent, 'td')
    fmt = convertir_tiros_formato(enc, intentos)
    if fmt:
        td.text = fmt
    return td


def create_xml(teams_data, info_adicional):
    doc = ET.Element('doc')
    doc.set('xml:lang', 'es')

    story = ET.SubElement(doc, 'story')
    text_el = ET.SubElement(story, 'text')
    content = ET.SubElement(text_el, 'content')

    for team in teams_data:
        table = ET.SubElement(content, 'table')
        table.set('class', 'fichabas_auto')

        header_row = ET.SubElement(table, 'tr')
        header_cell = ET.SubElement(header_row, 'td')
        header_cell.set('colspan', '11')
        header_cell.set('class', 'cabecera')
        header_cell.text = f"{team['nombre']}, {team['puntuacion']}"

        titles_row = ET.SubElement(table, 'tr')
        titles_row.set('class', 'valores titulos')
        for title in ['', 'Jugador', 'PTS', '2P', '3P', 'TL', 'RT', 'AS', 'MJ', 'V', '']:
            td = ET.SubElement(titles_row, 'td')
            if title:
                td.text = title

        totales = {
            'puntos': 0,
            't2_enc': 0, 't2_int': 0,
            't3_enc': 0, 't3_int': 0,
            'tl_enc': 0, 'tl_int': 0,
            'rebotes': 0,
            'asistencias': 0,
            'valoracion': 0,
        }

        jugadores_con_relleno = list(team['jugadores'])
        while len(jugadores_con_relleno) < 12:
            jugadores_con_relleno.append(None)

        for player in jugadores_con_relleno:
            row = ET.SubElement(table, 'tr')
            row.set('class', 'valores')

            if player is None:
                for _ in range(11):
                    ET.SubElement(row, 'td')
            else:
                ET.SubElement(row, 'td')

                nombre_cell = ET.SubElement(row, 'td')
                if player.get('titular', False):
                    span = ET.SubElement(nombre_cell, 'span')
                    span.set('class', 'negrita jug')
                    span.text = player['nombre']
                else:
                    nombre_cell.text = player['nombre']

                td_val(row, player['puntos'])
                td_tiro(row, player['t2_enc'], player['t2_int'])
                td_tiro(row, player['t3_enc'], player['t3_int'])
                td_tiro(row, player['tl_enc'], player['tl_int'])
                td_val(row, player['rebotes'])
                td_val(row, player['asistencias'])

                mj_td = ET.SubElement(row, 'td')
                mj_td.text = player['minutos']

                val_td = ET.SubElement(row, 'td')
                val_td.text = player['valoracion']

                ET.SubElement(row, 'td')

                try:
                    totales['puntos'] += int(player['puntos'])
                except (ValueError, TypeError):
                    pass

                totales['t2_enc'] += player['t2_enc']
                totales['t2_int'] += player['t2_int']
                totales['t3_enc'] += player['t3_enc']
                totales['t3_int'] += player['t3_int']
                totales['tl_enc'] += player['tl_enc']
                totales['tl_int'] += player['tl_int']

                try:
                    totales['rebotes'] += int(player['rebotes'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['asistencias'] += int(player['asistencias'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['valoracion'] += int(player['valoracion'])
                except (ValueError, TypeError):
                    pass

        tot_row = ET.SubElement(table, 'tr')
        tot_row.set('class', 'totales')
        ET.SubElement(tot_row, 'td')
        ET.SubElement(tot_row, 'td').text = 'Totales'
        ET.SubElement(tot_row, 'td').text = str(totales['puntos'])

        def tot_tiro_td(parent, enc, int_v):
            td = ET.SubElement(parent, 'td')
            td.text = f"{enc}-{int_v}" if int_v > 0 else ''
            return td

        tot_tiro_td(tot_row, totales['t2_enc'], totales['t2_int'])
        tot_tiro_td(tot_row, totales['t3_enc'], totales['t3_int'])
        tot_tiro_td(tot_row, totales['tl_enc'], totales['tl_int'])

        total_rebotes = totales['rebotes'] + team.get('team_rebotes_extra', 0)
        total_valoracion = totales['valoracion'] + team.get('team_valoracion_extra', 0)
        minutos_partido = 200 + team.get('num_ot', 0) * 25

        td_reb = ET.SubElement(tot_row, 'td')
        td_reb.text = str(total_rebotes) if total_rebotes > 0 else ''

        td_ast = ET.SubElement(tot_row, 'td')
        td_ast.text = str(totales['asistencias']) if totales['asistencias'] > 0 else ''

        ET.SubElement(tot_row, 'td').text = str(minutos_partido)
        ET.SubElement(tot_row, 'td').text = str(total_valoracion)
        ET.SubElement(tot_row, 'td')

        is_last_team = (team is teams_data[-1])

        entr_row = ET.SubElement(table, 'tr')
        entr_row.set('class', 'margenesfilete')
        ET.SubElement(entr_row, 'td')
        entr_lbl = ET.SubElement(entr_row, 'td')
        entr_lbl.set('class', 'negrita')
        entr_lbl.text = 'Entrenador:'
        entr_val = ET.SubElement(entr_row, 'td')
        entr_val.set('class', 'left')
        entr_val.set('colspan', '8')
        entr_val.text = f"\u2002{team.get('entrenador', '')}"
        ET.SubElement(entr_row, 'td')

        if is_last_team:
            def add_info_row(parent, label, value=''):
                row = ET.SubElement(parent, 'tr')
                row.set('class', 'margenesfilete')
                ET.SubElement(row, 'td')
                cell = ET.SubElement(row, 'td')
                cell.set('class', 'left')
                cell.set('colspan', '9')
                span = ET.SubElement(cell, 'span')
                span.set('class', 'negrita')
                span.text = label
                span.tail = value
                ET.SubElement(row, 'td')
                return row

            add_info_row(table, 'Parciales: ', info_adicional.get('parciales', ''))
            add_info_row(table, 'Árbitros: ', info_adicional.get('arbitros', ''))

            cab = ET.SubElement(table, 'tr')
            cab_cell = ET.SubElement(cab, 'td')
            cab_cell.set('class', 'rojo')
            cab_cell.set('colspan', '11')

    xml_string = ET.tostring(doc, encoding='utf-8', method='xml')
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent='\t', encoding='utf-8')
    return pretty_xml


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        match_id = str(data.get('matchId', '')).strip()

        if not match_id:
            return jsonify({'error': 'Por favor, introduce el número de partido'}), 400

        try:
            api_data = fetch_match_data(match_id)
        except Exception as e:
            return jsonify({'error': f'Error al conectar con la API de ACB: {str(e)}'}), 502

        teams_data, info_adicional = parse_api_data(api_data)

        if not teams_data:
            return jsonify({'error': 'No se encontraron datos para este partido'}), 404

        xml_content = create_xml(teams_data, info_adicional)
        xml_str = xml_content.decode('utf-8')

        return jsonify({'success': True, 'xml': xml_str})

    except Exception as e:
        return jsonify({'error': f'Error al generar el XML: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
from flask import Flask, render_template, request, jsonify
import xml.etree.ElementTree as ET
from xml.dom import minidom
import urllib.request
import json

app = Flask(__name__)

ACB_HEADERS = {
    'x-apikey': '0dd94928-6f57-4c08-a3bd-b1b2f092976e',
    'origin': 'https://live.acb.com',
    'referer': 'https://live.acb.com/',
}


def convertir_tiros_formato(enc, intentos):
    if enc == 0 and intentos == 0:
        return ''
    return f"{enc}-{intentos}"


def convertir_minutos(minutos_str):
    if ':' in minutos_str:
        parts = minutos_str.split(':')
        mins = int(parts[0])
        secs = int(parts[1]) if len(parts) > 1 else 0
        result = round(mins + secs / 60)
        if result == 0 and secs > 0:
            result = 1
        return str(result)
    return minutos_str


def extraer_apellido(first_initial_and_last):
    if '. ' in first_initial_and_last:
        return first_initial_and_last.split('. ', 1)[1]
    return first_initial_and_last


def fetch_match_data(match_id):
    url = f'https://api2.acb.com/api/matchdata/Result/boxscores?matchId={match_id}'
    req = urllib.request.Request(url)
    for k, v in ACB_HEADERS.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def parse_api_data(data):
    teams_data = []

    for team_box in data.get('teamBoxscores', []):
        team_info = team_box.get('team', {})
        team_name = team_info.get('fullName', '')

        head_coach = team_box.get('headCoach', '')

        periods = team_box.get('statsByPeriods', [])

        total_period = next((p for p in periods if p['quarter'] == 0), None)
        if total_period is None:
            continue

        team_points = total_period['stats']['total']['points']
        team_stats = total_period['stats'].get('team', {})
        team_rebotes_extra = team_stats.get('totalRebounds', 0)
        team_valoracion_extra = team_stats.get('rating', 0)

        num_ot = sum(1 for p in periods if p['quarter'] > 4)

        players_raw = total_period['stats']['players']

        starters = [p for p in players_raw if p.get('isStarted')]
        bench = [p for p in players_raw if not p.get('isStarted')]
        ordered_players = starters + bench

        players = []
        for p in ordered_players:
            play_time = p.get('playTime', '00:00')
            if play_time == '00:00' or play_time == '0:00':
                continue

            player_info = p.get('player', {})
            nombre = extraer_apellido(player_info.get('firstInitialAndLastName', ''))
            dorsal = player_info.get('shirtNumber', '')

            minutos = convertir_minutos(play_time)
            puntos = p.get('points', 0)
            t2_enc = p.get('twoPointersMade', 0)
            t2_int = p.get('twoPointersAttempted', 0)
            t3_enc = p.get('threePointersMade', 0)
            t3_int = p.get('threePointersAttempted', 0)
            tl_enc = p.get('freeThrowsMade', 0)
            tl_int = p.get('freeThrowsAttempted', 0)
            rebotes = p.get('totalRebounds', 0)
            asistencias = p.get('assists', 0)
            valoracion = p.get('rating', 0)
            titular = p.get('isStarted', False)

            players.append({
                'dorsal': dorsal,
                'nombre': nombre,
                'minutos': minutos,
                'puntos': str(puntos),
                't2_enc': t2_enc, 't2_int': t2_int,
                't3_enc': t3_enc, 't3_int': t3_int,
                'tl_enc': tl_enc, 'tl_int': tl_int,
                'rebotes': str(rebotes),
                'asistencias': str(asistencias),
                'valoracion': str(valoracion),
                'titular': titular,
            })

        teams_data.append({
            'nombre': team_name,
            'puntuacion': str(team_points),
            'jugadores': players,
            'entrenador': head_coach,
            'periods': periods,
            'team_rebotes_extra': team_rebotes_extra,
            'team_valoracion_extra': team_valoracion_extra,
            'num_ot': num_ot,
        })

    parciales_parts = []
    if len(teams_data) == 2:
        t1_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[0]['periods']}
        t2_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[1]['periods']}
        quarters = sorted(q for q in t1_periods if q > 0)
        for q in quarters:
            parciales_parts.append(f"{t1_periods[q]}-{t2_periods[q]}")

    info_adicional = {
        'parciales': ' '.join(parciales_parts),
        'arbitros': ', '.join(data.get('referees', [])),
    }

    return teams_data, info_adicional


def td_val(parent, value):
    td = ET.SubElement(parent, 'td')
    if value and value != '0':
        td.text = value
    return td


def td_tiro(parent, enc, intentos):
    td = ET.SubElement(parent, 'td')
    fmt = convertir_tiros_formato(enc, intentos)
    if fmt:
        td.text = fmt
    return td


def create_xml(teams_data, info_adicional):
    doc = ET.Element('doc')
    doc.set('xml:lang', 'es')

    story = ET.SubElement(doc, 'story')
    text_el = ET.SubElement(story, 'text')
    content = ET.SubElement(text_el, 'content')

    for team in teams_data:
        table = ET.SubElement(content, 'table')
        table.set('class', 'fichabas_auto')

        header_row = ET.SubElement(table, 'tr')
        header_cell = ET.SubElement(header_row, 'td')
        header_cell.set('colspan', '11')
        header_cell.set('class', 'cabecera')
        header_cell.text = f"{team['nombre']}, {team['puntuacion']}"

        titles_row = ET.SubElement(table, 'tr')
        titles_row.set('class', 'valores titulos')
        for title in ['', 'Jugador', 'PTS', '2P', '3P', 'TL', 'RT', 'AS', 'MJ', 'V', '']:
            td = ET.SubElement(titles_row, 'td')
            if title:
                td.text = title

        totales = {
            'puntos': 0,
            't2_enc': 0, 't2_int': 0,
            't3_enc': 0, 't3_int': 0,
            'tl_enc': 0, 'tl_int': 0,
            'rebotes': 0,
            'asistencias': 0,
            'valoracion': 0,
        }

        jugadores_con_relleno = list(team['jugadores'])
        while len(jugadores_con_relleno) < 12:
            jugadores_con_relleno.append(None)

        for player in jugadores_con_relleno:
            row = ET.SubElement(table, 'tr')
            row.set('class', 'valores')

            if player is None:
                for _ in range(11):
                    ET.SubElement(row, 'td')
            else:
                ET.SubElement(row, 'td')

                nombre_cell = ET.SubElement(row, 'td')
                if player.get('titular', False):
                    span = ET.SubElement(nombre_cell, 'span')
                    span.set('class', 'negrita jug')
                    span.text = player['nombre']
                else:
                    nombre_cell.text = player['nombre']

                td_val(row, player['puntos'])
                td_tiro(row, player['t2_enc'], player['t2_int'])
                td_tiro(row, player['t3_enc'], player['t3_int'])
                td_tiro(row, player['tl_enc'], player['tl_int'])
                td_val(row, player['rebotes'])
                td_val(row, player['asistencias'])

                mj_td = ET.SubElement(row, 'td')
                mj_td.text = player['minutos']

                val_td = ET.SubElement(row, 'td')
                val_td.text = player['valoracion']

                ET.SubElement(row, 'td')

                try:
                    totales['puntos'] += int(player['puntos'])
                except (ValueError, TypeError):
                    pass

                totales['t2_enc'] += player['t2_enc']
                totales['t2_int'] += player['t2_int']
                totales['t3_enc'] += player['t3_enc']
                totales['t3_int'] += player['t3_int']
                totales['tl_enc'] += player['tl_enc']
                totales['tl_int'] += player['tl_int']

                try:
                    totales['rebotes'] += int(player['rebotes'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['asistencias'] += int(player['asistencias'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['valoracion'] += int(player['valoracion'])
                except (ValueError, TypeError):
                    pass

        tot_row = ET.SubElement(table, 'tr')
        tot_row.set('class', 'totales')
        ET.SubElement(tot_row, 'td')
        ET.SubElement(tot_row, 'td').text = 'Totales'
        ET.SubElement(tot_row, 'td').text = str(totales['puntos'])

        def tot_tiro_td(parent, enc, int_v):
            td = ET.SubElement(parent, 'td')
            td.text = f"{enc}-{int_v}" if int_v > 0 else ''
            return td

        tot_tiro_td(tot_row, totales['t2_enc'], totales['t2_int'])
        tot_tiro_td(tot_row, totales['t3_enc'], totales['t3_int'])
        tot_tiro_td(tot_row, totales['tl_enc'], totales['tl_int'])

        total_rebotes = totales['rebotes'] + team.get('team_rebotes_extra', 0)
        total_valoracion = totales['valoracion'] + team.get('team_valoracion_extra', 0)
        minutos_partido = 200 + team.get('num_ot', 0) * 25

        td_reb = ET.SubElement(tot_row, 'td')
        td_reb.text = str(total_rebotes) if total_rebotes > 0 else ''

        td_ast = ET.SubElement(tot_row, 'td')
        td_ast.text = str(totales['asistencias']) if totales['asistencias'] > 0 else ''

        ET.SubElement(tot_row, 'td').text = str(minutos_partido)
        ET.SubElement(tot_row, 'td').text = str(total_valoracion)
        ET.SubElement(tot_row, 'td')

        is_last_team = (team is teams_data[-1])

        entr_row = ET.SubElement(table, 'tr')
        entr_row.set('class', 'margenesfilete')
        ET.SubElement(entr_row, 'td')
        entr_lbl = ET.SubElement(entr_row, 'td')
        entr_lbl.set('class', 'negrita')
        entr_lbl.text = 'Entrenador:'
        entr_val = ET.SubElement(entr_row, 'td')
        entr_val.set('class', 'left')
        entr_val.set('colspan', '8')
        entr_val.text = f"\u2002{team.get('entrenador', '')}"
        ET.SubElement(entr_row, 'td')

        if is_last_team:
            def add_info_row(parent, label, value=''):
                row = ET.SubElement(parent, 'tr')
                row.set('class', 'margenesfilete')
                ET.SubElement(row, 'td')
                cell = ET.SubElement(row, 'td')
                cell.set('class', 'left')
                cell.set('colspan', '9')
                span = ET.SubElement(cell, 'span')
                span.set('class', 'negrita')
                span.text = label
                span.tail = value
                ET.SubElement(row, 'td')
                return row

            add_info_row(table, 'Parciales: ', info_adicional.get('parciales', ''))
            add_info_row(table, 'Árbitros: ', info_adicional.get('arbitros', ''))

            cab = ET.SubElement(table, 'tr')
            cab_cell = ET.SubElement(cab, 'td')
            cab_cell.set('class', 'rojo')
            cab_cell.set('colspan', '11')

    xml_string = ET.tostring(doc, encoding='utf-8', method='xml')
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent='\t', encoding='utf-8')
    return pretty_xml


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        match_id = str(data.get('matchId', '')).strip()

        if not match_id:
            return jsonify({'error': 'Por favor, introduce el número de partido'}), 400

        try:
            api_data = fetch_match_data(match_id)
        except Exception as e:
            return jsonify({'error': f'Error al conectar con la API de ACB: {str(e)}'}), 502

        teams_data, info_adicional = parse_api_data(api_data)

        if not teams_data:
            return jsonify({'error': 'No se encontraron datos para este partido'}), 404

        xml_content = create_xml(teams_data, info_adicional)
        xml_str = xml_content.decode('utf-8')

        return jsonify({'success': True, 'xml': xml_str})

    except Exception as e:
        return jsonify({'error': f'Error al generar el XML: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
from flask import Flask, render_template, request, jsonify
import xml.etree.ElementTree as ET
from xml.dom import minidom
import urllib.request
import json

app = Flask(__name__)

ACB_HEADERS = {
    'x-apikey': '0dd94928-6f57-4c08-a3bd-b1b2f092976e',
    'origin': 'https://live.acb.com',
    'referer': 'https://live.acb.com/',
}


def convertir_tiros_formato(enc, intentos):
    if enc == 0 and intentos == 0:
        return ''
    return f"{enc}-{intentos}"


def convertir_minutos(minutos_str):
    if ':' in minutos_str:
        parts = minutos_str.split(':')
        mins = int(parts[0])
        secs = int(parts[1]) if len(parts) > 1 else 0
        result = round(mins + secs / 60)
        if result == 0 and secs > 0:
            result = 1
        return str(result)
    return minutos_str


def extraer_apellido(first_initial_and_last):
    if '. ' in first_initial_and_last:
        return first_initial_and_last.split('. ', 1)[1]
    return first_initial_and_last


def fetch_match_data(match_id):
    url = f'https://api2.acb.com/api/matchdata/Result/boxscores?matchId={match_id}'
    req = urllib.request.Request(url)
    for k, v in ACB_HEADERS.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def parse_api_data(data):
    teams_data = []

    for team_box in data.get('teamBoxscores', []):
        team_info = team_box.get('team', {})
        team_name = team_info.get('fullName', '')

        head_coach = team_box.get('headCoach', '')

        periods = team_box.get('statsByPeriods', [])

        total_period = next((p for p in periods if p['quarter'] == 0), None)
        if total_period is None:
            continue

        team_points = total_period['stats']['total']['points']
        team_stats = total_period['stats'].get('team', {})
        team_rebotes_extra = team_stats.get('totalRebounds', 0)
        team_valoracion_extra = team_stats.get('rating', 0)

        num_ot = sum(1 for p in periods if p['quarter'] > 4)

        players_raw = total_period['stats']['players']

        starters = [p for p in players_raw if p.get('isStarted')]
        bench = [p for p in players_raw if not p.get('isStarted')]
        ordered_players = starters + bench

        players = []
        for p in ordered_players:
            play_time = p.get('playTime', '00:00')
            if play_time == '00:00' or play_time == '0:00':
                continue

            player_info = p.get('player', {})
            nombre = extraer_apellido(player_info.get('firstInitialAndLastName', ''))
            dorsal = player_info.get('shirtNumber', '')

            minutos = convertir_minutos(play_time)
            puntos = p.get('points', 0)
            t2_enc = p.get('twoPointersMade', 0)
            t2_int = p.get('twoPointersAttempted', 0)
            t3_enc = p.get('threePointersMade', 0)
            t3_int = p.get('threePointersAttempted', 0)
            tl_enc = p.get('freeThrowsMade', 0)
            tl_int = p.get('freeThrowsAttempted', 0)
            rebotes = p.get('totalRebounds', 0)
            asistencias = p.get('assists', 0)
            valoracion = p.get('rating', 0)
            titular = p.get('isStarted', False)

            players.append({
                'dorsal': dorsal,
                'nombre': nombre,
                'minutos': minutos,
                'puntos': str(puntos),
                't2_enc': t2_enc, 't2_int': t2_int,
                't3_enc': t3_enc, 't3_int': t3_int,
                'tl_enc': tl_enc, 'tl_int': tl_int,
                'rebotes': str(rebotes),
                'asistencias': str(asistencias),
                'valoracion': str(valoracion),
                'titular': titular,
            })

        teams_data.append({
            'nombre': team_name,
            'puntuacion': str(team_points),
            'jugadores': players,
            'entrenador': head_coach,
            'periods': periods,
            'team_rebotes_extra': team_rebotes_extra,
            'team_valoracion_extra': team_valoracion_extra,
            'num_ot': num_ot,
        })

    parciales_parts = []
    if len(teams_data) == 2:
        t1_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[0]['periods']}
        t2_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[1]['periods']}
        quarters = sorted(q for q in t1_periods if q > 0)
        for q in quarters:
            parciales_parts.append(f"{t1_periods[q]}-{t2_periods[q]}")

    info_adicional = {
        'parciales': ' '.join(parciales_parts),
        'arbitros': ', '.join(data.get('referees', [])),
    }

    return teams_data, info_adicional


def td_val(parent, value):
    td = ET.SubElement(parent, 'td')
    if value and value != '0':
        td.text = value
    return td


def td_tiro(parent, enc, intentos):
    td = ET.SubElement(parent, 'td')
    fmt = convertir_tiros_formato(enc, intentos)
    if fmt:
        td.text = fmt
    return td


def create_xml(teams_data, info_adicional):
    doc = ET.Element('doc')
    doc.set('xml:lang', 'es')

    story = ET.SubElement(doc, 'story')
    text_el = ET.SubElement(story, 'text')
    content = ET.SubElement(text_el, 'content')

    for team in teams_data:
        table = ET.SubElement(content, 'table')
        table.set('class', 'fichabas_auto')

        header_row = ET.SubElement(table, 'tr')
        header_cell = ET.SubElement(header_row, 'td')
        header_cell.set('colspan', '11')
        header_cell.set('class', 'cabecera')
        header_cell.text = f"{team['nombre']}, {team['puntuacion']}"

        titles_row = ET.SubElement(table, 'tr')
        titles_row.set('class', 'valores titulos')
        for title in ['', 'Jugador', 'PTS', '2P', '3P', 'TL', 'RT', 'AS', 'MJ', 'V', '']:
            td = ET.SubElement(titles_row, 'td')
            if title:
                td.text = title

        totales = {
            'puntos': 0,
            't2_enc': 0, 't2_int': 0,
            't3_enc': 0, 't3_int': 0,
            'tl_enc': 0, 'tl_int': 0,
            'rebotes': 0,
            'asistencias': 0,
            'valoracion': 0,
        }

        jugadores_con_relleno = list(team['jugadores'])
        while len(jugadores_con_relleno) < 12:
            jugadores_con_relleno.append(None)

        for player in jugadores_con_relleno:
            row = ET.SubElement(table, 'tr')
            row.set('class', 'valores')

            if player is None:
                for _ in range(11):
                    ET.SubElement(row, 'td')
            else:
                ET.SubElement(row, 'td')

                nombre_cell = ET.SubElement(row, 'td')
                if player.get('titular', False):
                    span = ET.SubElement(nombre_cell, 'span')
                    span.set('class', 'negrita jug')
                    span.text = player['nombre']
                else:
                    nombre_cell.text = player['nombre']

                td_val(row, player['puntos'])
                td_tiro(row, player['t2_enc'], player['t2_int'])
                td_tiro(row, player['t3_enc'], player['t3_int'])
                td_tiro(row, player['tl_enc'], player['tl_int'])
                td_val(row, player['rebotes'])
                td_val(row, player['asistencias'])

                mj_td = ET.SubElement(row, 'td')
                mj_td.text = player['minutos']

                val_td = ET.SubElement(row, 'td')
                val_td.text = player['valoracion']

                ET.SubElement(row, 'td')

                try:
                    totales['puntos'] += int(player['puntos'])
                except (ValueError, TypeError):
                    pass

                totales['t2_enc'] += player['t2_enc']
                totales['t2_int'] += player['t2_int']
                totales['t3_enc'] += player['t3_enc']
                totales['t3_int'] += player['t3_int']
                totales['tl_enc'] += player['tl_enc']
                totales['tl_int'] += player['tl_int']

                try:
                    totales['rebotes'] += int(player['rebotes'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['asistencias'] += int(player['asistencias'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['valoracion'] += int(player['valoracion'])
                except (ValueError, TypeError):
                    pass

        tot_row = ET.SubElement(table, 'tr')
        tot_row.set('class', 'totales')
        ET.SubElement(tot_row, 'td')
        ET.SubElement(tot_row, 'td').text = 'Totales'
        ET.SubElement(tot_row, 'td').text = str(totales['puntos'])

        def tot_tiro_td(parent, enc, int_v):
            td = ET.SubElement(parent, 'td')
            td.text = f"{enc}-{int_v}" if int_v > 0 else ''
            return td

        tot_tiro_td(tot_row, totales['t2_enc'], totales['t2_int'])
        tot_tiro_td(tot_row, totales['t3_enc'], totales['t3_int'])
        tot_tiro_td(tot_row, totales['tl_enc'], totales['tl_int'])

        total_rebotes = totales['rebotes'] + team.get('team_rebotes_extra', 0)
        total_valoracion = totales['valoracion'] + team.get('team_valoracion_extra', 0)
        minutos_partido = 200 + team.get('num_ot', 0) * 25

        td_reb = ET.SubElement(tot_row, 'td')
        td_reb.text = str(total_rebotes) if total_rebotes > 0 else ''

        td_ast = ET.SubElement(tot_row, 'td')
        td_ast.text = str(totales['asistencias']) if totales['asistencias'] > 0 else ''

        ET.SubElement(tot_row, 'td').text = str(minutos_partido)
        ET.SubElement(tot_row, 'td').text = str(total_valoracion)
        ET.SubElement(tot_row, 'td')

        is_last_team = (team is teams_data[-1])

        entr_row = ET.SubElement(table, 'tr')
        entr_row.set('class', 'margenesfilete')
        ET.SubElement(entr_row, 'td')
        entr_lbl = ET.SubElement(entr_row, 'td')
        entr_lbl.set('class', 'negrita')
        entr_lbl.text = 'Entrenador:'
        entr_val = ET.SubElement(entr_row, 'td')
        entr_val.set('class', 'left')
        entr_val.set('colspan', '8')
        entr_val.text = f"\u2002{team.get('entrenador', '')}"
        ET.SubElement(entr_row, 'td')

        if is_last_team:
            def add_info_row(parent, label, value=''):
                row = ET.SubElement(parent, 'tr')
                row.set('class', 'margenesfilete')
                ET.SubElement(row, 'td')
                cell = ET.SubElement(row, 'td')
                cell.set('class', 'left')
                cell.set('colspan', '9')
                span = ET.SubElement(cell, 'span')
                span.set('class', 'negrita')
                span.text = label
                span.tail = value
                ET.SubElement(row, 'td')
                return row

            add_info_row(table, 'Parciales: ', info_adicional.get('parciales', ''))
            add_info_row(table, 'Árbitros: ', info_adicional.get('arbitros', ''))

            cab = ET.SubElement(table, 'tr')
            cab_cell = ET.SubElement(cab, 'td')
            cab_cell.set('class', 'rojo')
            cab_cell.set('colspan', '11')

    xml_string = ET.tostring(doc, encoding='utf-8', method='xml')
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent='\t', encoding='utf-8')
    return pretty_xml


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        match_id = str(data.get('matchId', '')).strip()

        if not match_id:
            return jsonify({'error': 'Por favor, introduce el número de partido'}), 400

        try:
            api_data = fetch_match_data(match_id)
        except Exception as e:
            return jsonify({'error': f'Error al conectar con la API de ACB: {str(e)}'}), 502

        teams_data, info_adicional = parse_api_data(api_data)

        if not teams_data:
            return jsonify({'error': 'No se encontraron datos para este partido'}), 404

        xml_content = create_xml(teams_data, info_adicional)
        xml_str = xml_content.decode('utf-8')

        return jsonify({'success': True, 'xml': xml_str})

    except Exception as e:
        return jsonify({'error': f'Error al generar el XML: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
from flask import Flask, render_template, request, jsonify
import xml.etree.ElementTree as ET
from xml.dom import minidom
import urllib.request
import json

app = Flask(__name__)

ACB_HEADERS = {
    'x-apikey': '0dd94928-6f57-4c08-a3bd-b1b2f092976e',
    'origin': 'https://live.acb.com',
    'referer': 'https://live.acb.com/',
}


def convertir_tiros_formato(enc, intentos):
    if enc == 0 and intentos == 0:
        return ''
    return f"{enc}-{intentos}"


def convertir_minutos(minutos_str):
    if ':' in minutos_str:
        parts = minutos_str.split(':')
        mins = int(parts[0])
        secs = int(parts[1]) if len(parts) > 1 else 0
        result = round(mins + secs / 60)
        if result == 0 and secs > 0:
            result = 1
        return str(result)
    return minutos_str


def extraer_apellido(first_initial_and_last):
    if '. ' in first_initial_and_last:
        return first_initial_and_last.split('. ', 1)[1]
    return first_initial_and_last


def fetch_match_data(match_id):
    url = f'https://api2.acb.com/api/matchdata/Result/boxscores?matchId={match_id}'
    req = urllib.request.Request(url)
    for k, v in ACB_HEADERS.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def parse_api_data(data):
    teams_data = []

    for team_box in data.get('teamBoxscores', []):
        team_info = team_box.get('team', {})
        team_name = team_info.get('fullName', '')

        head_coach = team_box.get('headCoach', '')

        periods = team_box.get('statsByPeriods', [])

        total_period = next((p for p in periods if p['quarter'] == 0), None)
        if total_period is None:
            continue

        team_points = total_period['stats']['total']['points']
        team_stats = total_period['stats'].get('team', {})
        team_rebotes_extra = team_stats.get('totalRebounds', 0)
        team_valoracion_extra = team_stats.get('rating', 0)

        num_ot = sum(1 for p in periods if p['quarter'] > 4)

        players_raw = total_period['stats']['players']

        starters = [p for p in players_raw if p.get('isStarted')]
        bench = [p for p in players_raw if not p.get('isStarted')]
        ordered_players = starters + bench

        players = []
        for p in ordered_players:
            play_time = p.get('playTime', '00:00')
            if play_time == '00:00' or play_time == '0:00':
                continue

            player_info = p.get('player', {})
            nombre = extraer_apellido(player_info.get('firstInitialAndLastName', ''))
            dorsal = player_info.get('shirtNumber', '')

            minutos = convertir_minutos(play_time)
            puntos = p.get('points', 0)
            t2_enc = p.get('twoPointersMade', 0)
            t2_int = p.get('twoPointersAttempted', 0)
            t3_enc = p.get('threePointersMade', 0)
            t3_int = p.get('threePointersAttempted', 0)
            tl_enc = p.get('freeThrowsMade', 0)
            tl_int = p.get('freeThrowsAttempted', 0)
            rebotes = p.get('totalRebounds', 0)
            asistencias = p.get('assists', 0)
            valoracion = p.get('rating', 0)
            titular = p.get('isStarted', False)

            players.append({
                'dorsal': dorsal,
                'nombre': nombre,
                'minutos': minutos,
                'puntos': str(puntos),
                't2_enc': t2_enc, 't2_int': t2_int,
                't3_enc': t3_enc, 't3_int': t3_int,
                'tl_enc': tl_enc, 'tl_int': tl_int,
                'rebotes': str(rebotes),
                'asistencias': str(asistencias),
                'valoracion': str(valoracion),
                'titular': titular,
            })

        teams_data.append({
            'nombre': team_name,
            'puntuacion': str(team_points),
            'jugadores': players,
            'entrenador': head_coach,
            'periods': periods,
            'team_rebotes_extra': team_rebotes_extra,
            'team_valoracion_extra': team_valoracion_extra,
            'num_ot': num_ot,
        })

    parciales_parts = []
    if len(teams_data) == 2:
        t1_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[0]['periods']}
        t2_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[1]['periods']}
        quarters = sorted(q for q in t1_periods if q > 0)
        for q in quarters:
            parciales_parts.append(f"{t1_periods[q]}-{t2_periods[q]}")

    info_adicional = {
        'parciales': ' '.join(parciales_parts),
        'arbitros': ', '.join(data.get('referees', [])),
    }

    return teams_data, info_adicional


def td_val(parent, value):
    td = ET.SubElement(parent, 'td')
    if value and value != '0':
        td.text = value
    return td


def td_tiro(parent, enc, intentos):
    td = ET.SubElement(parent, 'td')
    fmt = convertir_tiros_formato(enc, intentos)
    if fmt:
        td.text = fmt
    return td


def create_xml(teams_data, info_adicional):
    doc = ET.Element('doc')
    doc.set('xml:lang', 'es')

    story = ET.SubElement(doc, 'story')
    text_el = ET.SubElement(story, 'text')
    content = ET.SubElement(text_el, 'content')

    for team in teams_data:
        table = ET.SubElement(content, 'table')
        table.set('class', 'fichabas_auto')

        header_row = ET.SubElement(table, 'tr')
        header_cell = ET.SubElement(header_row, 'td')
        header_cell.set('colspan', '11')
        header_cell.set('class', 'cabecera')
        header_cell.text = f"{team['nombre']}, {team['puntuacion']}"

        titles_row = ET.SubElement(table, 'tr')
        titles_row.set('class', 'valores titulos')
        for title in ['', 'Jugador', 'PTS', '2P', '3P', 'TL', 'RT', 'AS', 'MJ', 'V', '']:
            td = ET.SubElement(titles_row, 'td')
            if title:
                td.text = title

        totales = {
            'puntos': 0,
            't2_enc': 0, 't2_int': 0,
            't3_enc': 0, 't3_int': 0,
            'tl_enc': 0, 'tl_int': 0,
            'rebotes': 0,
            'asistencias': 0,
            'valoracion': 0,
        }

        jugadores_con_relleno = list(team['jugadores'])
        while len(jugadores_con_relleno) < 12:
            jugadores_con_relleno.append(None)

        for player in jugadores_con_relleno:
            row = ET.SubElement(table, 'tr')
            row.set('class', 'valores')

            if player is None:
                for _ in range(11):
                    ET.SubElement(row, 'td')
            else:
                ET.SubElement(row, 'td')

                nombre_cell = ET.SubElement(row, 'td')
                if player.get('titular', False):
                    span = ET.SubElement(nombre_cell, 'span')
                    span.set('class', 'negrita jug')
                    span.text = player['nombre']
                else:
                    nombre_cell.text = player['nombre']

                td_val(row, player['puntos'])
                td_tiro(row, player['t2_enc'], player['t2_int'])
                td_tiro(row, player['t3_enc'], player['t3_int'])
                td_tiro(row, player['tl_enc'], player['tl_int'])
                td_val(row, player['rebotes'])
                td_val(row, player['asistencias'])

                mj_td = ET.SubElement(row, 'td')
                mj_td.text = player['minutos']

                val_td = ET.SubElement(row, 'td')
                val_td.text = player['valoracion']

                ET.SubElement(row, 'td')

                try:
                    totales['puntos'] += int(player['puntos'])
                except (ValueError, TypeError):
                    pass

                totales['t2_enc'] += player['t2_enc']
                totales['t2_int'] += player['t2_int']
                totales['t3_enc'] += player['t3_enc']
                totales['t3_int'] += player['t3_int']
                totales['tl_enc'] += player['tl_enc']
                totales['tl_int'] += player['tl_int']

                try:
                    totales['rebotes'] += int(player['rebotes'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['asistencias'] += int(player['asistencias'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['valoracion'] += int(player['valoracion'])
                except (ValueError, TypeError):
                    pass

        tot_row = ET.SubElement(table, 'tr')
        tot_row.set('class', 'totales')
        ET.SubElement(tot_row, 'td')
        ET.SubElement(tot_row, 'td').text = 'Totales'
        ET.SubElement(tot_row, 'td').text = str(totales['puntos'])

        def tot_tiro_td(parent, enc, int_v):
            td = ET.SubElement(parent, 'td')
            td.text = f"{enc}-{int_v}" if int_v > 0 else ''
            return td

        tot_tiro_td(tot_row, totales['t2_enc'], totales['t2_int'])
        tot_tiro_td(tot_row, totales['t3_enc'], totales['t3_int'])
        tot_tiro_td(tot_row, totales['tl_enc'], totales['tl_int'])

        total_rebotes = totales['rebotes'] + team.get('team_rebotes_extra', 0)
        total_valoracion = totales['valoracion'] + team.get('team_valoracion_extra', 0)
        minutos_partido = 200 + team.get('num_ot', 0) * 25

        td_reb = ET.SubElement(tot_row, 'td')
        td_reb.text = str(total_rebotes) if total_rebotes > 0 else ''

        td_ast = ET.SubElement(tot_row, 'td')
        td_ast.text = str(totales['asistencias']) if totales['asistencias'] > 0 else ''

        ET.SubElement(tot_row, 'td').text = str(minutos_partido)
        ET.SubElement(tot_row, 'td').text = str(total_valoracion)
        ET.SubElement(tot_row, 'td')

        is_last_team = (team is teams_data[-1])

        entr_row = ET.SubElement(table, 'tr')
        entr_row.set('class', 'margenesfilete')
        ET.SubElement(entr_row, 'td')
        entr_lbl = ET.SubElement(entr_row, 'td')
        entr_lbl.set('class', 'negrita')
        entr_lbl.text = 'Entrenador:'
        entr_val = ET.SubElement(entr_row, 'td')
        entr_val.set('class', 'left')
        entr_val.set('colspan', '8')
        entr_val.text = f"\u2002{team.get('entrenador', '')}"
        ET.SubElement(entr_row, 'td')

        if is_last_team:
            def add_info_row(parent, label, value=''):
                row = ET.SubElement(parent, 'tr')
                row.set('class', 'margenesfilete')
                ET.SubElement(row, 'td')
                cell = ET.SubElement(row, 'td')
                cell.set('class', 'left')
                cell.set('colspan', '9')
                span = ET.SubElement(cell, 'span')
                span.set('class', 'negrita')
                span.text = label
                span.tail = value
                ET.SubElement(row, 'td')
                return row

            add_info_row(table, 'Parciales: ', info_adicional.get('parciales', ''))
            add_info_row(table, 'Árbitros: ', info_adicional.get('arbitros', ''))

            cab = ET.SubElement(table, 'tr')
            cab_cell = ET.SubElement(cab, 'td')
            cab_cell.set('class', 'rojo')
            cab_cell.set('colspan', '11')

    xml_string = ET.tostring(doc, encoding='utf-8', method='xml')
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent='\t', encoding='utf-8')
    return pretty_xml


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        match_id = str(data.get('matchId', '')).strip()

        if not match_id:
            return jsonify({'error': 'Por favor, introduce el número de partido'}), 400

        try:
            api_data = fetch_match_data(match_id)
        except Exception as e:
            return jsonify({'error': f'Error al conectar con la API de ACB: {str(e)}'}), 502

        teams_data, info_adicional = parse_api_data(api_data)

        if not teams_data:
            return jsonify({'error': 'No se encontraron datos para este partido'}), 404

        xml_content = create_xml(teams_data, info_adicional)
        xml_str = xml_content.decode('utf-8')

        return jsonify({'success': True, 'xml': xml_str})

    except Exception as e:
        return jsonify({'error': f'Error al generar el XML: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
from flask import Flask, render_template, request, jsonify
import xml.etree.ElementTree as ET
from xml.dom import minidom
import urllib.request
import json

app = Flask(__name__)

ACB_HEADERS = {
    'x-apikey': '0dd94928-6f57-4c08-a3bd-b1b2f092976e',
    'origin': 'https://live.acb.com',
    'referer': 'https://live.acb.com/',
}


def convertir_tiros_formato(enc, intentos):
    if enc == 0 and intentos == 0:
        return ''
    return f"{enc}-{intentos}"


def convertir_minutos(minutos_str):
    if ':' in minutos_str:
        parts = minutos_str.split(':')
        mins = int(parts[0])
        secs = int(parts[1]) if len(parts) > 1 else 0
        result = round(mins + secs / 60)
        if result == 0 and secs > 0:
            result = 1
        return str(result)
    return minutos_str


def extraer_apellido(first_initial_and_last):
    if '. ' in first_initial_and_last:
        return first_initial_and_last.split('. ', 1)[1]
    return first_initial_and_last


def fetch_match_data(match_id):
    url = f'https://api2.acb.com/api/matchdata/Result/boxscores?matchId={match_id}'
    req = urllib.request.Request(url)
    for k, v in ACB_HEADERS.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def parse_api_data(data):
    teams_data = []

    for team_box in data.get('teamBoxscores', []):
        team_info = team_box.get('team', {})
        team_name = team_info.get('fullName', '')

        head_coach = team_box.get('headCoach', '')

        periods = team_box.get('statsByPeriods', [])

        total_period = next((p for p in periods if p['quarter'] == 0), None)
        if total_period is None:
            continue

        team_points = total_period['stats']['total']['points']
        team_stats = total_period['stats'].get('team', {})
        team_rebotes_extra = team_stats.get('totalRebounds', 0)
        team_valoracion_extra = team_stats.get('rating', 0)

        num_ot = sum(1 for p in periods if p['quarter'] > 4)

        players_raw = total_period['stats']['players']

        starters = [p for p in players_raw if p.get('isStarted')]
        bench = [p for p in players_raw if not p.get('isStarted')]
        ordered_players = starters + bench

        players = []
        for p in ordered_players:
            play_time = p.get('playTime', '00:00')
            if play_time == '00:00' or play_time == '0:00':
                continue

            player_info = p.get('player', {})
            nombre = extraer_apellido(player_info.get('firstInitialAndLastName', ''))
            dorsal = player_info.get('shirtNumber', '')

            minutos = convertir_minutos(play_time)
            puntos = p.get('points', 0)
            t2_enc = p.get('twoPointersMade', 0)
            t2_int = p.get('twoPointersAttempted', 0)
            t3_enc = p.get('threePointersMade', 0)
            t3_int = p.get('threePointersAttempted', 0)
            tl_enc = p.get('freeThrowsMade', 0)
            tl_int = p.get('freeThrowsAttempted', 0)
            rebotes = p.get('totalRebounds', 0)
            asistencias = p.get('assists', 0)
            valoracion = p.get('rating', 0)
            titular = p.get('isStarted', False)

            players.append({
                'dorsal': dorsal,
                'nombre': nombre,
                'minutos': minutos,
                'puntos': str(puntos),
                't2_enc': t2_enc, 't2_int': t2_int,
                't3_enc': t3_enc, 't3_int': t3_int,
                'tl_enc': tl_enc, 'tl_int': tl_int,
                'rebotes': str(rebotes),
                'asistencias': str(asistencias),
                'valoracion': str(valoracion),
                'titular': titular,
            })

        teams_data.append({
            'nombre': team_name,
            'puntuacion': str(team_points),
            'jugadores': players,
            'entrenador': head_coach,
            'periods': periods,
            'team_rebotes_extra': team_rebotes_extra,
            'team_valoracion_extra': team_valoracion_extra,
            'num_ot': num_ot,
        })

    parciales_parts = []
    if len(teams_data) == 2:
        t1_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[0]['periods']}
        t2_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[1]['periods']}
        quarters = sorted(q for q in t1_periods if q > 0)
        for q in quarters:
            parciales_parts.append(f"{t1_periods[q]}-{t2_periods[q]}")

    info_adicional = {
        'parciales': ' '.join(parciales_parts),
        'arbitros': ', '.join(data.get('referees', [])),
    }

    return teams_data, info_adicional


def td_val(parent, value):
    td = ET.SubElement(parent, 'td')
    if value and value != '0':
        td.text = value
    return td


def td_tiro(parent, enc, intentos):
    td = ET.SubElement(parent, 'td')
    fmt = convertir_tiros_formato(enc, intentos)
    if fmt:
        td.text = fmt
    return td


def create_xml(teams_data, info_adicional):
    doc = ET.Element('doc')
    doc.set('xml:lang', 'es')

    story = ET.SubElement(doc, 'story')
    text_el = ET.SubElement(story, 'text')
    content = ET.SubElement(text_el, 'content')

    for team in teams_data:
        table = ET.SubElement(content, 'table')
        table.set('class', 'fichabas_auto')

        header_row = ET.SubElement(table, 'tr')
        header_cell = ET.SubElement(header_row, 'td')
        header_cell.set('colspan', '11')
        header_cell.set('class', 'cabecera')
        header_cell.text = f"{team['nombre']}, {team['puntuacion']}"

        titles_row = ET.SubElement(table, 'tr')
        titles_row.set('class', 'valores titulos')
        for title in ['', 'Jugador', 'PTS', '2P', '3P', 'TL', 'RT', 'AS', 'MJ', 'V', '']:
            td = ET.SubElement(titles_row, 'td')
            if title:
                td.text = title

        totales = {
            'puntos': 0,
            't2_enc': 0, 't2_int': 0,
            't3_enc': 0, 't3_int': 0,
            'tl_enc': 0, 'tl_int': 0,
            'rebotes': 0,
            'asistencias': 0,
            'valoracion': 0,
        }

        jugadores_con_relleno = list(team['jugadores'])
        while len(jugadores_con_relleno) < 12:
            jugadores_con_relleno.append(None)

        for player in jugadores_con_relleno:
            row = ET.SubElement(table, 'tr')
            row.set('class', 'valores')

            if player is None:
                for _ in range(11):
                    ET.SubElement(row, 'td')
            else:
                ET.SubElement(row, 'td')

                nombre_cell = ET.SubElement(row, 'td')
                if player.get('titular', False):
                    span = ET.SubElement(nombre_cell, 'span')
                    span.set('class', 'negrita jug')
                    span.text = player['nombre']
                else:
                    nombre_cell.text = player['nombre']

                td_val(row, player['puntos'])
                td_tiro(row, player['t2_enc'], player['t2_int'])
                td_tiro(row, player['t3_enc'], player['t3_int'])
                td_tiro(row, player['tl_enc'], player['tl_int'])
                td_val(row, player['rebotes'])
                td_val(row, player['asistencias'])

                mj_td = ET.SubElement(row, 'td')
                mj_td.text = player['minutos']

                val_td = ET.SubElement(row, 'td')
                val_td.text = player['valoracion']

                ET.SubElement(row, 'td')

                try:
                    totales['puntos'] += int(player['puntos'])
                except (ValueError, TypeError):
                    pass

                totales['t2_enc'] += player['t2_enc']
                totales['t2_int'] += player['t2_int']
                totales['t3_enc'] += player['t3_enc']
                totales['t3_int'] += player['t3_int']
                totales['tl_enc'] += player['tl_enc']
                totales['tl_int'] += player['tl_int']

                try:
                    totales['rebotes'] += int(player['rebotes'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['asistencias'] += int(player['asistencias'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['valoracion'] += int(player['valoracion'])
                except (ValueError, TypeError):
                    pass

        tot_row = ET.SubElement(table, 'tr')
        tot_row.set('class', 'totales')
        ET.SubElement(tot_row, 'td')
        ET.SubElement(tot_row, 'td').text = 'Totales'
        ET.SubElement(tot_row, 'td').text = str(totales['puntos'])

        def tot_tiro_td(parent, enc, int_v):
            td = ET.SubElement(parent, 'td')
            td.text = f"{enc}-{int_v}" if int_v > 0 else ''
            return td

        tot_tiro_td(tot_row, totales['t2_enc'], totales['t2_int'])
        tot_tiro_td(tot_row, totales['t3_enc'], totales['t3_int'])
        tot_tiro_td(tot_row, totales['tl_enc'], totales['tl_int'])

        total_rebotes = totales['rebotes'] + team.get('team_rebotes_extra', 0)
        total_valoracion = totales['valoracion'] + team.get('team_valoracion_extra', 0)
        minutos_partido = 200 + team.get('num_ot', 0) * 25

        td_reb = ET.SubElement(tot_row, 'td')
        td_reb.text = str(total_rebotes) if total_rebotes > 0 else ''

        td_ast = ET.SubElement(tot_row, 'td')
        td_ast.text = str(totales['asistencias']) if totales['asistencias'] > 0 else ''

        ET.SubElement(tot_row, 'td').text = str(minutos_partido)
        ET.SubElement(tot_row, 'td').text = str(total_valoracion)
        ET.SubElement(tot_row, 'td')

        is_last_team = (team is teams_data[-1])

        entr_row = ET.SubElement(table, 'tr')
        entr_row.set('class', 'margenesfilete')
        ET.SubElement(entr_row, 'td')
        entr_lbl = ET.SubElement(entr_row, 'td')
        entr_lbl.set('class', 'negrita')
        entr_lbl.text = 'Entrenador:'
        entr_val = ET.SubElement(entr_row, 'td')
        entr_val.set('class', 'left')
        entr_val.set('colspan', '8')
        entr_val.text = f"\u2002{team.get('entrenador', '')}"
        ET.SubElement(entr_row, 'td')

        if is_last_team:
            def add_info_row(parent, label, value=''):
                row = ET.SubElement(parent, 'tr')
                row.set('class', 'margenesfilete')
                ET.SubElement(row, 'td')
                cell = ET.SubElement(row, 'td')
                cell.set('class', 'left')
                cell.set('colspan', '9')
                span = ET.SubElement(cell, 'span')
                span.set('class', 'negrita')
                span.text = label
                span.tail = value
                ET.SubElement(row, 'td')
                return row

            add_info_row(table, 'Parciales: ', info_adicional.get('parciales', ''))
            add_info_row(table, 'Árbitros: ', info_adicional.get('arbitros', ''))

            cab = ET.SubElement(table, 'tr')
            cab_cell = ET.SubElement(cab, 'td')
            cab_cell.set('class', 'rojo')
            cab_cell.set('colspan', '11')

    xml_string = ET.tostring(doc, encoding='utf-8', method='xml')
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent='\t', encoding='utf-8')
    return pretty_xml


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        match_id = str(data.get('matchId', '')).strip()

        if not match_id:
            return jsonify({'error': 'Por favor, introduce el número de partido'}), 400

        try:
            api_data = fetch_match_data(match_id)
        except Exception as e:
            return jsonify({'error': f'Error al conectar con la API de ACB: {str(e)}'}), 502

        teams_data, info_adicional = parse_api_data(api_data)

        if not teams_data:
            return jsonify({'error': 'No se encontraron datos para este partido'}), 404

        xml_content = create_xml(teams_data, info_adicional)
        xml_str = xml_content.decode('utf-8')

        return jsonify({'success': True, 'xml': xml_str})

    except Exception as e:
        return jsonify({'error': f'Error al generar el XML: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
from flask import Flask, render_template, request, jsonify
import xml.etree.ElementTree as ET
from xml.dom import minidom
import urllib.request
import json

app = Flask(__name__)

ACB_HEADERS = {
    'x-apikey': '0dd94928-6f57-4c08-a3bd-b1b2f092976e',
    'origin': 'https://live.acb.com',
    'referer': 'https://live.acb.com/',
}


def convertir_tiros_formato(enc, intentos):
    if enc == 0 and intentos == 0:
        return ''
    return f"{enc}-{intentos}"


def convertir_minutos(minutos_str):
    if ':' in minutos_str:
        parts = minutos_str.split(':')
        mins = int(parts[0])
        secs = int(parts[1]) if len(parts) > 1 else 0
        result = round(mins + secs / 60)
        if result == 0 and secs > 0:
            result = 1
        return str(result)
    return minutos_str


def extraer_apellido(first_initial_and_last):
    if '. ' in first_initial_and_last:
        return first_initial_and_last.split('. ', 1)[1]
    return first_initial_and_last


def fetch_match_data(match_id):
    url = f'https://api2.acb.com/api/matchdata/Result/boxscores?matchId={match_id}'
    req = urllib.request.Request(url)
    for k, v in ACB_HEADERS.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def parse_api_data(data):
    teams_data = []

    for team_box in data.get('teamBoxscores', []):
        team_info = team_box.get('team', {})
        team_name = team_info.get('fullName', '')

        head_coach = team_box.get('headCoach', '')

        periods = team_box.get('statsByPeriods', [])

        total_period = next((p for p in periods if p['quarter'] == 0), None)
        if total_period is None:
            continue

        team_points = total_period['stats']['total']['points']
        team_stats = total_period['stats'].get('team', {})
        team_rebotes_extra = team_stats.get('totalRebounds', 0)
        team_valoracion_extra = team_stats.get('rating', 0)

        num_ot = sum(1 for p in periods if p['quarter'] > 4)

        players_raw = total_period['stats']['players']

        starters = [p for p in players_raw if p.get('isStarted')]
        bench = [p for p in players_raw if not p.get('isStarted')]
        ordered_players = starters + bench

        players = []
        for p in ordered_players:
            play_time = p.get('playTime', '00:00')
            if play_time == '00:00' or play_time == '0:00':
                continue

            player_info = p.get('player', {})
            nombre = extraer_apellido(player_info.get('firstInitialAndLastName', ''))
            dorsal = player_info.get('shirtNumber', '')

            minutos = convertir_minutos(play_time)
            puntos = p.get('points', 0)
            t2_enc = p.get('twoPointersMade', 0)
            t2_int = p.get('twoPointersAttempted', 0)
            t3_enc = p.get('threePointersMade', 0)
            t3_int = p.get('threePointersAttempted', 0)
            tl_enc = p.get('freeThrowsMade', 0)
            tl_int = p.get('freeThrowsAttempted', 0)
            rebotes = p.get('totalRebounds', 0)
            asistencias = p.get('assists', 0)
            valoracion = p.get('rating', 0)
            titular = p.get('isStarted', False)

            players.append({
                'dorsal': dorsal,
                'nombre': nombre,
                'minutos': minutos,
                'puntos': str(puntos),
                't2_enc': t2_enc, 't2_int': t2_int,
                't3_enc': t3_enc, 't3_int': t3_int,
                'tl_enc': tl_enc, 'tl_int': tl_int,
                'rebotes': str(rebotes),
                'asistencias': str(asistencias),
                'valoracion': str(valoracion),
                'titular': titular,
            })

        teams_data.append({
            'nombre': team_name,
            'puntuacion': str(team_points),
            'jugadores': players,
            'entrenador': head_coach,
            'periods': periods,
            'team_rebotes_extra': team_rebotes_extra,
            'team_valoracion_extra': team_valoracion_extra,
            'num_ot': num_ot,
        })

    parciales_parts = []
    if len(teams_data) == 2:
        t1_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[0]['periods']}
        t2_periods = {p['quarter']: p['stats']['total']['points']
                      for p in teams_data[1]['periods']}
        quarters = sorted(q for q in t1_periods if q > 0)
        for q in quarters:
            parciales_parts.append(f"{t1_periods[q]}-{t2_periods[q]}")

    info_adicional = {
        'parciales': ' '.join(parciales_parts),
        'arbitros': ', '.join(data.get('referees', [])),
    }

    return teams_data, info_adicional


def td_val(parent, value):
    td = ET.SubElement(parent, 'td')
    if value and value != '0':
        td.text = value
    return td


def td_tiro(parent, enc, intentos):
    td = ET.SubElement(parent, 'td')
    fmt = convertir_tiros_formato(enc, intentos)
    if fmt:
        td.text = fmt
    return td


def create_xml(teams_data, info_adicional):
    doc = ET.Element('doc')
    doc.set('xml:lang', 'es')

    story = ET.SubElement(doc, 'story')
    text_el = ET.SubElement(story, 'text')
    content = ET.SubElement(text_el, 'content')

    for team in teams_data:
        table = ET.SubElement(content, 'table')
        table.set('class', 'fichabas_auto')

        header_row = ET.SubElement(table, 'tr')
        header_cell = ET.SubElement(header_row, 'td')
        header_cell.set('colspan', '11')
        header_cell.set('class', 'cabecera')
        header_cell.text = f"{team['nombre']}, {team['puntuacion']}"

        titles_row = ET.SubElement(table, 'tr')
        titles_row.set('class', 'valores titulos')
        for title in ['', 'Jugador', 'PTS', '2P', '3P', 'TL', 'RT', 'AS', 'MJ', 'V', '']:
            td = ET.SubElement(titles_row, 'td')
            if title:
                td.text = title

        totales = {
            'puntos': 0,
            't2_enc': 0, 't2_int': 0,
            't3_enc': 0, 't3_int': 0,
            'tl_enc': 0, 'tl_int': 0,
            'rebotes': 0,
            'asistencias': 0,
            'valoracion': 0,
        }

        jugadores_con_relleno = list(team['jugadores'])
        while len(jugadores_con_relleno) < 12:
            jugadores_con_relleno.append(None)

        for player in jugadores_con_relleno:
            row = ET.SubElement(table, 'tr')
            row.set('class', 'valores')

            if player is None:
                for _ in range(11):
                    ET.SubElement(row, 'td')
            else:
                ET.SubElement(row, 'td')

                nombre_cell = ET.SubElement(row, 'td')
                if player.get('titular', False):
                    span = ET.SubElement(nombre_cell, 'span')
                    span.set('class', 'negrita jug')
                    span.text = player['nombre']
                else:
                    nombre_cell.text = player['nombre']

                td_val(row, player['puntos'])
                td_tiro(row, player['t2_enc'], player['t2_int'])
                td_tiro(row, player['t3_enc'], player['t3_int'])
                td_tiro(row, player['tl_enc'], player['tl_int'])
                td_val(row, player['rebotes'])
                td_val(row, player['asistencias'])

                mj_td = ET.SubElement(row, 'td')
                mj_td.text = player['minutos']

                val_td = ET.SubElement(row, 'td')
                val_td.text = player['valoracion']

                ET.SubElement(row, 'td')

                try:
                    totales['puntos'] += int(player['puntos'])
                except (ValueError, TypeError):
                    pass

                totales['t2_enc'] += player['t2_enc']
                totales['t2_int'] += player['t2_int']
                totales['t3_enc'] += player['t3_enc']
                totales['t3_int'] += player['t3_int']
                totales['tl_enc'] += player['tl_enc']
                totales['tl_int'] += player['tl_int']

                try:
                    totales['rebotes'] += int(player['rebotes'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['asistencias'] += int(player['asistencias'])
                except (ValueError, TypeError):
                    pass

                try:
                    totales['valoracion'] += int(player['valoracion'])
                except (ValueError, TypeError):
                    pass

        tot_row = ET.SubElement(table, 'tr')
        tot_row.set('class', 'totales')
        ET.SubElement(tot_row, 'td')
        ET.SubElement(tot_row, 'td').text = 'Totales'
        ET.SubElement(tot_row, 'td').text = str(totales['puntos'])

        def tot_tiro_td(parent, enc, int_v):
            td = ET.SubElement(parent, 'td')
            td.text = f"{enc}-{int_v}" if int_v > 0 else ''
            return td

        tot_tiro_td(tot_row, totales['t2_enc'], totales['t2_int'])
        tot_tiro_td(tot_row, totales['t3_enc'], totales['t3_int'])
        tot_tiro_td(tot_row, totales['tl_enc'], totales['tl_int'])

        total_rebotes = totales['rebotes'] + team.get('team_rebotes_extra', 0)
        total_valoracion = totales['valoracion'] + team.get('team_valoracion_extra', 0)
        minutos_partido = 200 + team.get('num_ot', 0) * 25

        td_reb = ET.SubElement(tot_row, 'td')
        td_reb.text = str(total_rebotes) if total_rebotes > 0 else ''

        td_ast = ET.SubElement(tot_row, 'td')
        td_ast.text = str(totales['asistencias']) if totales['asistencias'] > 0 else ''

        ET.SubElement(tot_row, 'td').text = str(minutos_partido)
        ET.SubElement(tot_row, 'td').text = str(total_valoracion)
        ET.SubElement(tot_row, 'td')

        is_last_team = (team is teams_data[-1])

        entr_row = ET.SubElement(table, 'tr')
        entr_row.set('class', 'margenesfilete')
        ET.SubElement(entr_row, 'td')
        entr_lbl = ET.SubElement(entr_row, 'td')
        entr_lbl.set('class', 'negrita')
        entr_lbl.text = 'Entrenador:'
        entr_val = ET.SubElement(entr_row, 'td')
        entr_val.set('class', 'left')
        entr_val.set('colspan', '8')
        entr_val.text = f"\u2002{team.get('entrenador', '')}"
        ET.SubElement(entr_row, 'td')

        if is_last_team:
            def add_info_row(parent, label, value=''):
                row = ET.SubElement(parent, 'tr')
                row.set('class', 'margenesfilete')
                ET.SubElement(row, 'td')
                cell = ET.SubElement(row, 'td')
                cell.set('class', 'left')
                cell.set('colspan', '9')
                span = ET.SubElement(cell, 'span')
                span.set('class', 'negrita')
                span.text = label
                span.tail = value
                ET.SubElement(row, 'td')
                return row

            add_info_row(table, 'Parciales: ', info_adicional.get('parciales', ''))
            add_info_row(table, 'Árbitros: ', info_adicional.get('arbitros', ''))

            cab = ET.SubElement(table, 'tr')
            cab_cell = ET.SubElement(cab, 'td')
            cab_cell.set('class', 'rojo')
            cab_cell.set('colspan', '11')

    xml_string = ET.tostring(doc, encoding='utf-8', method='xml')
    dom = minidom.parseString(xml_string)
    pretty_xml = dom.toprettyxml(indent='\t', encoding='utf-8')
    return pretty_xml


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        match_id = str(data.get('matchId', '')).strip()

        if not match_id:
            return jsonify({'error': 'Por favor, introduce el número de partido'}), 400

        try:
            api_data = fetch_match_data(match_id)
        except Exception as e:
            return jsonify({'error': f'Error al conectar con la API de ACB: {str(e)}'}), 502

        teams_data, info_adicional = parse_api_data(api_data)

        if not teams_data:
            return jsonify({'error': 'No se encontraron datos para este partido'}), 404

        xml_content = create_xml(teams_data, info_adicional)
        xml_str = xml_content.decode('utf-8')

        return jsonify({'success': True, 'xml': xml_str})

    except Exception as e:
        return jsonify({'error': f'Error al generar el XML: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
