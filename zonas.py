"""Límites administrativos de los municipios de estudio.

Usa la colección FAO/GAUL (bordes administrativos mundiales gratuitos
disponibles en Google Earth Engine).

Importante: GAUL/2025 renombró los campos respecto a GAUL/2015:
    2015: ADM0_NAME, ADM2_NAME
    2025: GAUL0_NAME, GAUL2_NAME  (y el país también se puede buscar por ISO3_CODE)
Esta función detecta automáticamente qué nombres usa cada versión.
"""

import geopandas as gpd
from shapely.geometry import shape

import ee
import config

# Versiones del dataset, de la más nueva a la más vieja.
ASSETS_GAUL = ("FAO/GAUL/2025/level2", "FAO/GAUL/2015/level2")


def _campos_pais_municipio(coleccion: ee.FeatureCollection) -> tuple[str, str]:
    """Detecta los nombres de campo del país y del municipio."""
    campos = coleccion.first().propertyNames().getInfo()

    campo_pais = next((c for c in ("GAUL0_NAME", "ADM0_NAME") if c in campos), None)
    campo_mun = next((c for c in ("GAUL2_NAME", "ADM2_NAME") if c in campos), None)

    if not campo_pais or not campo_mun:
        raise RuntimeError(f"Campos inesperados en el dataset: {campos}")
    return campo_pais, campo_mun


def _buscar_en(asset: str) -> ee.FeatureCollection | None:
    """Intenta localizar los municipios en un asset; None si no están."""
    try:
        coleccion = ee.FeatureCollection(asset)
        campo_pais, campo_mun = _campos_pais_municipio(coleccion)

        filtro = ee.Filter.And(
            ee.Filter.eq(campo_pais, config.PAIS),
            ee.Filter.inList(campo_mun, config.MUNICIPIOS),
        )
        municipios = coleccion.filter(filtro)

        if municipios.size().getInfo() == 0:
            return None
        return municipios

    except Exception as error:
        print(f"[AVISO] No se pudo usar {asset}: {type(error).__name__}")
        return None


def obtener_municipios() -> ee.FeatureCollection:
    """Devuelve los límites de Sabaneta y Envigado como FeatureCollection."""
    for asset in ASSETS_GAUL:
        municipios = _buscar_en(asset)
        if municipios is not None:
            print(f"[OK] Municipios localizados en {asset}: {config.MUNICIPIOS}")
            return municipios

    raise SystemExit(
        f"No se encontraron los municipios {config.MUNICIPIOS} en GAUL. "
        "Verifica los nombres (deben coincidir exactamente)."
    )


def geometria_unida(municipios: ee.FeatureCollection) -> ee.Geometry:
    """Une los municipios en una sola geometría (para recortar la imagen)."""
    return municipios.geometry()


def a_geodataframe(municipios: ee.FeatureCollection) -> gpd.GeoDataFrame:
    """Convierte la colección de Earth Engine a GeoDataFrame local (mapa PNG)."""
    geojson = municipios.getInfo()  # descarga los límites al PC
    registros = [
        {
            "nombre": props.get("GAUL2_NAME") or props.get("ADM2_NAME", ""),
            "geometry": shape(feat["geometry"]),
        }
        for feat in geojson["features"]
        for props in [feat.get("properties", {})]
    ]
    return gpd.GeoDataFrame(registros, crs="EPSG:4326")
