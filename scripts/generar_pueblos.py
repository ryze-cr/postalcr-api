#!/usr/bin/env python3
"""
Genera data/pueblos.json: pueblos (localidades INEC) y playas (IGN) de Costa Rica
asignados a su distrito DTA (codigo PCCDD = codigo postal de 5 digitos).

Uso (requiere shapely y pyproj: pip install -r scripts/requirements.txt):
    python scripts/generar_pueblos.py --descargar   # baja las capas WFS a fuentes/pueblos/
    python scripts/generar_pueblos.py               # reconstruye data/pueblos.json

Metodo: cada punto oficial (INEC localidades de referencia / IGN accidentes
costeros tipo PLAYA) se cruza (punto-en-poligono) con los poligonos oficiales
de distrito del IGN (IGN_5_CO:limitedistrital_5k, DTA 2026). El distrito NO se
toma del atributo de la fuente: se calcula geometricamente y luego se compara.
"""
import argparse
import collections
import datetime
import glob
import json
import math
import os
import re
import subprocess
import unicodedata
import urllib.parse

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(RAIZ, "fuentes", "pueblos")  # descargas (no se versionan)
SALIDA = os.path.join(RAIZ, "data", "pueblos.json")
DTA_JSON = os.path.join(RAIZ, "data", "dta.json")

WFS_IGN_DIST = "https://geos.snitcr.go.cr/be/IGN_5_CO/wfs"
WFS_IGN_NG = "https://geos.snitcr.go.cr/be/IGN_NG/wfs"
WFS_INEC = "https://gestorgeo.inec.go.cr/geoserver/SNIT_INEC_MGN/wfs"

# Categorias INEC que se consideran "pueblo" (poblaciones con nombre propio).
# Se excluyen barrios, urbanizaciones, calles, condominios, residenciales,
# fincas, haciendas, asentamientos informales/precarios, etc.
CATEGORIAS_PUEBLO = {
    "Centro/Cabecera": ("Centro/Cabecera de Distrito ", "Cabecera de distrito"),
    "Centro": ("Centro de Distrito ", "Cabecera de distrito"),
    "Poblado": ("Poblado ", "Poblado"),
    "Caserío": ("Caserío ", "Caserío"),
    "Territorio/Comunidad": ("Territorio/Comunidad Indigena ", "Territorio/Comunidad indígena"),
}
PRIORIDAD_CAT = {"Cabecera de distrito": 0, "Poblado": 1, "Caserío": 2,
                 "Territorio/Comunidad indígena": 3}

UMBRAL_CLUSTER_M = 3000      # puntos INEC del mismo nombre a <3 km = misma localidad
UMBRAL_COSTA_M = 2000        # playa fuera de poligono: se asigna al distrito mas cercano si <2 km
UMBRAL_VECINO_M = 5000       # aviso de mismo nombre en distrito vecino

# Alias de busqueda para playas: no se da alias cuando el nombre corto es un
# adjetivo generico (no identifica un lugar por si solo).
GENERICOS = {"blanca", "negra", "hermosa", "grande", "bonita", "linda", "azul",
             "larga", "ancha", "chiquita", "rajada", "pequena", "brava", "honda",
             "mansa", "seca", "colorada", "real", "escondida", "linda vista",
             "del muerto", "el muerto", "muerto", "piedra", "arena", "barco",
             "palma", "cocal", "roble", "cedro", "cacao", "penca", "garza",
             "pelada", "playita", "playitas", "san miguel", "san juan",
             "pochote", "naranjo", "guacalillo", "coyote", "manzanillo",
             "matapalo", "carmen", "bajamar", "bellavista", "buena vista",
             "chal", "chino", "bote", "camaron", "calera"}

# Alias editoriales de busqueda (NO cambian nombre ni distrito; solo ayudan a
# encontrar la entrada oficial). Clave: (nombre normalizado, distrito).
ALIAS_EDITORIAL = {
    ("malpais", "60111"): ["Malpaís", "Mal País"],
    ("puerto viejo", "70403"): ["Puerto Viejo de Talamanca"],
    ("puerto viejo", "41001"): ["Puerto Viejo de Sarapiquí"],
    ("santa elena", "61201"): ["Santa Elena de Monteverde"],
    ("agujitas (drake)", "60506"): ["Agujitas", "Drake"],
    ("playas del coco", "50503"): ["El Coco"],
}

# Playas muy buscadas: si no estan en la capa IGN se listan en "sin_fuente".
PLAYAS_BUSCADAS = [
    ("Playa Flamingo", r"^playa flamingo$", "503"), ("Playa Cocles", r"^playa cocles$", "704"),
    ("Playa Ocotal", r"^playa ocotal$", "505"), ("Playa Uvita", r"^playa uvita$", "605"),
    ("Playa Tortuguero", r"^playa tortuguero$", "702"), ("Playa Pavones (Golfito)", r"^playa pavones$", "607"),
    ("Playa Puerto Viejo", r"^playa puerto viejo$", "704"), ("Playa Punta Uva", r"^playa punta uva$", "704"),
    ("Playa Chiquita (Talamanca)", r"^playa chiquita$", "704"), ("Playa Manzanillo (Talamanca)", r"^playa manzanillo$", "704"),
    ("Playa Zancudo", r"^playa zancudo$", "607"), ("Playa Biesanz", r"^playa biesanz$", "606"),
    ("Playa Brasilito", r"^playa brasilito$", "503"), ("Playa Conchal", r"^playa conchal$", "503"),
    ("Playa Avellanas", r"^playa avellanas$", "503"), ("Playa Pelada", r"^playa pelada$", "502"),
    ("Playa Carrillo", r"^playa carrillo$", "511"), ("Playa Esterillos", r"^playa esterillos", "609"),
    ("Playa Bejuco (Parrita)", r"^playa bejuco$", "609"), ("Playa Herradura", r"^playa herradura$", "611"),
    ("Playa Hermosa (Garabito)", r"^playa hermosa$", "611"), ("Playa Hermosa (Guanacaste)", r"^playa hermosa$", "505"),
    ("Playa Panamá", r"^playa panama$", "505"), ("Playa Matapalo (Quepos)", r"^playa matapalo$", "606"),
    ("Playa Ventanas (Osa)", r"^playa ventanas$", "605"), ("Playa Montezuma", r"^playa montezuma$", "601"),
    ("Playa Santa Teresa", r"^playa santa teresa$", "601"), ("Playa Malpaís", r"^playa malpais$", "601"),
    ("Playa Tambor", r"^playa tambor$", "601"), ("Playa Grande (Santa Cruz)", r"^playa grande$", "503"),
    ("Playa Negra (Santa Cruz)", r"^playa negra$", "503"), ("Playa Junquillal", r"^playa junquillal$", "503"),
    ("Playa Guiones", r"^playa guiones$", "502"), ("Playa Ostional", r"^playa ostional$", "503"),
    ("Playa Dominical", r"^playa dominical$", "605"), ("Playa Cahuita", r"^playa (negra|blanca|cahuita)$", "704"),
    ("Playa Bonita (Limón)", r"^playa bonita$", "701"), ("Playa Doña Ana", r"^playa dona ana$", "602"),
    ("Playa Potrero", r"^playa potrero$", "503"), ("Playa Langosta", r"^playa langosta$", "503"),
]

# Destinos turisticos a verificar (nombre buscado -> regex sobre el nombre oficial
# + canton donde se espera; el canton solo sirve para escoger entre homonimos y
# se comprueba contra el resultado geometrico, no se impone).
DESTINOS = [
    ("Tamarindo", r"^tamarindo$", "503"), ("Jacó", r"^jaco$", "611"),
    ("Santa Teresa", r"^santa teresa$", "601"), ("Nosara", r"^nosara$", "502"),
    ("La Fortuna", r"^la fortuna$", "210"), ("Puerto Viejo de Talamanca", r"^puerto viejo$", "704"),
    ("Manuel Antonio", r"^manuel antonio$", "606"), ("Montezuma", r"^montezuma$", "601"),
    ("Dominical", r"^dominical$", "605"), ("Uvita", r"^uvita$", "605"),
    ("Playas del Coco", r"^playas del coco$", "505"), ("Monteverde", r"^monte ?verde$", "612"),
    ("Santa Elena (Monteverde)", r"^santa elena$", "612"), ("Sámara", r"^samara$", "502"),
    ("Flamingo", r"^(playa )?flamingo$", "503"), ("Malpaís", r"^mal ?pais$", "601"),
    ("Cahuita", r"^cahuita$", "704"), ("Tortuguero", r"^tortuguero$", "702"),
    ("Pavones", r"^pavones$", "607"), ("Ojochal", r"^ojochal$", "605"),
    ("Potrero", r"^potrero$", "503"), ("Brasilito", r"^brasilito$", "503"),
    ("Playa Hermosa (Guanacaste)", r"^playa hermosa$", "505"),
    ("Playa Hermosa (Garabito)", r"^playa hermosa$", "611"),
    ("Esterillos", r"^esterillos", "609"), ("Herradura", r"^herradura$", "611"),
    ("Quepos", r"^quepos$", "606"), ("Puerto Jiménez", r"^puerto jimenez$", "613"),
    ("Drake", r"drake", "605"), ("Sierpe", r"^sierpe$", "605"),
    ("Cabuya", r"^cabuya$", "601"), ("Tambor", r"^tambor$", "601"),
    ("Paquera", r"^paquera$", "601"), ("Playa Grande", r"^playa grande$", "503"),
    ("Avellanas", r"^(playa )?avellanas$", "503"), ("Playa Negra (Santa Cruz)", r"^(playa )?negra$", "503"),
    ("Ostional", r"^ostional$", "503"), ("Guiones", r"^guiones$", "502"),
    ("Playa Panamá", r"^playa panama$", "505"), ("Ocotal", r"^ocotal$", "505"),
    ("Manzanillo (Talamanca)", r"^manzanillo$", "704"), ("Cocles", r"^cocles$", "704"),
    ("Zancudo", r"^zancudo$", "607"), ("Golfito", r"^golfito$", "607"),
    ("Puerto Viejo de Sarapiquí", r"^puerto viejo$", "410"), ("Liberia", r"^liberia$", "501"),
    ("Nicoya", r"^nicoya$", "502"), ("Santa Cruz", r"^santa cruz$", "503"),
    ("Puntarenas", r"^puntarenas$", "601"), ("Limón", r"^limon$", "701"),
    ("Turrialba", r"^turrialba$", "305"), ("Cóbano", r"^cobano$", "601"),
    ("Junquillal", r"^(playa )?junquillal$", "503"), ("Conchal", r"^(playa |reserva )?conchal$", "503"),
    ("Playa Carrillo", r"^playa carrillo$", "502"),
    ("Ballena", r"^ballena$", "605"), ("Parrita", r"^parrita$", "609"),
    ("Tárcoles", r"^tarcoles$", "611"), ("Bijagua", r"^bijagua$", "213"),
    ("Río Celeste", r"^rio celeste$", "215"),
]


# ----------------------------------------------------------------------------
# Descarga
# ----------------------------------------------------------------------------
def _get(url, destino):
    # curl usa el almacen de certificados del sistema (el Python de python.org en
    # macOS no trae certificados raiz por defecto).
    subprocess.run(["curl", "-sS", "--fail", "-m", "600", "-A", "postalcr-api/2.0",
                    "-o", destino, url], check=True)
    print("  ", os.path.basename(destino), os.path.getsize(destino), "bytes")


def _wfs(base, typename, count, start, sort):
    q = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
         "typeNames": typename, "outputFormat": "application/json",
         "count": str(count), "startIndex": str(start)}
    if sort:
        q["sortBy"] = sort
    return base + "?" + urllib.parse.urlencode(q)


def descargar():
    os.makedirs(DATA, exist_ok=True)
    print("IGN limitedistrital_5k (494 distritos)")
    for i in range(0, 500, 100):
        _get(_wfs(WFS_IGN_DIST, "IGN_5_CO:limitedistrital_5k", 100, i, "OBJECTID"),
             os.path.join(DATA, f"ign_distritos_{i}.json"))
    print("IGN accidentescosteros_25k")
    _get(_wfs(WFS_IGN_NG, "IGN_NG:accidentescosteros_25k", 5000, 0, None),
         os.path.join(DATA, "accidentescosteros_25k.json"))
    print("INEC localidades_de_referencia_snit")
    for i in range(0, 70000, 10000):
        _get(_wfs(WFS_INEC, "SNIT_INEC_MGN:localidades_de_referencia_snit", 10000, i, "id"),
             os.path.join(DATA, f"inec_localidades_{i}.json"))


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
def norm(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip().casefold()


def limpiar(s):
    return re.sub(r"\s+", " ", s or "").strip()


def mayus_inicial(s):
    return s[:1].upper() + s[1:] if s else s


def medoide(pts):
    """indice del punto con menor suma de distancias (un punto real de la fuente)."""
    if len(pts) <= 2:
        return 0
    best, bi = None, 0
    for i, (x, y) in enumerate(pts):
        s = sum(math.hypot(x - a, y - b) for a, b in pts)
        if best is None or s < best:
            best, bi = s, i
    return bi


def clusters(pts, umbral):
    """single-linkage: lista de listas de indices."""
    n = len(pts)
    padre = list(range(n))

    def raiz(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i
    for i in range(n):
        xi, yi = pts[i]
        for j in range(i + 1, n):
            if abs(pts[j][0] - xi) < umbral and abs(pts[j][1] - yi) < umbral and \
               math.hypot(pts[j][0] - xi, pts[j][1] - yi) < umbral:
                a, b = raiz(i), raiz(j)
                if a != b:
                    padre[a] = b
    g = collections.defaultdict(list)
    for i in range(n):
        g[raiz(i)].append(i)
    return list(g.values())


# ----------------------------------------------------------------------------
# Construccion
# ----------------------------------------------------------------------------
def construir():
    from shapely.geometry import shape, Point
    from shapely.strtree import STRtree
    from shapely.prepared import prep
    from pyproj import Transformer

    hoy = datetime.date.today().isoformat()

    # --- DTA (lista oficial de distritos) ---
    dta = json.load(open(DTA_JSON, encoding="utf-8"))
    DIST = {}
    for p in dta["provincias"]:
        for c in p["cantones"]:
            for d in c["distritos"]:
                DIST[d["codigo"]] = {"nombre": d["nombre"], "canton": c["codigo"],
                                     "canton_nombre": c["nombre"], "provincia": p["nombre"]}

    # --- poligonos IGN ---
    feats = []
    for f in sorted(glob.glob(os.path.join(DATA, "ign_distritos_*.json"))):
        feats += json.load(open(f, encoding="utf-8"))["features"]
    geoms, codigos = [], []
    vistos = set()
    for f in feats:
        cod = str(f["properties"]["CÓDIGO_DTA"]).zfill(5)
        if cod in vistos:
            continue
        vistos.add(cod)
        g = shape(f["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        geoms.append(g)
        codigos.append(cod)
    assert set(codigos) == set(DIST), "codigos IGN != dta.json"
    prepared = [prep(g) for g in geoms]
    tree = STRtree(geoms)

    def distrito_de(x, y):
        """(codigo, distancia_m). distancia 0 si cae dentro."""
        pt = Point(x, y)
        cands = [i for i in tree.query(pt) if prepared[i].contains(pt)]
        if len(cands) == 1:
            return codigos[cands[0]], 0.0
        if len(cands) > 1:  # exactamente sobre un borde compartido: el de menor codigo
            cands.sort(key=lambda i: codigos[i])
            return codigos[cands[0]], 0.0
        i = tree.nearest(pt)
        return codigos[i], geoms[i].distance(pt)

    def alternativa(x, y, cod, dm):
        """para puntos fuera de poligono: otro distrito casi tan cercano (<200 m extra)."""
        pt = Point(x, y)
        alt = []
        for i in tree.query(pt.buffer(dm + 200)):
            if codigos[i] != cod:
                d2 = geoms[i].distance(pt)
                if d2 < dm + 200:
                    alt.append((d2, codigos[i]))
        return sorted(alt)

    t5367 = Transformer.from_crs(5367, 4326, always_xy=True)
    t8908 = Transformer.from_crs(8908, 4326, always_xy=True)

    def latlon(tr, x, y):
        lon, lat = tr.transform(x, y)
        return [round(lat, 5), round(lon, 5)]

    pueblos, sin_fuente = [], []
    stats = collections.Counter()

    # ======================= PLAYAS (IGN) =======================
    costa = json.load(open(os.path.join(DATA, "accidentescosteros_25k.json"), encoding="utf-8"))["features"]
    playas = [f for f in costa if f["properties"]["nom_objeto"] == "PLAYA"]
    stats["playas_puntos_fuente"] = len(playas)
    grupos = collections.defaultdict(list)  # (norm nombre, distrito) -> [(x,y,nombre,dist_m,origen)]
    for f in playas:
        nombre = limpiar(f["properties"]["nom_ofi"])
        x, y = f["geometry"]["coordinates"][:2]
        cod, dm = distrito_de(x, y)
        if dm > UMBRAL_COSTA_M:
            sin_fuente.append({"nombre": nombre, "tipo": "playa",
                               "motivo": f"punto IGN a {dm:.0f} m del poligono distrital mas cercano ({cod}); no se asigna"})
            stats["playas_descartadas_lejos"] += 1
            continue
        alt = alternativa(x, y, cod, dm) if dm > 0 else []
        corto0 = re.sub(r"^playas?\s+", "", nombre, flags=re.I)
        if corto0 and corto0[0].islower() and corto0.split()[0] not in ("de", "del", "el", "la", "las", "los"):
            sin_fuente.append({"nombre": nombre, "tipo": "playa",
                               "motivo": f"nombre aparentemente truncado en la fuente IGN (punto en distrito {cod}); se omite hasta confirmarlo"})
            stats["playas_descartadas_nombre"] += 1
            continue
        grupos[(norm(nombre), cod)].append((x, y, nombre, dm, alt))
    # indice para avisar homonimos en distritos vecinos
    por_nombre = collections.defaultdict(list)
    for (n, cod), pts in grupos.items():
        for p in pts:
            por_nombre[n].append((p[0], p[1], cod))
    for (n, cod), pts in grupos.items():
        xy = [(p[0], p[1]) for p in pts]
        i = medoide(xy)
        x, y, nombre, dm, alt = pts[i]
        notas = []
        if len(pts) > 1:
            notas.append(f"{len(pts)} puntos/segmentos en la fuente; se usa el punto representativo (medoide)")
        if any(p[3] > 0 for p in pts):
            dmax = max(p[3] for p in pts)
            notas.append(f"punto IGN fuera de la linea de costa del poligono distrital (hasta {max(dmax, 1):.0f} m); asignado al distrito mas cercano")
        if alt:
            notas.append("AMBIGUO: el punto cae en el mar casi equidistante de " +
                         ", ".join(f"{c} ({d:.0f} m)" for d, c in alt) + f" frente a {cod} ({max(dm, 1):.0f} m)")
            stats["playas_ambiguas"] += 1
        vecinos = sorted({c for (a, b, c) in por_nombre[n] if c != cod and
                          min(math.hypot(a - q[0], b - q[1]) for q in xy) < UMBRAL_VECINO_M})
        if vecinos:
            notas.append("mismo nombre en distrito(s) contiguo(s) " + ", ".join(vecinos) +
                         ": puede ser la misma playa que cruza el limite distrital")
        base = re.sub(r"\b(de|del|el|la|las|los)\b", " ", n)
        gemelas = [m for (m, c2) in grupos if c2 == cod and m != n and
                   re.sub(r"\s+", " ", re.sub(r"\b(de|del|el|la|las|los)\b", " ", m)).strip() ==
                   re.sub(r"\s+", " ", base).strip()]
        if gemelas:
            notas.append("posible duplicado en la misma fuente: " + ", ".join(
                grupos[(m, cod)][0][2] for m in gemelas) + " (mismo distrito)")
        e = {"nombre": nombre, "tipo": "playa", "categoria": "Playa",
             "distrito": cod, "coordenadas": latlon(t5367, x, y),
             "fuente": "ign_accidentescosteros_25k"}
        corto = re.sub(r"^playa\s+", "", nombre, flags=re.I)
        if corto != nombre and norm(corto) not in GENERICOS and "(" not in corto:
            e["_corto"] = corto
        if notas:
            e["nota"] = "; ".join(notas)
        pueblos.append(e)

    # ======================= PUEBLOS (INEC) =======================
    loc = []
    for f in sorted(glob.glob(os.path.join(DATA, "inec_localidades_*.json"))):
        loc += json.load(open(f, encoding="utf-8"))["features"]
    ids = set()
    pts_por_nombre = collections.defaultdict(list)
    # "Centro de Distrito X" son etiquetas repetidas del centro del distrito; solo se
    # usan si no existe el punto unico "Centro/Cabecera de Distrito X" con ese nombre.
    con_cabecera = {norm(f["properties"]["nomb_loc"].replace("Centro/Cabecera de Distrito ", ""))
                    for f in loc if f["properties"]["descr_cat"] == "Centro/Cabecera"}
    for f in loc:
        if f["id"] in ids:
            continue
        ids.add(f["id"])
        p = f["properties"]
        cat = p["descr_cat"]
        if cat not in CATEGORIAS_PUEBLO:
            continue
        pref, cat_out = CATEGORIAS_PUEBLO[cat]
        raw = limpiar(p["nomb_loc"])
        if cat == "Centro" and norm(raw[len(pref):]) in con_cabecera:
            continue
        if not raw.startswith(pref.strip()):
            stats["inec_prefijo_inesperado"] += 1
            continue
        nombre = mayus_inicial(limpiar(raw[len(pref):]))
        if not nombre:
            continue
        x, y = f["geometry"]["coordinates"][:2]
        cod, dm = distrito_de(x, y)
        pts_por_nombre[norm(nombre)].append({
            "x": x, "y": y, "nombre": nombre, "raw": raw, "cat": cat_out,
            "cabecera": cat == "Centro/Cabecera", "cod": cod, "dm": dm,
            "inec": str(p.get("cod_uged") or "").zfill(5)})
        stats["inec_puntos_usados"] += 1

    entradas = {}  # (norm nombre, distrito) -> entrada
    for n, pts in pts_por_nombre.items():
        grupos_cl = []
        for cl in clusters([(q["x"], q["y"]) for q in pts], UMBRAL_CLUSTER_M):
            cp = [pts[i] for i in cl]
            cabs = [q for q in cp if q["cabecera"]]
            if len(cabs) <= 1:
                grupos_cl.append(cp)
                continue
            # varias cabeceras homonimas cercanas (p.ej. Cartago 30101/30102): cada
            # cabecera es su propia localidad; los demas puntos van a la mas cercana
            sub = {id(c): [c] for c in cabs}
            for q in cp:
                if not q["cabecera"]:
                    c = min(cabs, key=lambda c: math.hypot(c["x"] - q["x"], c["y"] - q["y"]))
                    sub[id(c)].append(q)
            grupos_cl.extend(sub.values())
        for cp in grupos_cl:
            cab = [q for q in cp if q["cabecera"]]
            rep = cab[0] if cab else cp[medoide([(q["x"], q["y"]) for q in cp])]
            cod = rep["cod"]
            cats = sorted({q["cat"] for q in cp}, key=lambda c: PRIORIDAD_CAT[c])
            dist_cnt = collections.Counter(q["cod"] for q in cp)
            inec_cnt = collections.Counter(q["inec"] for q in cp)
            notas = []
            if rep["dm"] > 0:
                notas.append(f"punto INEC fuera de los poligonos IGN ({rep['dm']:.0f} m); distrito mas cercano")
            otros = {c: k for c, k in dist_cnt.items() if c != cod}
            if otros:
                notas.append("la localidad tiene puntos INEC tambien en " +
                             ", ".join(f"{c} ({k})" for c, k in sorted(otros.items())) +
                             f"; se usa el distrito del punto representativo ({dist_cnt[cod]} de {len(cp)} puntos)")
            if rep["inec"] != cod:
                notas.append(f"INEC codifica el punto representativo en {rep['inec']}; el poligono IGN 2026 lo ubica en {cod}")
                stats["inec_codigo_distinto"] += 1
            nombre = rep["nombre"]
            if norm(nombre) == norm(DIST[cod]["nombre"]):
                nombre = DIST[cod]["nombre"]        # grafia oficial DTA (tildes)
            clave = (n, cod)
            e = {"nombre": nombre, "tipo": "pueblo", "categoria": cats[0],
                 "distrito": cod, "coordenadas": latlon(t8908, rep["x"], rep["y"]),
                 "fuente": "inec_localidades_referencia", "nombre_fuente": rep["raw"],
                 "_n": len(cp), "_notas": notas}
            alias = []
            dn = DIST[cod]["nombre"]
            if nombre != dn and norm(nombre).replace(" ", "") == norm(dn).replace(" ", ""):
                alias.append(dn)                    # grafia DTA del distrito homonimo
            alias += [x for x in ALIAS_EDITORIAL.get((norm(nombre), cod), []) if x not in alias]
            if alias:
                e["alias"] = alias
            if (norm(nombre), cod) in ALIAS_EDITORIAL:
                e["_notas"].append("alias editorial de busqueda (no oficial)")
            if norm(nombre) == "puerto viejo":
                e["_notas"].append("homonimo: Puerto Viejo de Sarapiqui (41001) y Puerto Viejo de Talamanca (70403)")
            if cats[0] == "Cabecera de distrito":
                e["_notas"].insert(0, "cabecera (centro) de distrito segun INEC")
            if clave in entradas:
                prev = entradas[clave]
                # dos nucleos con el mismo nombre en el mismo distrito: una sola entrada
                if e["_n"] > prev["_n"] or PRIORIDAD_CAT[e["categoria"]] < PRIORIDAD_CAT[prev["categoria"]]:
                    e["_notas"].append(f"hay otro nucleo homonimo en el mismo distrito ({prev['_n']} puntos)")
                    entradas[clave] = e
                else:
                    prev["_notas"].append(f"hay otro nucleo homonimo en el mismo distrito ({e['_n']} puntos)")
            else:
                entradas[clave] = e

    # alias de playas: solo si el nombre corto coincide con el distrito DTA o con un
    # pueblo INEC del MISMO distrito (evidencia de que es el lugar que se busca).
    pueblos_dist = {(n, c) for (n, c) in entradas}
    for e in pueblos:
        corto = e.pop("_corto", None)
        if not corto:
            continue
        cod = e["distrito"]
        if norm(corto) == norm(DIST[cod]["nombre"]):
            e["alias"] = [DIST[cod]["nombre"]]     # grafia oficial DTA (con tildes)
        elif (norm(corto), cod) in pueblos_dist:
            e["alias"] = [entradas[(norm(corto), cod)]["nombre"]]

    for e in entradas.values():
        notas = e.pop("_notas")
        e.pop("_n")
        if notas:
            e["nota"] = "; ".join(dict.fromkeys(notas))
        pueblos.append(e)

    # Homonimos de playa/pueblo en el mismo distrito se mantienen (tipo distinto).
    pueblos.sort(key=lambda e: (norm(e["nombre"]), e["tipo"], e["distrito"]))

    # ======================= verificacion de destinos =======================
    verif = []
    for buscado, rx, canton in DESTINOS:
        m = [e for e in pueblos if re.search(rx, norm(e["nombre"]))
             and DIST[e["distrito"]]["canton"] == canton]
        mp = [e for e in m if e["tipo"] == "pueblo"] or m
        if mp:
            verif.append({"buscado": buscado,
                          "encontrado": [{"nombre": e["nombre"], "tipo": e["tipo"],
                                          "distrito": e["distrito"],
                                          "distrito_nombre": DIST[e["distrito"]]["nombre"],
                                          "canton": DIST[e["distrito"]]["canton_nombre"]} for e in m]})
        else:
            verif.append({"buscado": buscado, "encontrado": []})

    # Playas muy buscadas que NO figuran en IGN accidentescosteros_25k
    for buscada, rx, canton in PLAYAS_BUSCADAS:
        if any(e["tipo"] == "playa" and re.search(rx, norm(e["nombre"])) and
               DIST[e["distrito"]]["canton"] == canton for e in pueblos):
            continue
        rx_corto = r"^(playa )?" + rx.replace("^playa ", "").lstrip("^")
        pu = [e for e in pueblos if e["tipo"] == "pueblo" and re.search(rx_corto, norm(e["nombre"]))
              and DIST[e["distrito"]]["canton"] == canton]
        motivo = "no figura como PLAYA en IGN_NG:accidentescosteros_25k"
        if pu:
            motivo += "; existe el pueblo INEC " + ", ".join(
                f"'{e['nombre']}' ({e['distrito']})" for e in pu) + " — usar esa entrada"
        sin_fuente.append({"nombre": buscada, "tipo": "playa", "motivo": motivo})

    stats["pueblos"] = sum(e["tipo"] == "pueblo" for e in pueblos)
    stats["playas"] = sum(e["tipo"] == "playa" for e in pueblos)

    fuentes = [
        {"id": "ign_limitedistrital_5k", "nombre": "DTA (Límite Distrital) 1:5 000",
         "institucion": "Instituto Geográfico Nacional (IGN), Registro Nacional",
         "url": WFS_IGN_DIST, "capa": "IGN_5_CO:limitedistrital_5k",
         "detalle": "494 polígonos, atributo CÓDIGO_DTA (PCCDD), VERSIÓN 20260410001, EPSG:5367 (CRTM05)",
         "consultado": hoy},
        {"id": "ign_dta_2026", "nombre": "División Territorial Administrativa 2026",
         "institucion": "Instituto Geográfico Nacional (IGN), Registro Nacional",
         "url": dta["fuente"]["url"], "capa": "tabla provincia-cantón-distrito (data/dta.json)",
         "detalle": "nombres oficiales de distrito usados para validar códigos y restituir tildes",
         "consultado": dta["fuente"].get("extraido")},
        {"id": "ign_accidentescosteros_25k", "nombre": "Accidentes Costeros 1:25 000 (nombres geográficos)",
         "institucion": "Instituto Geográfico Nacional (IGN), Registro Nacional",
         "url": WFS_IGN_NG, "capa": "IGN_NG:accidentescosteros_25k",
         "detalle": "nom_objeto = 'PLAYA' (316 puntos), nom_ofi = nombre oficial; EPSG:5367",
         "consultado": hoy},
        {"id": "inec_localidades_referencia", "nombre": "Localidades de referencia (Marco Geoestadístico Nacional)",
         "institucion": "Instituto Nacional de Estadística y Censos (INEC), nodo SNIT",
         "url": WFS_INEC, "capa": "SNIT_INEC_MGN:localidades_de_referencia_snit",
         "detalle": "66 979 puntos; se usan descr_cat Centro/Cabecera, Centro, Poblado, Caserío y "
                    "Territorio/Comunidad; nomb_loc = nombre; EPSG:8908 (CR-SIRGAS / CRTM05)",
         "consultado": hoy},
    ]
    metodo = (
        "Punto-en-polígono: cada punto oficial (IGN accidentes costeros tipo PLAYA; INEC localidades de "
        "referencia de categoría Centro/Cabecera, Centro, Poblado, Caserío o Territorio/Comunidad indígena) "
        "se proyecta en CRTM05 y se cruza con los 494 polígonos distritales IGN DTA 2026 "
        "(IGN_5_CO:limitedistrital_5k, CÓDIGO_DTA = código postal PCCDD). El distrito se calcula "
        "geométricamente, no se copia del atributo de la fuente; cuando el código INEC (cod_uged) difiere "
        f"se indica en 'nota'. Playas cuyo punto cae en el mar se asignan al distrito más cercano si está a "
        f"menos de {UMBRAL_COSTA_M} m. Puntos INEC del mismo nombre a menos de {UMBRAL_CLUSTER_M} m forman una "
        "localidad; su punto representativo es la cabecera INEC si existe o, si no, el medoide (un punto "
        "real de la fuente). Deduplicación: un registro por nombre + distrito y tipo. Nombres tal como "
        "los escribe la fuente, sin el prefijo de categoría INEC ('Poblado ', 'Caserío ', 'Centro/Cabecera "
        "de Distrito ', 'Territorio/Comunidad Indigena '), con espacios normalizados y mayúscula inicial; "
        "si el nombre coincide (sin tildes) con el nombre DTA del distrito se usa la grafía DTA. "
        "'nombre_fuente' conserva el texto INEC original. Coordenadas WGS84 (lat, lon) redondeadas a 5 "
        "decimales (pyproj, EPSG:5367/8908 -> 4326). 'alias' de playas = nombre sin 'Playa ' solo cuando "
        "coincide con el nombre DTA del distrito o con un pueblo INEC del mismo distrito; 'alias' de pueblos = "
        "grafía DTA cuando solo difiere en espacios, más unos pocos alias editoriales de búsqueda marcados en 'nota'."
    )
    out = {"fuente": fuentes, "metodo": metodo, "generado": hoy,
           "totales": {"pueblos": stats["pueblos"], "playas": stats["playas"],
                       "sin_fuente": len(sin_fuente)},
           "pueblos": pueblos, "sin_fuente": sin_fuente}
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    with open(os.path.join(DATA, "verificacion_destinos.json"), "w", encoding="utf-8") as f:
        json.dump(verif, f, ensure_ascii=False, indent=1)
    print(json.dumps(dict(stats), ensure_ascii=False, indent=1))
    print("escrito", SALIDA, os.path.getsize(SALIDA), "bytes")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--descargar", action="store_true")
    a = ap.parse_args()
    if a.descargar:
        descargar()
    construir()
