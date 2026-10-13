"""Límites administrativos de los municipios de estudio.

Usa la colección FAO/GAUL/2015/level2 (bordes administrativos mundiales
gratuitos disponibles en Google Earth Engine) y filtra los municipios
indicados en config.MUNICIPIOS.
"""

import geopandas as gpd
from shapely.geometry import shape

import ee
import config


def obtener_municipios() -> ee.FeatureCollection:
    """Devuelve los límites de Sabaneta y Envigado como FeatureCollection.

    Usa el asset FAO/GAUL/2025 (bordes administrativos mundiales) y, si
    aún no estuviera disponible, regresa al clásico GAUL/2015.
    """
    for asset in ("FAO/GAUL/2025/level2", "FAO/GAUL/2015/level2"):
        try:
            gaul = ee.FeatureCollection(asset)
            municipios = gaul.filter(_filtro_municipios())
            cantidad = municipios.size().getInfo()
            if cantidad > 0:
                print(f"[OK] {cantidad} municipio(s) en {asset}: {config.MUNICIPIOS}")
                return municipios
        except Exception as advertencia:
            print(f"[AVISO] {asset} no disponible ({type(advertencia).__name__})")

    raise SystemExit(
        f"No se encontraron los municipios {config.MUNICIPIOS} en GAUL. "
        "Verifica los nombres (deben coincidir exactamente)."
    )


def _filtro_municipios() -> ee.Filter:
    """Filtro: país = Colombia y nombre del municipio en la lista."""
    return ee.Filter.And(
        ee.Filter.eq("ADM0_NAME", config.PAIS),
        ee.Filter.inList("ADM2_NAME", config.MUNICIPIOS),
    )


def geometria_unida(municipios: ee.FeatureCollection) -> ee.Geometry:
    """Une los municipios en una sola geometría (para recortar la imagen)."""
    return municipios.geometry()


def a_geodataframe(municipios: ee.FeatureCollection) -> gpd.GeoDataFrame:
    """Convierte la colección de Earth Engine a GeoDataFrame local (mapa PNG)."""
    geojson = municipios.getInfo()  # descarga los límites al PC
    registros = [
        {
            "nombre": props.get("ADM2_NAME", ""),
            "geometry": shape(feat["geometry"]),
        }
        for feat in geojson["features"]
        for props in [feat.get("properties", {})]
    ]
    return gpd.GeoDataFrame(registros, crs="EPSG:4326")
