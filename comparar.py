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


def _etiquetas_nombres(nombres: list, limites: list) -> list:
    """Coloca una etiqueta por municipio, repartidas horizontalmente."""
    sur, oeste = limites[0]
    norte, este = limites[1]
    cantidad = max(len(nombres), 1)
    etiquetas = []
    for indice, nombre in enumerate(nombres):
        lon = oeste + (este - oeste) * ((indice + 0.5) / cantidad)
        lat = sur + (norte - sur) * 0.5
        etiquetas.append({"nombre": nombre, "coords": [lat, lon]})
    return etiquetas


def _geojson_referencia(nombres: list, limites: list) -> dict:
    """GeoJSON simple: un rectángulo por municipio como referencia.

    Los límites reales son complejos y aumentarían mucho el tamaño del
    HTML. Estos rectángulos dan contexto geográfico sin pesar; si
    necesitas los polígonos exactos, abre el GeoTIFF en QGIS.
    """
    sur, oeste = limites[0]
    norte, este = limites[1]
    ancho = (este - oeste) / max(len(nombres), 1)

    caracteristicas = []
    for indice in range(len(nombres)):
        o = oeste + ancho * indice
        e = oeste + ancho * (indice + 1)
        anillo = [[o, sur], [e, sur], [e, norte], [o, norte], [o, sur]]
        caracteristicas.append(
            {
                "type": "Feature",
                "properties": {"nombre": nombres[indice]},
                "geometry": {"type": "Polygon", "coordinates": [anillo]},
            }
        )
    return {"type": "FeatureCollection", "features": caracteristicas}


def generar_html(
    bytes_sat: bytes,
    bytes_clas: bytes,
    limites: list,
    nombres: list,
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
        "@@GEOJSON@@"   : json.dumps(_geojson_referencia(nombres, limites)),
        "@@ETIQUETAS@@" : json.dumps(_etiquetas_nombres(nombres, limites)),
        "@@PORCENTAJES@@" : json.dumps(
            [round(porcentajes.get(c, 0.0), 4) for c in sorted(config.CLASES)]
        ),
        "@@LEYENDA@@"    : _filas_leyenda(),
        "@@RESUMEN@@"    : _resumen_html(porcentajes),
        "@@TITULOS@@"    : ", ".join(nombres),
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
        return '<span style="color:#888">Sin datos</span>'
    principales = sorted(porcentajes.items(), key=lambda x: -x[1])[:2]
    return "".join(
        '<div style="display:flex;justify-content:space-between;margin:2px 0">'
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

    nombres = [
        props.get("GAUL2_NAME") or props.get("ADM2_NAME", "")
        for props in (
            feat.get("properties", {})
            for feat in municipios.getInfo()["features"]
        )
    ]

    satelital = imagen_satelital(geometria)
    clasifica_colores = clasificacion_visual(imagen_clasificada)
    bytes_sat, bytes_clas, limites = descargar_capas(
        satelital, clasifica_colores, geometria
    )

    html = generar_html(bytes_sat, bytes_clas, limites, nombres, porcentajes)

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

/* Panel de control lateral */
#panel {
  position: absolute; top: 12px; right: 12px; z-index: 1000;
  background: rgba(255,255,255,.96); border-radius: 10px;
  padding: 14px 16px; box-shadow: 0 3px 14px rgba(0,0,0,.28);
  width: 232px; box-sizing: border-box; font-size: 13px;
}
#panel h3 { margin: 0 0 8px; font-size: 14px; }
#panel .grupo { margin-bottom: 12px; }
#panel .grupo > b {
  display: block; margin-bottom: 6px; font-size: 11px;
  color: #666; text-transform: uppercase; letter-spacing: .5px;
}
#panel label { display: block; margin: 4px 0; cursor: pointer; }
#panel input { margin-right: 6px; vertical-align: -1px; }

/* Divisor del swipe */
#divisor {
  position: absolute; top: 0; left: 50%; height: 100%; width: 40px;
  transform: translateX(-50%); z-index: 1100; cursor: ew-resize;
  display: flex; align-items: center; justify-content: center;
}
#divisor .linea {
  position: absolute; top: 0; left: 50%; width: 3px; height: 100%;
  transform: translateX(-50%); background: #fff;
  box-shadow: 0 0 6px rgba(0,0,0,.55);
}
#divisor .pomo {
  position: relative; width: 38px; height: 38px; border-radius: 50%;
  background: #fff; border: 3px solid #2d3436;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 2px 8px rgba(0,0,0,.45); font-size: 15px; color: #2d3436;
}
#divisor.oculto { display: none; }

/* Etiquetas de lado: en el pie, para no chocar con el título ni el panel */
.etiqueta-lado {
  position: absolute; z-index: 900; bottom: 28px; padding: 6px 12px;
  background: rgba(0,0,0,.72); color: #fff; border-radius: 6px;
  font-size: 13px; font-weight: 600; pointer-events: none;
}
.etiqueta-izq { left: 78px; }
.etiqueta-der { right: 218px; }

/* Leyenda */
#leyenda {
  position: absolute; bottom: 26px; right: 12px; z-index: 1000;
  background: rgba(255,255,255,.96); border-radius: 10px;
  padding: 12px 14px; box-shadow: 0 3px 14px rgba(0,0,0,.28);
  font-size: 12px; max-height: 40%; overflow-y: auto; width: 190px;
}
#leyenda h3 { margin: 0 0 8px; font-size: 13px; }
.fila-leyenda { display: flex; align-items: center; margin: 3px 0; }
.fila-leyenda .pct { margin-left: auto; color: #555; padding-left: 10px; }
.cuadro {
  width: 14px; height: 14px; border-radius: 3px; margin-right: 8px;
  border: 1px solid rgba(0,0,0,.2); flex: none;
}

/* Barra de título: se centra en el espacio libre entre el control de zoom
   (izquierda) y el panel de opciones (derecha), así nunca se solapan. */
#cabecera {
  position: absolute; top: 12px; left: 78px; right: 262px;
  z-index: 1000; background: rgba(0,0,0,.78); color: #fff;
  padding: 9px 20px; border-radius: 8px; text-align: center;
  pointer-events: none; box-shadow: 0 3px 14px rgba(0,0,0,.3);
}
#cabecera b { font-size: 15px; }
#cabecera small { display: block; opacity: .85; margin-top: 2px; }
</style>
</head>
<body>
<div id="mapa"></div>

<div id="cabecera">
  <b>Cobertura terrestre — @@TITULOS@@</b>
  <small>Dynamic World · Sentinel-2 · @@FECHA_INICIO@@ a @@FECHA_FIN@@</small>
</div>

<div class="etiqueta-lado etiqueta-izq">🛰️ Imagen satelital</div>
<div class="etiqueta-lado etiqueta-der">🤖 Clasificación IA</div>

<div id="divisor">
  <div class="linea"></div>
  <div class="pomo">⟷</div>
</div>

<div id="panel">
  <h3>🎛️ Visualización</h3>

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
    <select id="selBase" style="width:100%;margin-top:5px;padding:3px">
      <option value="satelite">Satélite (Esri)</option>
      <option value="calles">Calles (Esri)</option>
      <option value="topografico">Topográfico (Esri)</option>
      <option value="opentopo">Topográfico (OpenTopoMap)</option>
    </select>
  </div>

  <div class="grupo" style="margin-bottom:0">
    <b>Cobertura dominante</b>
    @@RESUMEN@@
  </div>
</div>

<div id="leyenda">
  <h3>Tipos de cobertura</h3>
  @@LEYENDA@@
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
var mapa = L.map('mapa', {zoomSnap: 0, zoomDelta: 0.5}).fitBounds(LIMITES, {padding: [24, 24]});
L.control.scale({imperial: false}).addTo(mapa);

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
  style: {color: '#2d3436', weight: 2.5, fill: false, dashArray: '6 4'}
}).addTo(mapa);

var capaNombres = L.layerGroup().addTo(mapa);
ETIQUETAS.forEach(function (item) {
  L.marker(item.coords, {
    interactive: false,
    icon: L.divIcon({
      className: '',
      html: '<div style="background:rgba(255,255,255,.92);padding:4px 10px;'
          + 'border-radius:6px;font-weight:700;font-size:13px;white-space:nowrap;'
          + 'border:1px solid rgba(0,0,0,.25);box-shadow:0 1px 4px rgba(0,0,0,.3)">'
          + item.nombre + '</div>',
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

function aplicarClip() {
  var elClas = clas.getElement();
  if (!elClas) return;

  var rect = mapa.getContainer().getBoundingClientRect();
  var xDivisor = rect.left + posDivisor * rect.width;

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
  elDivisor.style.left = (posDivisor * 100) + '%';
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
  var rect = mapa.getContainer().getBoundingClientRect();
  posDivisor = Math.min(1, Math.max(0, (posicionX(e) - rect.left) / rect.width));
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
