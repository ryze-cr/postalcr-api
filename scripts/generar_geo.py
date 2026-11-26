#!/usr/bin/env python3
"""Genera data/geo.json: centro, vecinos y contorno simplificado de los 494 distritos.

Uso (requiere shapely y pyproj: pip install -r scripts/requirements.txt):
    python scripts/generar_pueblos.py --descargar   # baja los límites del IGN a fuentes/pueblos/
    python scripts/generar_geo.py

Fuente: IGN, capa IGN_5_CO:limitedistrital_5k (límites distritales 1:5 000 de la DTA 2026),
atributo CÓDIGO_DTA = código postal. Las geometrías vienen en CR-SIRGAS / CRTM05 (metros).

- centro: punto interior representativo (shapely representative_point), en WGS84 (lat, lon).
- vecinos: distritos que comparten un tramo de límite de al menos 20 m (no solo un vértice).
- contorno: polígonos simplificados con tolerancia de 120 m, en WGS84 [lon, lat] con 4 decimales
  (unos 11 m). Se simplifican juntos, como una cobertura (shapely.coverage_simplify): cada
  borde compartido se simplifica una sola vez, así que dos vecinos tienen exactamente el mismo
  borde, sin huecos ni solapes entre ellos. Antes se arreglan los descuadres de la capa del
  IGN (astillas de pocos m² entre límites que no calzan): se recortan todos los límites juntos
  y cada pedazo va al distrito que lo cubre, o, si nadie lo cubre, al vecino con el que
  comparte más borde. Sirven para dibujar mapas, no para decidir en qué distrito cae una
  dirección.
"""
import glob
import json
import os

import shapely

from pyproj import Transformer
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.strtree import STRtree

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUENTES = os.path.join(RAIZ, 'fuentes', 'pueblos')
SALIDA = os.path.join(RAIZ, 'data', 'geo.json')
TOLERANCIA_M = 120
BORDE_MINIMO_M = 20


def cobertura(geoms):
    """Los distritos como una partición exacta: sin solapes ni huecos entre vecinos."""
    geoms = shapely.make_valid(shapely.set_precision(geoms, 0.5))
    caras = shapely.get_parts(shapely.polygonize(shapely.get_parts(shapely.union_all(shapely.boundary(geoms)))))
    arbol = STRtree(geoms)
    partes = [[] for _ in geoms]
    huerfanas = []
    for f in caras:
        pt = f.representative_point()
        cand = [i for i in arbol.query(pt) if geoms[i].covers(pt)]
        if not cand:
            huerfanas.append(f)
            continue
        partes[max(cand, key=lambda i: geoms[i].intersection(f).area)].append(f)
    for f in huerfanas:
        if f.area > 1_000_000:  # un hueco grande es de verdad (un lago fuera de todo distrito)
            continue
        borde = f.boundary
        cand = [i for i in arbol.query(f.buffer(1)) if partes[i]]
        if cand:
            partes[max(cand, key=lambda i: borde.intersection(shapely.union_all(partes[i]).boundary).length)].append(f)
    return [shapely.union_all(p) if p else g for p, g in zip(partes, geoms)]


def main():
    a_wgs84 = Transformer.from_crs('EPSG:8908', 'EPSG:4326', always_xy=True)
    distritos = {}
    version = None
    for ruta in sorted(glob.glob(os.path.join(FUENTES, 'ign_distritos_*.json'))):
        for f in json.load(open(ruta, encoding='utf-8'))['features']:
            codigo = str(f['properties']['CÓDIGO_DTA'])
            version = f['properties'].get('VERSIÓN', version)
            distritos[codigo] = shape(f['geometry']).buffer(0)
    dta = json.load(open(os.path.join(RAIZ, 'data', 'dta.json'), encoding='utf-8'))
    oficiales = {d['codigo'] for p in dta['provincias'] for c in p['cantones'] for d in c['distritos']}
    if set(distritos) != oficiales:
        raise SystemExit(f'los polígonos no coinciden con dta.json: faltan {sorted(oficiales - set(distritos))}, '
                         f'sobran {sorted(set(distritos) - oficiales)}')

    codigos = sorted(distritos)
    geoms = [distritos[c] for c in codigos]
    arbol = STRtree(geoms)
    simples = shapely.coverage_simplify(cobertura(geoms), TOLERANCIA_M)
    arbol_s = STRtree(simples)
    salida = {}
    for i, codigo in enumerate(codigos):
        g = geoms[i]
        vecinos = []
        for j in arbol.query(g.buffer(1)):
            if j == i:
                continue
            if g.buffer(1).intersection(geoms[j].boundary).length >= BORDE_MINIMO_M:
                vecinos.append(codigos[j])
        x, y = g.representative_point().coords[0]
        lon, lat = a_wgs84.transform(x, y)
        simple = simples[i]
        partes = list(simple.geoms) if isinstance(simple, MultiPolygon) else [simple]
        # se descartan islotes menores a 0,05 km² para que el contorno no pese de más
        # (solo islotes de verdad: un pedazo chico pegado a otro distrito se queda, si no
        # dejaría un hueco en el borde del vecino)
        def toca_otro(p):
            return any(j != i and simples[j].intersects(p.buffer(1)) for j in arbol_s.query(p.buffer(1)))
        partes = [p for p in partes if p.area >= 50_000 or toca_otro(p)] or [max(partes, key=lambda p: p.area)]
        contorno = []
        for p in partes:
            anillo = [[round(v, 4) for v in a_wgs84.transform(px, py)] for px, py in p.exterior.coords]
            contorno.append([anillo])
        salida[codigo] = {'centro': [round(lat, 5), round(lon, 5)], 'vecinos': sorted(vecinos),
                          'contorno': contorno}

    datos = {
        'fuente': {'nombre': 'Límite distrital 1:5 000 (DTA 2026)',
                   'institucion': 'Instituto Geográfico Nacional (IGN), Registro Nacional',
                   'url': 'https://geos.snitcr.go.cr/be/IGN_5_CO/wfs', 'capa': 'IGN_5_CO:limitedistrital_5k',
                   'version': str(version)},
        'metodo': (f'centro = punto interior representativo; vecinos = límite compartido de al menos '
                   f'{BORDE_MINIMO_M} m; contorno simplificado a {TOLERANCIA_M} m como cobertura (los vecinos '
                   f'comparten el mismo borde, sin huecos) en WGS84 [lon, lat].'),
        'distritos': salida,
    }
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(datos, f, ensure_ascii=False, separators=(',', ':'))
        f.write('\n')
    puntos = sum(len(a[0]) for d in salida.values() for a in d['contorno'])
    print(f'escrito {SALIDA}: {len(salida)} distritos, {puntos} vértices, {os.path.getsize(SALIDA)} bytes')


if __name__ == '__main__':
    main()
