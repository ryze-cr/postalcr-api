"""Valida los datos y la API publicada en public/.

Uso:
    python scripts/validar.py

Sale con código 1 si encuentra algún problema.
"""
import codecs
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generar_api  # noqa: E402

RAIZ = generar_api.RAIZ
PUBLIC = generar_api.PUBLIC
errores = []


def revisar(condicion, mensaje):
    if not condicion:
        errores.append(mensaje)


dta = generar_api.leer('dta.json')
oficiales = dta['fuente']['totales_oficiales']
cantones = [c for p in dta['provincias'] for c in p['cantones']]
distritos = [d for c in cantones for d in c['distritos']]
codigos = [d['codigo'] for d in distritos]

# 1. Los datos coinciden con los totales oficiales del IGN y los códigos son coherentes
revisar(len(dta['provincias']) == oficiales['provincias'], f"provincias: {len(dta['provincias'])} != {oficiales['provincias']}")
revisar(len(cantones) == oficiales['cantones'], f"cantones: {len(cantones)} != {oficiales['cantones']}")
revisar(len(distritos) == oficiales['distritos'], f"distritos: {len(distritos)} != {oficiales['distritos']}")
revisar(len(codigos) == len(set(codigos)), 'hay códigos de distrito repetidos')
for p in dta['provincias']:
    for c in p['cantones']:
        revisar(c['codigo'].startswith(p['codigo']) and len(c['codigo']) == 3, f"código de cantón inválido: {c['codigo']}")
        revisar(c['distritos'], f"el cantón {c['codigo']} no tiene distritos")
        for d in c['distritos']:
            revisar(d['codigo'].startswith(c['codigo']) and len(d['codigo']) == 5, f"código de distrito inválido: {d['codigo']}")
            revisar(d['nombre'] and d['nombre'].strip() == d['nombre'], f"nombre inválido en {d['codigo']}")

# 2. Cada distrito está clasificado dentro o fuera de la GAM, una sola vez
gam = generar_api.leer('gam.json')
dentro, fuera = set(gam['gam']), set(gam['no_gam'])
revisar(not dentro & fuera, f'distritos en gam y no_gam a la vez: {sorted(dentro & fuera)}')
revisar(dentro | fuera == set(codigos), f'distritos sin clasificar en data/gam.json: {sorted(set(codigos) - dentro - fuera)}; '
        f'sobran: {sorted((dentro | fuera) - set(codigos))}')

# 2b. Cada distrito tiene su contorno y sus vecinos existen
geo = generar_api.leer('geo.json')['distritos']
revisar(set(geo) == set(codigos), f'data/geo.json no coincide con los distritos: {sorted(set(geo) ^ set(codigos))}')
for codigo, g in geo.items():
    revisar(all(v in geo and codigo in geo[v]['vecinos'] for v in g['vecinos']), f'vecinos no recíprocos en {codigo}')
    lat, lon = g['centro']
    revisar(5.4 < lat < 11.3 and -87.2 < lon < -82.5, f'centro fuera de Costa Rica en {codigo}')

# 3. Cada pueblo apunta a un distrito que existe
pueblos = generar_api.leer('pueblos.json')
if pueblos:
    for pu in pueblos['pueblos']:
        revisar(pu['distrito'] in set(codigos), f"el pueblo {pu['nombre']} apunta a un distrito que no existe: {pu['distrito']}")
        revisar(pu['tipo'] in ('pueblo', 'playa'), f"tipo inválido en {pu['nombre']}: {pu['tipo']}")
        revisar(pu['categoria'] in generar_api.CON_PAGINA | {'Caserío'}, f"categoría inválida en {pu['nombre']}: {pu['categoria']}")
    claves = [(pu['nombre'], pu['distrito'], pu['tipo']) for pu in pueblos['pueblos']]
    revisar(len(claves) == len(set(claves)), 'hay pueblos repetidos (mismo nombre, distrito y tipo)')

recursos = generar_api.construir()
paginas = [pu['url'] for pu in recursos['pueblos.json'] if '/lugares/' in pu['url']]
revisar(len(paginas) == len(set(paginas)), 'hay lugares con la misma URL')

# 4. public/ es exactamente lo que generan los datos
for ruta, esperado in recursos.items():
    archivo = PUBLIC / ruta
    if not archivo.exists():
        errores.append(f'falta public/{ruta}')
        continue
    texto = archivo.read_text(encoding='utf-8')
    actual = texto if isinstance(esperado, str) else json.loads(texto)
    revisar(actual == esperado, f'public/{ruta} está desactualizado (correr scripts/generar_api.py)')
for carpeta in ('provincias', 'cantones', 'distritos'):
    sobran = {f'{carpeta}/{f.name}' for f in (PUBLIC / carpeta).glob('*.json')} - set(recursos)
    revisar(not sobran, f'sobran archivos: {sorted(sobran)}')

# 5. La documentación cubre todas las rutas y la versión es la misma en todos lados
readme = (RAIZ / 'README.md').read_text(encoding='utf-8')
for ruta, *_ in generar_api.RUTAS:
    revisar(ruta in readme, f'README.md no documenta la ruta {ruta}')
changelog = (RAIZ / 'CHANGELOG.md').read_text(encoding='utf-8')
revisar(f'## {generar_api.VERSION}' in changelog, f'CHANGELOG.md no tiene la versión {generar_api.VERSION}')
revisar(f"DTA {dta['fuente']['edicion']}" in readme, f"README.md no menciona la DTA {dta['fuente']['edicion']}")

# 6. Nada de terceros ni de herramientas en el repositorio
# Palabras que no pueden aparecer en el repositorio (en rot13, para que esta línea no las contenga)
prohibidas = tuple(codecs.decode(p, 'rot13') for p in ('pynhqr', 'naguebcvp', 'ysoilb', 'cntvanfjro', 'jbexref.qri', 'hovpnpvbarf-pe'))
rastreados = subprocess.run(['git', 'ls-files'], cwd=RAIZ, capture_output=True, text=True).stdout.split()
for nombre in rastreados or [str(p.relative_to(RAIZ)) for p in RAIZ.rglob('*') if p.is_file() and '.git' not in p.parts]:
    ruta = RAIZ / nombre
    contenido = nombre.lower()
    if ruta.suffix in ('.json', '.md', '.txt', '.py', '.yml', '.yaml', '.jsonc', '') and ruta.is_file():
        contenido += ruta.read_text(encoding='utf-8', errors='ignore').lower()
    for palabra in prohibidas:
        if palabra in contenido:
            errores.append(f'{nombre} menciona "{palabra}"')

if errores:
    print('\n'.join(f'✗ {e}' for e in errores))
    sys.exit(1)
m = recursos['meta.json']['totales']
print(f"✓ PostalCR API {generar_api.VERSION}: {m['provincias']} provincias, {m['cantones']} cantones, "
      f"{m['distritos']} distritos, {m['pueblos']} pueblos. Todo consistente.")
