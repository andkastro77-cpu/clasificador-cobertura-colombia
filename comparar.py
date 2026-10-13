"""Visor interactivo: imagen satelital real vs clasificación de IA.

Genera un archivo HTML autocontenido que se abre con doble clic y ofrece:

  • Un comparador "swipe" arrastrable (como la herramienta equivalente de
    ERDAS Imagine): la imagen satelital queda de fondo siempre visible y
    un divisor controla cuánto de la clasificación se superpone. Al
    arrastrar, la capa de coberturas aparece o desaparece sobre la
    fotografía real, lo que facilita comprobar si la IA acertó.
  • Un panel de capas para encender/apagar cada elemento.
  • Zoom, desplazamiento y lectura de coordenadas.

Todo va incrustado en un único archivo .html: librerías de mapas,
imágenes en base64 y estilos. Funciona sin internet (excepto el mapa
base de calles, que sí necesita conexión).

Uso:
    import comparar
    comparar.crear_comparacion(geo, imagen_clasificada, municipios, pct, dir)
"""

import base64
import io
import json
import urllib.request
import webbrowser
from math import cos, radians
from pathlib import Path

from PIL import Image

import ee
import config

# Carpeta con las librerías de mapas descargadas (ver README).
CARPETA_VISOR = config.CARPETA_PROYECTO / "visor"

# Ancho máximo en píxeles de las capas. A mayor valor, mejor detalle pero
# archivo HTML más pesado. 1400 px da un buen equilibrio.
ANCHO_MAXIMO = 1400

# Calidad del JPEG de la imagen satelital (1-100). Más bajo = más liviano.
CALIDAD_JPEG = 82


# ---------------------------------------------------------------------------
# 1. IMAGEN SATELITAL
# ---------------------------------------------------------------------------
def imagen_satelital(geometria: ee.Geometry) -> ee.Image:
    """Composición mediana de Sentinel-2 en color natural (rojo/verde/azul).

    Se usa la mediana de todas las escenas del período: es el truco
    clásico para eliminar nubes, porque la mediana ignora los píxeles
    ocasionales tapados por nubes.
    """
    coleccion = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(geometria)
        .filterDate(config.FECHA_INICIO, config.FECHA_FIN)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", config.MAX_NUBES))
    )

    # B4=rojo, B3=verde, B2=azul. min/max ajustan el contraste visual.
    # Se recorta al rectángulo y no al polígono municipal: el JPEG no
    # admite transparencia, así que recortar al polígono dejaría bloques
    # negros en las esquinas. La clasificación sí conserva su transparencia.
    return (
        coleccion.median()
        .clip(geometria.bounds())
        .visualize(bands=["B4", "B3", "B2"], min=0, max=3000)
    )


def clasificacion_visual(imagen: ee.Image) -> ee.Image:
    """Asigna a cada clase su color de `config.CLASES`.

    La imagen clasificada solo contiene números (0 = agua, 1 = bosque, ...).
    Sin este paso se vería en escala de grises. `visualize()` traduce cada
    valor a su color hexadecimal y deja transparentes los píxeles fuera del
    municipio (zonas sin dato), que es justo lo que queremos en el visor.
    """
    colores = [config.CLASES[clave]["color"] for clave in sorted(config.CLASES)]
    return imagen.visualize(min=0, max=len(colores) - 1, palette=colores)


# ---------------------------------------------------------------------------
# 2. DESCARGA DE CAPAS
# ---------------------------------------------------------------------------
def _descargar_bytes(url: str) -> bytes:
    """Descarga una URL y devuelve sus bytes."""
    with urllib.request.urlopen(url, timeout=300) as respuesta:
        return respuesta.read()


def descargar_capas(
    imagen_sat: ee.Image,
    imagen_clas: ee.Image,
    geometria: ee.Geometry,
) -> tuple[bytes, bytes, list]:
    """Descarga ambas capas con exactamente el mismo tamaño de píxel.

    Clave del swipe: si las dos imágenes no tienen las mismas dimensiones,
    el divisor no alinea los píxeles y la comparación pierde sentido.
    Por eso ambas se piden con la misma región, la misma proyección
    (EPSG:4326, la que entiende Leaflet) y la misma escala en metros.

    La escala se calcula para que el ancho ronde ~ANCHO_MAXIMO píxeles:
    así el HTML queda liviano pero conserva detalle suficiente para
    moverse con zoom.
    """
    region = geometria.bounds().getInfo()["coordinates"][0]
    lons = [punto[0] for punto in region]
    lats = [punto[1] for punto in region]

    # Grados a metros (aproximación local, válida para zonas ecuatoriales).
    ancho_m = (max(lons) - min(lons)) * 111_320.0
    ancho_m *= cos(radians(sum(lats) / len(lats)))
    escala_m = max(ancho_m / ANCHO_MAXIMO, 1.0)

    parametros = {
        "scale": escala_m,
        "crs": "EPSG:4326",
        "region": region,
        "format": "PNG",
    }

    print(f"[...] Descargando imagen satelital (escala ≈ {escala_m:.1f} m/px)...")
    bytes_sat = _descargar_bytes(imagen_sat.getDownloadURL(parametros))

    print("[...] Descargando clasificación con transparencia...")
    bytes_clas = _descargar_bytes(imagen_clas.getDownloadURL(parametros))

    # La satelital se guarda como JPEG: al ser una fotografía, el JPEG la
    # comprime mucho mejor que el PNG y el HTML final pesa la mitad.
    with Image.open(io.BytesIO(bytes_sat)) as imagen:
        ancho, alto = imagen.size
        buffer = io.BytesIO()
        imagen.convert("RGB").save(buffer, "JPEG", quality=CALIDAD_JPEG)
        bytes_sat = buffer.getvalue()

    print(f"[OK] Capas descargadas: {ancho} x {alto} px")

    # Límites geográficos [[sur, oeste], [norte, este]] para Leaflet.
    lons = [punto[0] for punto in region]
    lats = [punto[1] for punto in region]
    limites = [[min(lats), min(lons)], [max(lats), max(lons)]]

    return bytes_sat, bytes_clas, limites


# ---------------------------------------------------------------------------
# 3. GENERACIÓN DEL HTML
# ---------------------------------------------------------------------------
def _leer_libreria(nombre: str) -> str:
    """Lee una librería del visor; da un mensaje claro si falta."""
    ruta = CARPETA_VISOR / nombre
    if not ruta.exists():
        raise SystemExit(
            f"Falta la libreria {ruta}.\n"
            "Descargala desde unpkg.com/leaflet@1.9.4/dist/ y vuelve a ejecutar."
        )
    return ruta.read_text(encoding="utf-8")


def _a_base64(datos: bytes, tipo: str) -> str:
    """Convierte bytes en un data URI para incrustar en el HTML."""
    return f"data:{tipo};base64,{base64.b64encode(datos).decode()}"


def _filas_leyenda() -> str:
    """Genera el bloque HTML de la leyenda de colores."""
    return "".join(
        '<div class="fila-leyenda">'
        f'<span class="cuadro" style="background:{datos["color"]}"></span>'
        f'<span>{datos["nombre"]}</span></div>'
        for datos in config.CLASES.values()
    )


def _extraer_limites(info: dict) -> tuple[list, dict, list]:
    """Convierte la colección de Earth Engine en datos para el visor.

    Devuelve:
      · nombres   — lista con el nombre de cada municipio
      · geojson   — FeatureCollection con los polígonos reales
      · etiquetas — [{nombre, coords:[lat, lon]}] ancladas al centroide

    Los polígonos salen de la MISMA colección con la que se recortó la
    clasificación, por eso el contorno coincide exactamente con el borde
    de los colores. Antes se dibujaban rectángulos como referencia, lo
    que no se parecía en nada a los municipios.
    """
    nombres: list = []
    caracteristicas: list = []
    etiquetas: list = []

    for feat in info.get("features", []):
        props = feat.get("properties", {})
        nombre = props.get("GAUL2_NAME") or props.get("ADM2_NAME", "")
        geometria = feat.get("geometry") or {}

        # Se conserva únicamente el nombre: las propiedades de GAUL son
        # extensas y el visor no las usa, así el HTML pesa menos.
        nombres.append(nombre)
        caracteristicas.append(
            {
                "type": "Feature",
                "properties": {"nombre": nombre},
                "geometry": geometria,
            }
        )

        centro = _centroide_servidor(props) or _centroide(geometria)
        if centro:
            lon, lat = centro
            etiquetas.append({"nombre": nombre, "coords": [lat, lon]})

    geojson = {"type": "FeatureCollection", "features": caracteristicas}
    return nombres, geojson, etiquetas


def _centroide_servidor(props: dict) -> tuple[float, float] | None:
    """Lee el centroide real (ponderado por área) que calcula Earth Engine."""
    lon = props.get("__lon")
    lat = props.get("__lat")
    if lon is None or lat is None:
        return None
    return float(lon), float(lat)


def _centroide(geometria: dict) -> tuple[float, float] | None:
    """Promedio simple de los vértices del anillo exterior.

    Funciona como respaldo si Earth Engine no devuelve el centroide real.
    Ojo: no es el centroide del área, sino la media de los puntos, así que
    tiende a alejarse hacia la zona donde el contorno tiene más vértices.
    """
    tipo = geometria.get("type")
    coords = geometria.get("coordinates")
    if not coords:
        return None

    if tipo == "Polygon":
        anillos = coords
    elif tipo == "MultiPolygon":
        # Cada polígono es una lista de anillos: se aplanan todos.
        anillos = [anillo for poligono in coords for anillo in poligono]
    else:
        return None

    if not anillos:
        return None

    # El anillo con más vértices es el contorno exterior del municipio.
    anillo = max(anillos, key=len)
    lons = [punto[0] for punto in anillo]
    lats = [punto[1] for punto in anillo]
    return sum(lons) / len(lons), sum(lats) / len(lats)


def generar_html(
    bytes_sat: bytes,
    bytes_clas: bytes,
    limites: list,
    geojson: dict,
    etiquetas: list,
    porcentajes: dict,
) -> str:
    """Construye el archivo HTML autocontenido del visor."""
    css = _leer_libreria("leaflet.css")
    js = _leer_libreria("leaflet.js")

    # Se usa .replace() en lugar de f-strings porque el JavaScript y el CSS
    # tienen llaves {} que Python intentaría interpretar como formato.
    marcadores = {
        "@@CSS@@" : css,
        "@@JS@@"  : js,
        "@@IMG_SAT@@"   : _a_base64(bytes_sat, "image/jpeg"),
        "@@IMG_CLAS@@"  : _a_base64(bytes_clas, "image/png"),
        "@@LIMITES@@"   : json.dumps(limites),
        "@@GEOJSON@@"   : json.dumps(geojson),
        "@@ETIQUETAS@@" : json.dumps(etiquetas),
        "@@PORCENTAJES@@" : json.dumps(
            [round(porcentajes.get(c, 0.0), 4) for c in sorted(config.CLASES)]
        ),
        "@@LEYENDA@@"    : _filas_leyenda(),
        "@@RESUMEN@@"    : _resumen_html(porcentajes),
        "@@TITULOS@@"    : ", ".join(
            e["nombre"] for e in etiquetas
        ) or "Municipios",
        "@@FECHA_INICIO@@" : config.FECHA_INICIO,
        "@@FECHA_FIN@@"    : config.FECHA_FIN,
    }

    html = _PLANTILLA
    for marcador, valor in marcadores.items():
        html = html.replace(marcador, valor)
    return html


def _resumen_html(porcentajes: dict) -> str:
    """Filas compactas con las dos coberturas dominantes."""
    if not porcentajes:
        return '<span style="color:#9b9ba3">Sin datos</span>'
    principales = sorted(porcentajes.items(), key=lambda x: -x[1])[:2]
    return "".join(
        '<div class="resumen-fila">'
        f"<span>{config.CLASES[clase]['nombre']}</span>"
        f"<b>{pct:.1f}%</b></div>"
        for clase, pct in principales
    )


# ---------------------------------------------------------------------------
# 4. ORQUESTADOR
# ---------------------------------------------------------------------------
def crear_comparacion(
    geometria: ee.Geometry,
    imagen_clasificada: ee.Image,
    municipios: ee.FeatureCollection,
    porcentajes: dict,
    carpeta: Path,
) -> Path:
    """Genera el HTML del visor y lo abre en el navegador."""
    carpeta.mkdir(exist_ok=True)

    # Se simplifican los polígonos a 100 m de tolerancia: el visor se ve
    # igual (la capa se muestra a ~12 m/px) pero el GeoJSON pesa ~3 KB en
    # vez de decenas. Sale de la MISMA fuente con la que se recortó la
    # clasificación, por eso las líneas calzan exactamente con el borde.
    # El centroide se calcula en el servidor: promediar los vértices
    # desde Python desplaza la etiqueta hacia donde el contorno tiene más
    # puntos, no hacia el centro real del municipio.
    simplificados = municipios.map(
        lambda f: f
        .setGeometry(f.geometry().simplify(100))
        .set("__lon", f.geometry().centroid().coordinates().get(0))
        .set("__lat", f.geometry().centroid().coordinates().get(1))
    )
    info = simplificados.getInfo()

    nombres, geojson, etiquetas = _extraer_limites(info)

    satelital = imagen_satelital(geometria)
    clasifica_colores = clasificacion_visual(imagen_clasificada)
    bytes_sat, bytes_clas, limites = descargar_capas(
        satelital, clasifica_colores, geometria
    )

    html = generar_html(
        bytes_sat, bytes_clas, limites, geojson, etiquetas, porcentajes
    )

    ruta = carpeta / "comparacion.html"
    ruta.write_text(html, encoding="utf-8")
    print(f"[OK] Visor guardado: {ruta.name} ({len(html) / 1e6:.2f} MB)")

    webbrowser.open(ruta.as_uri())
    print("[OK] Visor abierto en el navegador")
    return ruta


# ---------------------------------------------------------------------------
# 5. PLANTILLA HTML
# ---------------------------------------------------------------------------
# Se usa una constante en lugar de f-strings porque el CSS y el JavaScript
# tienen llaves {} que Python intentaría interpretar como formato.
_PLANTILLA = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cobertura terrestre — @@TITULOS@@</title>
<style>
@@CSS@@

html, body { height: 100%; margin: 0; font-family: system-ui, sans-serif; }
#mapa { height: 100%; width: 100%; background: #dfe6e9; }

/* ---------------------------------------------------------------------------
   Medidas de la interfaz. Se repiten en JavaScript (MARGEN_IZQ / MARGEN_SUP)
   para posicionar el divisor y encuadrar el mapa fuera de estos paneles.
   --------------------------------------------------------------------------- */
:root { --ancho-lateral: 264px; --alto-cabecera: 54px; }

/* Barra superior de ancho completo */
#cabecera {
  position: absolute; top: 0; left: 0; right: 0;
  height: var(--alto-cabecera); box-sizing: border-box; z-index: 1300;
  background: #1e1e22; color: #fff; padding: 0 22px;
  display: flex; flex-direction: column; justify-content: center;
  box-shadow: 0 2px 12px rgba(0,0,0,.45);
}
#cabecera b { font-size: 16px; }
#cabecera small { font-size: 12px; opacity: .72; margin-top: 1px; }

/* Panel lateral izquierdo en gris oscuro, con dos módulos apilados */
#lateral {
  position: absolute; top: var(--alto-cabecera); left: 0; bottom: 0;
  width: var(--ancho-lateral); box-sizing: border-box; z-index: 1200;
  background: #2b2b30; color: #e6e6ea; padding: 12px;
  overflow-y: auto; box-shadow: 3px 0 14px rgba(0,0,0,.4);
}
#lateral section {
  background: #35353c; border-radius: 8px; padding: 12px 14px; margin-bottom: 12px;
}
#lateral section:last-child { margin-bottom: 0; }
#lateral h3 {
  margin: 0 0 10px; padding-bottom: 7px; font-size: 12.5px; color: #fff;
  text-transform: uppercase; letter-spacing: .7px;
  border-bottom: 1px solid rgba(255,255,255,.14);
}
#lateral .grupo { margin-bottom: 13px; }
#lateral .grupo:last-child { margin-bottom: 0; }
#lateral .grupo > b {
  display: block; margin-bottom: 6px; font-size: 10.5px;
  color: #9b9ba3; text-transform: uppercase; letter-spacing: .6px;
}
#lateral label { display: block; margin: 5px 0; cursor: pointer; font-size: 13px; }
#lateral input { margin-right: 7px; vertical-align: -1px; }
#lateral select {
  width: 100%; margin-top: 5px; padding: 4px; font-size: 12px;
  border: 1px solid #55555c; border-radius: 5px;
  background: #232328; color: #e6e6ea;
}

/* Leyenda dentro del módulo superior */
.fila-leyenda { display: flex; align-items: center; margin: 4px 0; font-size: 12.5px; }
.fila-leyenda .pct {
  margin-left: auto; padding-left: 10px; color: #b6b6be;
  font-variant-numeric: tabular-nums;
}
.cuadro {
  width: 14px; height: 14px; border-radius: 3px; margin-right: 9px; flex: none;
  border: 1px solid rgba(255,255,255,.28);
}
.resumen-fila {
  display: flex; justify-content: space-between; margin: 4px 0; font-size: 13px;
}
.resumen-fila b { color: #fff; }

/* Divisor del swipe: empieza debajo de la barra superior. La posición
   horizontal la fija JavaScript dentro del área visible (ver refrescar). */
#divisor {
  position: absolute; top: var(--alto-cabecera); bottom: 0; width: 40px;
  left: 50%; transform: translateX(-50%); z-index: 1150; cursor: ew-resize;
  display: flex; align-items: center; justify-content: center;
}
#divisor .linea {
  position: absolute; top: 0; left: 50%; width: 3px; height: 100%;
  transform: translateX(-50%); background: #fff;
  box-shadow: 0 0 7px rgba(0,0,0,.6);
}
#divisor .pomo {
  position: relative; width: 38px; height: 38px; border-radius: 50%;
  background: #fff; border: 3px solid #1e1e22;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 2px 9px rgba(0,0,0,.5); font-size: 15px; color: #1e1e22;
}
#divisor.oculto { display: none; }

/* Etiquetas de cada lado, en el pie */
.etiqueta-lado {
  position: absolute; z-index: 1000; bottom: 30px; padding: 6px 13px;
  background: rgba(20,20,22,.82); color: #fff; border-radius: 6px;
  font-size: 13px; font-weight: 600; pointer-events: none;
}
.etiqueta-izq { left: calc(var(--ancho-lateral) + 14px); }
.etiqueta-der { right: 14px; }

/* Límites municipales: línea amarilla intensa con contorno oscuro para que
   se lea tanto sobre la foto satelital (verde oscuro) como sobre la
   clasificación (verde y rojo). */
.limites-muni {
  filter: drop-shadow(0 0 2.5px rgba(0,0,0,1)) drop-shadow(0 0 2.5px rgba(0,0,0,1));
}

/* Nombres de municipios: solo texto con sombra, sin caja que tape el mapa */
.nombre-muni {
  color: #fff; font-weight: 700; font-size: 14px; white-space: nowrap;
  text-shadow: 0 0 5px #000, 0 0 5px #000, 0 0 3px #000, 0 2px 4px #000;
  transform: translate(-50%, -50%); padding: 2px 3px;
}

/* Los controles de Leaflet se anclan al borde del contenedor del mapa, que
   arranca detrás de la barra superior: se desplazan para no quedar tapados. */
.leaflet-top.leaflet-right    { top: var(--alto-cabecera); }
.leaflet-bottom.leaflet-right { bottom: 26px; }
</style>
</head>
<body>
<div id="mapa"></div>

<div id="cabecera">
  <b>Cobertura terrestre — @@TITULOS@@</b>
  <small>Dynamic World · Sentinel-2 · @@FECHA_INICIO@@ a @@FECHA_FIN@@</small>
</div>

<aside id="lateral">

  <section id="leyenda">
    <h3>Tipos de cobertura</h3>
    @@LEYENDA@@
  </section>

  <section id="panel">
    <h3>Visualización</h3>

    <div class="grupo">
      <b>Modo</b>
      <label><input type="radio" name="modo" value="swipe" checked> Comparar (swipe)</label>
      <label><input type="radio" name="modo" value="clas"> Solo clasificación</label>
      <label><input type="radio" name="modo" value="sat"> Solo satelital</label>
    </div>

    <div class="grupo">
      <b>Capas</b>
      <label><input type="checkbox" id="cLimites" checked> Límites municipales</label>
      <label><input type="checkbox" id="cNombres" checked> Nombres</label>
      <label><input type="checkbox" id="cBase" checked> Mapa base</label>
      <select id="selBase">
        <option value="satelite">Satélite (Esri)</option>
        <option value="calles">Calles (Esri)</option>
        <option value="topografico">Topográfico (Esri)</option>
        <option value="opentopo">Topográfico (OpenTopoMap)</option>
      </select>
    </div>

    <div class="grupo">
      <b>Cobertura dominante</b>
      @@RESUMEN@@
    </div>
  </section>

</aside>

<div class="etiqueta-lado etiqueta-izq">🛰️ Imagen satelital</div>
<div class="etiqueta-lado etiqueta-der">🤖 Clasificación IA</div>

<div id="divisor">
  <div class="linea"></div>
  <div class="pomo">⟷</div>
</div>

<script>
@@JS@@

/* ---------- Datos incrustados ---------- */
var URL_SAT    = "@@IMG_SAT@@";
var URL_CLAS   = "@@IMG_CLAS@@";
var LIMITES    = @@LIMITES@@;
var GEOJSON    = @@GEOJSON@@;
var ETIQUETAS  = @@ETIQUETAS@@;
var PORCENTAJES = @@PORCENTAJES@@;

/* ---------- Mapa ---------- */
/* zoomSnap: 0 permite zoom con decimales, para que fitBounds encuadre
   exactamente los límites sin dejar bandas vacías cuando la forma de la
   zona no coincide con la forma de la ventana. */
var MARGEN_IZQ = 264;   /* ancho del panel lateral (ver --ancho-lateral) */
var MARGEN_SUP = 54;    /* alto de la barra superior (ver --alto-cabecera) */

var mapa = L.map('mapa', {zoomSnap: 0, zoomDelta: 0.5});
/* El encuadre descuenta el panel lateral y la barra superior, para que
   los municipios queden centrados en el área realmente visible. */
mapa.fitBounds(LIMITES, {
  paddingTopLeft:  [MARGEN_IZQ + 24, MARGEN_SUP + 24],
  paddingBottomRight: [24, 24]
});
/* Los controles por defecto quedan tapados por el panel, así que se
   mueven a la esquina libre. */
L.control.zoom({position: 'topright'}).addTo(mapa);
L.control.scale({imperial: false, position: 'bottomright'}).addTo(mapa);

/* Mapas base.
   Requisito: funcionar sin clave de API y sin bloquearse al abrir el
   archivo con doble clic (file://).
     · tile.openstreetmap.org  -> devuelve error 403 «Access blocked»,
       porque no puede verificar el origen de la petición.
     · basemaps.cartocdn.com   -> muestra una losa «API KEY REQUIRED».
   Los servicios de Esri (ArcGIS Online) y OpenTopoMap sí son gratuitos,
   no exigen clave y no revisan el encabezado Referer. */
var BASEMAPAS = {
  satelite: {
    /* Ojo: Esri ordena la URL como {z}/{y}/{x}, no {z}/{x}/{y}. */
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    sub: '', attr: 'Imágenes: Esri, Maxar, Earthstar Geographics'
  },
  calles: {
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
    sub: '', attr: '© Esri, HERE, Garmin, OpenStreetMap'
  },
  topografico: {
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
    sub: '', attr: '© Esri, HERE, Garmin, OpenStreetMap'
  },
  opentopo: {
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    sub: 'abc', attr: '© OpenTopoMap (CC-BY-SA) · © OpenStreetMap'
  }
};

var capaBase = null;
function cambiarBase(clave) {
  var def = BASEMAPAS[clave];
  if (!def) return;
  if (capaBase) mapa.removeLayer(capaBase);
  capaBase = L.tileLayer(def.url, {
    maxZoom: 19, attribution: def.attr, subdomains: def.sub
  });
  /* Los tiles van en el panel de teselas (tilePane), que Leaflet dibuja
     por debajo de los imageOverlay, así que la imagen satelital y la
     clasificación siempre quedan encima del mapa base. */
  capaBase.addTo(mapa);
}
cambiarBase('satelite');

var sat  = L.imageOverlay(URL_SAT,  LIMITES).addTo(mapa);
var clas = L.imageOverlay(URL_CLAS, LIMITES).addTo(mapa);

var capaLimites = L.geoJSON(GEOJSON, {
  /* Los polígonos REALES de los municipios (FAO/GAUL, los mismos con los
     que se recortó la clasificación, así el contorno calza exactamente
     con el borde de los colores). Trazo gris claro discontinuo con doble
     contorno oscuro (clase .limites-muni) para que se lea igual sobre la
     foto satelital oscura que sobre los verdes y rojos de la clasificación. */
  className: 'limites-muni',
  style: {color: '#d9d9d9', weight: 2.5, fill: false, dashArray: '12 7'}
}).addTo(mapa);

var capaNombres = L.layerGroup().addTo(mapa);
ETIQUETAS.forEach(function (item) {
  L.marker(item.coords, {
    interactive: false,
    icon: L.divIcon({
      className: '',
      /* Solo texto con sombra: sin caja de fondo, para no tapar el mapa. */
      html: '<div class="nombre-muni">' + item.nombre + '</div>',
      iconSize: [0, 0]
    })
  }).addTo(capaNombres);
});

/* ---------- Leyenda con porcentajes ---------- */
var filasLeyenda = document.querySelectorAll('#leyenda .fila-leyenda');
filasLeyenda.forEach(function (fila, i) {
  var span = document.createElement('span');
  span.className = 'pct';
  span.textContent = (PORCENTAJES[i] !== undefined)
    ? PORCENTAJES[i].toFixed(1) + '%' : '—';
  fila.appendChild(span);
});

/* ---------- Comparador swipe ---------- */
var posDivisor = 0.5;      /* posición relativa del divisor (0 a 1) */
var modoActual = 'swipe';
var elDivisor  = document.getElementById('divisor');

/* El área realmente visible es la que queda a la derecha del panel
   lateral: sobre ella se calculan tanto la posición del divisor como el
   recorte de la clasificación. */
function areaVisible() {
  var rect = mapa.getContainer().getBoundingClientRect();
  return {
    izquierda: rect.left + MARGEN_IZQ,
    ancho: Math.max(1, rect.width - MARGEN_IZQ)
  };
}

function aplicarClip() {
  var elClas = clas.getElement();
  if (!elClas) return;

  var vis = areaVisible();
  var xDivisor = vis.izquierda + posDivisor * vis.ancho;

  /* La imagen satelital es la capa base y SIEMPRE se ve completa.
     Lo que se recorta es la clasificación: se oculta a la izquierda del
     divisor, de modo que al arrastrar la capa de coberturas va
     descubriendo la fotografía real que tiene debajo. */
  var rClas = elClas.getBoundingClientRect();
  elClas.style.clipPath = 'inset(0 0 0 ' + Math.max(0, xDivisor - rClas.left) + 'px)';
}

function quitarClip() {
  var elClas = clas.getElement();
  if (elClas) elClas.style.clipPath = 'none';
}

function refrescar() {
  /* Se fija en píxeles dentro del área visible; el translateX(-50%) del
     CSS centra el pomito sobre esa posición. */
  var vis = areaVisible();
  elDivisor.style.left = (vis.izquierda - mapa.getContainer().getBoundingClientRect().left
                          + posDivisor * vis.ancho) + 'px';
  if (modoActual === 'swipe') aplicarClip();
}

function aplicarModo() {
  var enMapa = function (capa) { return mapa.hasLayer(capa); };

  if (modoActual === 'swipe') {
    /* El orden de las capas importa: la satelital es la base y la
       clasificación va ENCIMA, porque es la que se recorta con el
       divisor. Se quitan y se vuelven a añadir en el orden correcto
       por si antes estaban invertidas en otro modo. Al ser imágenes
       incrustadas en el HTML, el reordenamiento es instantáneo. */
    if (enMapa(sat))  mapa.removeLayer(sat);
    if (enMapa(clas)) mapa.removeLayer(clas);
    mapa.addLayer(sat);
    mapa.addLayer(clas);
    elDivisor.classList.remove('oculto');
  } else if (modoActual === 'clas') {
    quitarClip();
    if (!enMapa(clas)) mapa.addLayer(clas);
    if (enMapa(sat))  mapa.removeLayer(sat);
    elDivisor.classList.add('oculto');
  } else {
    quitarClip();
    if (!enMapa(sat))  mapa.addLayer(sat);
    if (enMapa(clas)) mapa.removeLayer(clas);
    elDivisor.classList.add('oculto');
  }
  refrescar();
}

/* Arrastre del divisor (ratón y táctil) */
var arrastrando = false;
function posicionX(e) {
  return e.touches && e.touches.length ? e.touches[0].clientX : e.clientX;
}
function alMover(e) {
  if (!arrastrando) return;
  /* Se calcula sobre el área visible (a la derecha del panel lateral),
     así el divisor no puede acabar oculto bajo la barra lateral. */
  var vis = areaVisible();
  posDivisor = Math.min(1, Math.max(0, (posicionX(e) - vis.izquierda) / vis.ancho));
  refrescar();
  e.preventDefault();
}
elDivisor.addEventListener('mousedown', function (e) { arrastrando = true; e.preventDefault(); });
elDivisor.addEventListener('touchstart', function (e) { arrastrando = true; e.preventDefault(); }, {passive: false});
window.addEventListener('mousemove', alMover);
window.addEventListener('touchmove', alMover, {passive: false});
window.addEventListener('mouseup',   function () { arrastrando = false; });
window.addEventListener('touchend',  function () { arrastrando = false; });

/* Doble clic = volver al centro del divisor */
elDivisor.addEventListener('dblclick', function () {
  posDivisor = 0.5; refrescar();
});

/* ---------- Controles del panel ---------- */
document.querySelectorAll('input[name=modo]').forEach(function (radio) {
  radio.addEventListener('change', function () {
    modoActual = radio.value;
    aplicarModo();
  });
});
document.getElementById('cLimites').addEventListener('change', function (e) {
  if (e.target.checked) mapa.addLayer(capaLimites); else mapa.removeLayer(capaLimites);
});
document.getElementById('cNombres').addEventListener('change', function (e) {
  if (e.target.checked) mapa.addLayer(capaNombres); else mapa.removeLayer(capaNombres);
});
document.getElementById('cBase').addEventListener('change', function (e) {
  if (e.target.checked) cambiarBase(document.getElementById('selBase').value);
  else if (capaBase) { mapa.removeLayer(capaBase); capaBase = null; }
});
document.getElementById('selBase').addEventListener('change', function (e) {
  if (document.getElementById('cBase').checked) cambiarBase(e.target.value);
});

/* Mantener el recorte alineado al mover o hacer zoom */
mapa.on('move zoom moveend zoomend resize', refrescar);

aplicarModo();
</script>
</body>
</html>
"""
