"""Genera la API estática de PostalCR en public/ a partir de data/.

Uso:
    python scripts/generar_api.py

Solo usa la biblioteca estándar. Borra y vuelve a crear todo lo que genera (las rutas JSON,
openapi.json y llms.txt); no toca _headers, _redirects ni robots.txt, que se editan a mano.
"""
import json
import math
import re
import shutil
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PUBLIC = RAIZ / 'public'

# Versión de la API (semver): mayor = cambios que rompen integraciones, menor = rutas o campos
# nuevos, parche = correcciones de datos. Se publica en /meta.json, /openapi.json y en cada release.
VERSION = '2.1.0'
API = 'https://api.postalcr.dev'
SITIO = 'https://postalcr.dev'
REPO = 'https://github.com/ryze-cr/postalcr-api'

GENERADOS = ['provincias.json', 'provincias', 'cantones.json', 'cantones', 'distritos.json', 'distritos',
             'pueblos.json', 'populares.json', 'distritos.geojson', 'gam.json', 'todo.json', 'meta.json', 'openapi.json', 'llms.txt', '_redirects']


def slug(texto):
    s = unicodedata.normalize('NFD', texto).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def leer(nombre):
    ruta = RAIZ / 'data' / nombre
    return json.loads(ruta.read_text(encoding='utf-8')) if ruta.exists() else None


def escribir(ruta, datos):
    destino = PUBLIC / ruta
    destino.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(datos, str):
        destino.write_text(datos, encoding='utf-8')
    else:
        destino.write_text(json.dumps(datos, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')


def escala_popularidad(pop):
    """Visitas de 12 meses -> índice 0-100 en escala logarítmica (100 = el lugar más visitado).
    Sin artículo en Wikipedia = 0. Devuelve dos funciones: para un lugar y para un distrito."""
    lugares, distritos = pop.get('lugares', {}), pop.get('distritos', {})
    tope = max([v['visitas'] for v in [*lugares.values(), *distritos.values()]] or [0])

    def indice(ficha):
        if not ficha or not tope:
            return 0
        return max(1, round(100 * math.log10(1 + ficha['visitas']) / math.log10(1 + tope)))
    return (lambda pu: indice(lugares.get(f"{pu['nombre']}|{pu['distrito']}|{pu['tipo']}")),
            lambda codigo: indice(distritos.get(codigo)))


def construir():
    """Arma todos los recursos de la API en memoria. validar.py usa esta misma función."""
    dta = leer('dta.json')
    pop = leer('popularidad.json') or {}
    pop_lugar, pop_distrito = escala_popularidad(pop)
    clasificacion = leer('gam.json')
    datos_pueblos = leer('pueblos.json') or {'fuente': [], 'pueblos': []}
    geo = leer('geo.json')
    en_gam = set(clasificacion['gam'])

    por_distrito = {}
    for pu in datos_pueblos['pueblos']:
        por_distrito.setdefault(pu['distrito'], []).append(pu)

    provincias, cantones, distritos, recursos = [], [], [], {}
    for p in dta['provincias']:
        ref_p = {'codigo': p['codigo'], 'nombre': p['nombre']}
        url_p = f"{SITIO}/{slug(p['nombre'])}/"
        resumen_cantones = []
        for c in p['cantones']:
            ref_c = {'codigo': c['codigo'], 'nombre': c['nombre']}
            url_c = f"{url_p}{slug(c['nombre'])}/"
            resumen_distritos = []
            for d in c['distritos']:
                distrito = {
                    'codigo_postal': d['codigo'],
                    'nombre': d['nombre'],
                    'canton': ref_c,
                    'provincia': ref_p,
                    'etiqueta': f"{d['nombre']}, {c['nombre']}, {p['nombre']}",
                    'area_km2': d['area_km2'],
                    'gam': d['codigo'] in en_gam,
                    'popularidad': pop_distrito(d['codigo']),
                    'centro': geo['distritos'][d['codigo']]['centro'],
                    'vecinos': geo['distritos'][d['codigo']]['vecinos'],
                    'pueblos': sorted({pu['nombre'] for pu in por_distrito.get(d['codigo'], [])}),
                    'url': f"{url_c}{slug(d['nombre'])}/",
                }
                distritos.append(distrito)
                recursos[f"distritos/{d['codigo']}.json"] = distrito
                resumen_distritos.append({k: distrito[k] for k in ('codigo_postal', 'nombre', 'gam', 'url')})
            canton = {**ref_c, 'provincia': ref_p, 'area_km2': c['area_km2'],
                      'distritos': len(c['distritos']), 'url': url_c}
            cantones.append(canton)
            recursos[f"cantones/{c['codigo']}.json"] = {**canton, 'distritos': resumen_distritos}
            resumen_cantones.append({k: canton[k] for k in ('codigo', 'nombre', 'distritos', 'url')})
        provincia = {**ref_p, 'area_km2': p['area_km2'], 'cantones': len(p['cantones']),
                     'distritos': sum(c['distritos'] for c in resumen_cantones), 'url': url_p}
        provincias.append(provincia)
        recursos[f"provincias/{p['codigo']}.json"] = {**provincia, 'cantones': resumen_cantones}

    indice = {d['codigo_postal']: d for d in distritos}
    slugs = slugs_lugares(datos_pueblos['pueblos'], indice)
    pueblos = []
    for pu in sorted(datos_pueblos['pueblos'], key=lambda x: (slug(x['nombre']), x['distrito'], x['tipo'])):
        d = indice[pu['distrito']]
        clave = (pu['nombre'], pu['distrito'], pu['tipo'])
        pueblos.append({
            'nombre': pu['nombre'],
            'tipo': pu['tipo'],
            'categoria': pu['categoria'],
            'alias': pu.get('alias', []),
            'codigo_postal': pu['distrito'],
            'distrito': d['nombre'],
            'canton': d['canton']['nombre'],
            'provincia': d['provincia']['nombre'],
            'coordenadas': pu.get('coordenadas'),
            'popularidad': pop_lugar(pu),
            # Los caseríos no tienen página propia: su enlace es la página del distrito.
            'url': f"{SITIO}/lugares/{slugs[clave]}/" if clave in slugs else d['url'],
        })

    # Los lugares más visitados: un artículo de Wikipedia = una entrada (Tamarindo distrito,
    # cabecera y poblado comparten artículo: queda la playa o el pueblo antes que el distrito).
    populares, vistos = [], set()
    ficha_lugar = {f"{pu['nombre']}|{pu['codigo_postal']}|{pu['tipo']}": pu for pu in pueblos}
    candidatos = []
    for clave, f in pop.get('lugares', {}).items():
        pu = ficha_lugar.get(clave)
        if pu and pu['categoria'] != 'Caserío':
            orden = 0 if pu['tipo'] == 'playa' else 1 if pu['categoria'] == 'Poblado' else 2
            candidatos.append((f, orden, {'nombre': pu['nombre'], 'tipo': pu['tipo'], 'categoria': pu['categoria'],
                                          'codigo_postal': pu['codigo_postal'],
                                          'etiqueta': f"{pu['nombre']}, {pu['distrito']}, {pu['canton']}, {pu['provincia']}",
                                          'popularidad': pu['popularidad'], 'url': pu['url']}))
    for codigo, f in pop.get('distritos', {}).items():
        d = indice[codigo]
        candidatos.append((f, 3, {'nombre': d['nombre'], 'tipo': 'distrito', 'categoria': 'Distrito',
                                  'codigo_postal': codigo, 'etiqueta': d['etiqueta'],
                                  'popularidad': d['popularidad'], 'url': d['url']}))
    for f, _, entrada in sorted(candidatos, key=lambda x: (-x[0]['visitas'], x[1], x[2]['nombre'], x[2]['codigo_postal'])):
        if f['wikidata'] in vistos:
            continue
        vistos.add(f['wikidata'])
        art = f['articulos']
        populares.append({**entrada, 'visitas_wikipedia': f['visitas'],
                          'wikipedia': f"https://{'es' if 'es' in art else 'en'}.wikipedia.org/wiki/{art.get('es') or art['en']}".replace(' ', '_')})
        if len(populares) == 200:
            break

    totales = {'provincias': len(provincias), 'cantones': len(cantones), 'distritos': len(distritos),
               'distritos_gam': len(en_gam), 'pueblos': len(pueblos)}
    fuentes = [dta['fuente'], {'nombre': 'Plan GAM 2013-2030', **clasificacion['fuente']}, geo['fuente'],
               *[f for f in datos_pueblos['fuente'] if f.get('capa') not in (geo['fuente']['capa'], 'tabla provincia-cantón-distrito (data/dta.json)')],
               *([pop['fuente']] if pop else [])]
    contornos = {'type': 'FeatureCollection', 'fuente': geo['fuente'], 'nota': geo['metodo'], 'features': [{
        'type': 'Feature',
        'properties': {k: d[k] for k in ('codigo_postal', 'nombre', 'etiqueta', 'gam', 'url')},
        'geometry': {'type': 'MultiPolygon', 'coordinates': geo['distritos'][d['codigo_postal']]['contorno']},
    } for d in distritos]}
    recursos.update({
        'provincias.json': provincias,
        'cantones.json': cantones,
        'distritos.json': distritos,
        'pueblos.json': pueblos,
        'populares.json': {'fuente': pop.get('fuente'), 'metodo': pop.get('metodo'),
                           'escala': 'popularidad: 0 a 100 en escala logarítmica; 100 es el lugar con más visitas, 0 es sin artículo en Wikipedia.',
                           'lugares': populares},
        'distritos.geojson': contornos,
        'gam.json': {'definicion': clasificacion['definicion'], 'criterio': clasificacion['criterio'],
                     'fuente': clasificacion['fuente'], 'gam': clasificacion['gam'], 'no_gam': clasificacion['no_gam']},
        'todo.json': {'version': VERSION, 'provincias': [
            {**recursos[f"provincias/{p['codigo']}.json"], 'cantones': [
                {**{k: v for k, v in recursos[f"cantones/{c['codigo']}.json"].items() if k != 'provincia'},
                 'distritos': [{k: v for k, v in indice[d['codigo']].items() if k not in ('canton', 'provincia')}
                               for d in c['distritos']]}
                for c in p['cantones']]}
            for p in dta['provincias']]},
        'meta.json': {'version': VERSION, 'edicion_dta': dta['fuente']['edicion'], 'totales': totales,
                      'fuentes': fuentes, 'documentacion': f'{SITIO}/api/', 'repositorio': REPO},
    })
    recursos['openapi.json'] = openapi(recursos, dta['fuente']['edicion'], totales)
    recursos['llms.txt'] = llms(dta['fuente']['edicion'], totales)
    recursos['_redirects'] = redirecciones(dta)
    return recursos


# Categorías de lugar que tienen página propia en postalcr.dev (los caseríos solo salen en su distrito).
CON_PAGINA = {'Playa', 'Cabecera de distrito', 'Poblado', 'Territorio/Comunidad indígena'}


def slugs_lugares(lugares, indice):
    """Slug único por lugar con página. Un nombre que se repite lleva el distrito (y si hace falta el
    cantón o el código postal); el slug solo del nombre queda para la página que los lista a todos."""
    con_pagina = [pu for pu in lugares if pu['categoria'] in CON_PAGINA]
    grupos = {}
    for pu in con_pagina:
        grupos.setdefault(slug(pu['nombre']), []).append(pu)
    usados = set(grupos)  # cada nombre base es una página (el lugar, o la lista de homónimos)
    resultado = {}
    for base, grupo in sorted(grupos.items()):
        if len(grupo) == 1:
            pu = grupo[0]
            resultado[(pu['nombre'], pu['distrito'], pu['tipo'])] = base
    for base, grupo in sorted(grupos.items()):
        if len(grupo) == 1:
            continue
        for pu in sorted(grupo, key=lambda x: (x['distrito'], x['tipo'])):
            d = indice[pu['distrito']]
            for candidato in (f"{base}-{slug(d['nombre'])}",
                              f"{base}-{slug(d['nombre'])}-{slug(d['canton']['nombre'])}",
                              f"{base}-{d['codigo_postal']}",
                              f"{base}-{pu['tipo']}-{d['codigo_postal']}"):
                if candidato not in usados:
                    break
            else:
                raise ValueError(f"no hay slug libre para {pu['nombre']} ({pu['distrito']})")
            usados.add(candidato)
            resultado[(pu['nombre'], pu['distrito'], pu['tipo'])] = candidato
    return resultado


def redirecciones(dta):
    """Rutas de la v1 (2026-10) que apuntan a su equivalente en v2, más la raíz hacia la documentación."""
    lineas = ['# Generado por scripts/generar_api.py. Rutas de la v1 hacia su equivalente en la v2.',
              f'/ {SITIO}/api/ 302',
              '/provincia/:p/cantones.json /provincias/:p.json 301',
              '/codigo-postal/* /distritos/:splat 301']
    for p in dta['provincias']:
        for c in p['cantones']:
            lineas.append(f"/provincia/{p['codigo']}/canton/{int(c['codigo'][1:])}/distritos.json /cantones/{c['codigo']}.json 301")
    return '\n'.join(lineas) + '\n'


# Rutas documentadas: (ruta, resumen, descripción, recurso de ejemplo, parámetro)
RUTAS = [
    ('/provincias.json', 'Provincias', 'Las 7 provincias con su código, área y cantidad de cantones y distritos.', 'provincias.json', None),
    ('/provincias/{provincia}.json', 'Una provincia y sus cantones', 'Código de provincia de 1 dígito (1–7).', 'provincias/1.json', ('provincia', '1')),
    ('/cantones.json', 'Cantones', 'Los 84 cantones con su provincia.', 'cantones.json', None),
    ('/cantones/{canton}.json', 'Un cantón y sus distritos', 'Código oficial de cantón de 3 dígitos (PCC), por ejemplo 103 = Desamparados.', 'cantones/103.json', ('canton', '103')),
    ('/distritos.json', 'Distritos', 'Los 494 distritos, cada uno con la misma forma que /distritos/{codigoPostal}.json.', 'distritos.json', None),
    ('/distritos/{codigoPostal}.json', 'Un distrito por su código postal', 'Código postal de 5 dígitos (PCCDD): provincia, cantón y distrito.', 'distritos/10305.json', ('codigoPostal', '10305')),
    ('/pueblos.json', 'Pueblos y playas', '6 891 lugares oficiales que no son distritos (pueblos, caseríos, cabeceras, territorios indígenas y playas; fuentes INEC e IGN), con el distrito y el código postal al que pertenecen.', 'pueblos.json', None),
    ('/populares.json', 'Lugares más buscados', 'Los 200 pueblos, playas y distritos más visitados en Wikipedia (español e inglés, últimos 12 meses), de mayor a menor, con su código postal. Sirve para ordenar resultados de búsqueda: Tamarindo antes que un caserío con el mismo nombre.', 'populares.json', None),
    ('/distritos.geojson', 'Contornos de los distritos', 'GeoJSON con el contorno simplificado (120 m) de los 494 distritos, para dibujar mapas. Fuente: límites distritales del IGN (DTA 2026).', 'distritos.geojson', None),
    ('/gam.json', 'Gran Área Metropolitana', 'Códigos postales dentro (gam) y fuera (no_gam) de la GAM, con la definición y el criterio.', 'gam.json', None),
    ('/todo.json', 'Árbol completo', 'Provincias → cantones → distritos en un solo archivo.', 'todo.json', None),
    ('/meta.json', 'Versión y fuentes', 'Versión de la API, edición de la DTA, totales y fuentes oficiales.', 'meta.json', None),
]


def recortar(ejemplo):
    if isinstance(ejemplo, dict) and ejemplo.get('type') == 'FeatureCollection':
        f = ejemplo['features'][0]
        return {**ejemplo, 'features': [{**f, 'geometry': {**f['geometry'], 'coordinates': [[f['geometry']['coordinates'][0][0][:4]]]}}]}
    if isinstance(ejemplo, list):
        return ejemplo[:2]
    if isinstance(ejemplo, dict):
        return {k: (v[:2] if isinstance(v, list) and k not in ('pueblos', 'fuente') else v) for k, v in ejemplo.items()}
    return ejemplo


def openapi(recursos, edicion, totales):
    paths = {}
    for ruta, resumen, descripcion, recurso, param in RUTAS:
        op = {'summary': resumen, 'description': descripcion,
              'responses': {'200': {'description': 'OK', 'content': {'application/json': {'example': recortar(recursos[recurso])}}}}}
        if param:
            op['parameters'] = [{'name': param[0], 'in': 'path', 'required': True,
                                 'schema': {'type': 'string', 'pattern': r'^\d+$'}, 'example': param[1]}]
            op['responses']['404'] = {'description': 'No existe ese código'}
        paths[ruta] = {'get': op}
    return {
        'openapi': '3.1.0',
        'info': {
            'title': 'PostalCR API',
            'version': VERSION,
            'description': (f"API JSON gratuita con las {totales['provincias']} provincias, {totales['cantones']} cantones y "
                            f"{totales['distritos']} distritos de Costa Rica y sus códigos postales, según la División Territorial "
                            f"Administrativa (DTA {edicion}) del Instituto Geográfico Nacional. Sin API key y con CORS abierto. "
                            'Un proyecto de Flashout Labs.'),
            'contact': {'name': 'Flashout Labs', 'url': 'https://flashout.net'},
            'license': {'name': 'MIT', 'url': f'{REPO}/blob/main/LICENSE'},
        },
        'externalDocs': {'description': 'Documentación', 'url': f'{SITIO}/api/'},
        'servers': [{'url': API}],
        'paths': paths,
    }


def llms(edicion, totales):
    lineas = [
        '# PostalCR API',
        '',
        (f"> API JSON gratuita de Flashout Labs con las {totales['provincias']} provincias, {totales['cantones']} cantones y "
         f"{totales['distritos']} distritos de Costa Rica, su código postal oficial y si están en la Gran Área Metropolitana (GAM). "
         f"Datos de la DTA {edicion} del Instituto Geográfico Nacional (IGN). Sin API key, CORS abierto, solo GET."),
        '',
        f'Base URL: `{API}`',
        '',
        'El código postal de Costa Rica tiene 5 dígitos y es el código oficial del distrito: provincia (1 dígito) + cantón (2) + '
        'distrito (2). Ejemplo: 10305 = San Antonio, Desamparados, San José. Los códigos son strings: conservan los ceros.',
        '',
        '## Rutas',
        '',
    ]
    for ruta, resumen, descripcion, recurso, param in RUTAS:
        ejemplo = ruta.replace('{provincia}', '1').replace('{canton}', '103').replace('{codigoPostal}', '10305')
        lineas.append(f'- [{ruta}]({API}{ejemplo}): {resumen}. {descripcion}')
    lineas += [
        '',
        '## Notas',
        '',
        '- Para buscar un distrito por nombre, descargá /distritos.json una vez y filtrá en el cliente (pesa menos de 200 KB).',
        '- Cada distrito trae `url`: la página de ese código postal en postalcr.dev.',
        '- Un pueblo o playa (por ejemplo Tamarindo o Santa Teresa) no es un distrito: /pueblos.json dice a qué distrito y código postal pertenece. Muchos nombres se repiten (hay 54 San Rafael y 7 Santa Teresa): si hay varios, preguntá el cantón o la provincia antes de responder.',
        '- Cada distrito y cada pueblo o playa trae `popularidad` (0 a 100): qué tan visitado es su artículo de Wikipedia en español e inglés en los últimos 12 meses, en escala logarítmica. Usalo para ordenar resultados: entre homónimos, el más popular suele ser el que la persona busca. 0 significa que no tiene artículo, no que no exista. /populares.json trae los 200 más visitados.',
        '',
        '## Más',
        '',
        f'- [Documentación]({SITIO}/api/)',
        f'- [OpenAPI 3.1]({API}/openapi.json)',
        f'- [Código y datos]({REPO})',
        '',
    ]
    return '\n'.join(lineas)


def main():
    for nombre in GENERADOS:
        destino = PUBLIC / nombre
        if destino.is_dir():
            shutil.rmtree(destino)
        elif destino.exists():
            destino.unlink()
    recursos = construir()
    for ruta, datos in recursos.items():
        escribir(ruta, datos)
    m = recursos['meta.json']['totales']
    print(f"PostalCR API {VERSION}: {m['distritos']} distritos, {m['cantones']} cantones, {m['pueblos']} pueblos, "
          f'{len(recursos)} archivos en public/')


if __name__ == '__main__':
    main()
