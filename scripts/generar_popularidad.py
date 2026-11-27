#!/usr/bin/env python3
"""
Genera data/popularidad.json: qué tan buscado es cada pueblo, playa y distrito, medido con
las visitas a su artículo de Wikipedia (español + inglés) en los últimos 12 meses completos.

Uso (solo biblioteca estándar):
    python scripts/generar_popularidad.py --descargar   # baja Wikidata y las visitas a fuentes/popularidad/
    python scripts/generar_popularidad.py               # reconstruye data/popularidad.json

Método:
  1. Wikidata: todos los elementos con país Costa Rica (P17 = Q800), coordenadas (P625) y
     artículo en es.wikipedia o en.wikipedia.
  2. Visitas: API de páginas vistas de Wikimedia (solo personas, todos los accesos), sumando
     los 12 meses y los dos idiomas.
  3. Cada punto de Wikidata se ubica en su distrito con los polígonos oficiales del IGN.
     Cruce con un pueblo o playa: el nombre coincide (etiqueta o título del artículo, sin
     ", Costa Rica" ni aclaraciones entre paréntesis), el punto queda a 6 km o menos y cae en el
     mismo cantón (Escazú cruza con el artículo del cantón de Escazú, pero San Antonio de
     Alajuela no cruza con San Antonio de Belén). Cruce con un distrito: el nombre coincide y el
     punto cae en el mismo cantón (ahí los nombres de distrito no se repiten). Un punto en el mar (playas, islas) se acepta si queda a 2 km
     o menos del borde.
  Si un lugar cruza con varios elementos, cuenta el que tiene más visitas. Un lugar sin
  artículo queda en 0: no se inventa popularidad.
"""
import argparse
import datetime
import json
import math
import os
import re
import subprocess
import time
import unicodedata
import urllib.parse

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(RAIZ, 'fuentes', 'popularidad')  # descargas (no se versionan)
SALIDA = os.path.join(RAIZ, 'data', 'popularidad.json')
AGENTE = 'postalcr-api-data/1.0 (https://postalcr.dev/api/)'
SPARQL = 'https://query.wikidata.org/sparql'
VISTAS = 'https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{wiki}/all-access/user/{titulo}/monthly/{desde}00/{hasta}00'
DIST_PUEBLO_KM = 6.0
DIST_BORDE_KM = 2.0

CONSULTA = """
SELECT ?i ?les ?len ?c ?es ?en WHERE {
  ?i wdt:P17 wd:Q800; wdt:P625 ?c.
  OPTIONAL { ?es schema:about ?i; schema:isPartOf <https://es.wikipedia.org/>. }
  OPTIONAL { ?en schema:about ?i; schema:isPartOf <https://en.wikipedia.org/>. }
  FILTER(BOUND(?es) || BOUND(?en))
  OPTIONAL { ?i rdfs:label ?les FILTER(lang(?les) = "es") }
  OPTIONAL { ?i rdfs:label ?len FILTER(lang(?len) = "en") }
}"""


def periodo(hoy=None):
    """Los 12 meses completos anteriores al mes en curso, como (AAAAMMDD inicio, AAAAMMDD fin)."""
    hoy = hoy or datetime.date.today()
    fin = hoy.replace(day=1) - datetime.timedelta(days=1)
    ini = (fin.replace(day=1) - datetime.timedelta(days=330)).replace(day=1)
    return ini.strftime('%Y%m%d'), fin.strftime('%Y%m%d')


def pedir(url, intentos=4):
    """GET con curl (usa los certificados del sistema). None si la página no existe (404)."""
    for n in range(intentos):
        r = subprocess.run(['curl', '-sS', '-L', '-A', AGENTE, '-H', 'Accept: application/json',
                            '--max-time', '90', '-w', '\\n%{http_code}', url], capture_output=True, text=True)
        cuerpo, _, codigo = r.stdout.rpartition('\n')
        if codigo == '404':
            return None
        if r.returncode == 0 and codigo == '200':
            return json.loads(cuerpo)
        if n == intentos - 1:
            raise RuntimeError(f'{url}: {codigo or r.stderr.strip()}')
        time.sleep(2 ** n)


def descargar():
    os.makedirs(CACHE, exist_ok=True)
    url = SPARQL + '?' + urllib.parse.urlencode({'query': CONSULTA, 'format': 'json'})
    filas = pedir(url)['results']['bindings']
    elementos = {}
    for f in filas:
        qid = f['i']['value'].rsplit('/', 1)[1]
        m = re.match(r'Point\(([-\d.]+) ([-\d.]+)\)', f['c']['value'])
        if not m:
            continue
        e = elementos.setdefault(qid, {'qid': qid, 'coordenadas': [], 'es': None, 'en': None,
                                       'etiquetas': set()})
        punto = [round(float(m.group(2)), 5), round(float(m.group(1)), 5)]
        if punto not in e['coordenadas']:
            e['coordenadas'].append(punto)
        for lado in ('es', 'en'):
            if lado in f:
                e[lado] = urllib.parse.unquote(f[lado]['value'].rsplit('/wiki/', 1)[1])
        for k in ('les', 'len'):
            if k in f:
                e['etiquetas'].add(f[k]['value'])
    desde, hasta = periodo()
    for n, e in enumerate(elementos.values(), 1):
        e['etiquetas'] = sorted(e['etiquetas'])
        e['visitas'] = {}
        for lado in ('es', 'en'):
            if not e[lado]:
                continue
            titulo = urllib.parse.quote(e[lado], safe='')
            d = pedir(VISTAS.format(wiki=f'{lado}.wikipedia', titulo=titulo, desde=desde, hasta=hasta))
            e['visitas'][lado] = sum(i['views'] for i in (d or {}).get('items', []))
            time.sleep(0.05)
        if n % 100 == 0:
            print(f'   {n}/{len(elementos)} artículos')
    with open(os.path.join(CACHE, 'wikidata.json'), 'w', encoding='utf-8') as f:
        json.dump({'desde': desde, 'hasta': hasta, 'descargado': datetime.date.today().isoformat(),
                   'elementos': list(elementos.values())}, f, ensure_ascii=False)
    print(f'   {len(elementos)} elementos de Wikidata con artículo, visitas de {desde} a {hasta}')


def norm(s):
    s = unicodedata.normalize('NFD', s)
    s = ''.join(ch for ch in s if unicodedata.category(ch) != 'Mn').lower()
    s = s.replace('_', ' ')
    s = re.sub(r'\s*\(.*?\)\s*', ' ', s)
    s = re.sub(r',\s*(costa rica|provincia de .*|.* province|canton .*|.* canton)$', '', s)
    s = re.sub(r'[^a-z0-9]+', ' ', s).strip()
    return s


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def dentro(punto, multipoligono):
    """Punto [lat, lon] dentro de un MultiPolygon GeoJSON ([lon, lat])."""
    y, x = punto
    for poligono in multipoligono:
        anillo = poligono[0]
        adentro = False
        for (x1, y1), (x2, y2) in zip(anillo, anillo[1:] + anillo[:1]):
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                adentro = not adentro
        if adentro and not any(_en_anillo(x, y, h) for h in poligono[1:]):
            return True
    return False


def _en_anillo(x, y, anillo):
    adentro = False
    for (x1, y1), (x2, y2) in zip(anillo, anillo[1:] + anillo[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            adentro = not adentro
    return adentro


def cerca_del_borde(punto, multipoligono, limite):
    return any(km(punto, (v[1], v[0])) <= limite for pol in multipoligono for v in pol[0])


def construir():
    with open(os.path.join(CACHE, 'wikidata.json'), encoding='utf-8') as f:
        wd = json.load(f)
    leer = lambda n: json.load(open(os.path.join(RAIZ, 'data', n), encoding='utf-8'))
    pueblos, dta, geo = leer('pueblos.json')['pueblos'], leer('dta.json'), leer('geo.json')['distritos']

    cajas = {}
    for cod, g in geo.items():
        xs = [v[0] for pol in g['contorno'] for v in pol[0]]
        ys = [v[1] for pol in g['contorno'] for v in pol[0]]
        cajas[cod] = (min(ys), min(xs), max(ys), max(xs))

    def distrito_de(punto):
        for cod, (y0, x0, y1, x1) in cajas.items():
            if y0 <= punto[0] <= y1 and x0 <= punto[1] <= x1 and dentro(punto, geo[cod]['contorno']):
                return cod
        return None

    def cerca(punto, codigos):
        return any(cerca_del_borde(punto, geo[c]['contorno'], DIST_BORDE_KM) for c in codigos)

    por_nombre = {}
    for e in wd['elementos']:
        e['distritos'] = [distrito_de(c) for c in e['coordenadas']]
        e['total'] = sum(e['visitas'].values())
        if not e['total']:
            continue
        nombres = {norm(x) for x in e['etiquetas']} | {norm(e[l]) for l in ('es', 'en') if e[l]}
        for n in nombres - {''}:
            por_nombre.setdefault(n, []).append(e)

    def mejor(candidatos):
        return max(candidatos, key=lambda e: e['total']) if candidatos else None

    def ficha(e):
        return {'visitas': e['total'], 'wikidata': e['qid'],
                'articulos': {l: e[l] for l in ('es', 'en') if e[l]}}

    lugares = {}
    for pu in pueblos:
        if not pu.get('coordenadas'):
            continue
        nombres = {norm(pu['nombre'])} | {norm(a) for a in pu.get('alias', [])}
        canton = pu['distrito'][:3]
        del_canton = [c for c in geo if c.startswith(canton)]
        cand = [e for n in nombres for e in por_nombre.get(n, [])
                if any(km(pu['coordenadas'], c) <= DIST_PUEBLO_KM
                       and (d[:3] == canton if d else cerca(c, del_canton))
                       for c, d in zip(e['coordenadas'], e['distritos']))]
        e = mejor(cand)
        if e:
            lugares[f"{pu['nombre']}|{pu['distrito']}|{pu['tipo']}"] = ficha(e)

    distritos = {}
    for p in dta['provincias']:
        for c in p['cantones']:
            for d in c['distritos']:
                contorno = geo[d['codigo']]['contorno']
                # Dentro de un cantón no se repiten los nombres de distrito: basta con que el
                # punto caiga en el mismo cantón (Wikidata a veces lo pone en la cabecera vecina).
                cand = [e for e in por_nombre.get(norm(d['nombre']), [])
                        if any(dd[:3] == c['codigo'] if dd else cerca_del_borde(pt, contorno, DIST_BORDE_KM)
                               for pt, dd in zip(e['coordenadas'], e['distritos']))]
                e = mejor(cand)
                if e:
                    distritos[d['codigo']] = ficha(e)

    desde, hasta = wd['desde'], wd['hasta']
    salida = {
        'fuente': {
            'nombre': 'Visitas a Wikipedia (español e inglés)',
            'institucion': 'Wikimedia Foundation (API de páginas vistas) y Wikidata',
            'url': 'https://wikimedia.org/api/rest_v1/#/Pageviews%20data',
            'periodo': {'desde': f'{desde[:4]}-{desde[4:6]}-{desde[6:]}', 'hasta': f'{hasta[:4]}-{hasta[4:6]}-{hasta[6:]}'},
            'descargado': wd['descargado'],
        },
        'metodo': ('Visitas de personas (sin bots) al artículo de Wikipedia del lugar en español e inglés, '
                   'sumadas en 12 meses. El artículo se identifica en Wikidata: mismo nombre, a 6 km o menos del pueblo '
                   'o playa y en su mismo cantón (puede ser el artículo del pueblo, de su distrito o de su cantón '
                   'si se llaman igual), o, para un distrito, con el mismo nombre dentro de su cantón. Un lugar sin artículo queda en 0.'),
        'lugares': dict(sorted(lugares.items())),
        'distritos': dict(sorted(distritos.items())),
    }
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)
        f.write('\n')
    print(f'   {len(lugares)} pueblos y playas y {len(distritos)} distritos con artículo en Wikipedia')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--descargar', action='store_true')
    args = ap.parse_args()
    if args.descargar:
        descargar()
    construir()
