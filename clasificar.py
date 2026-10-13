"""Motor de clasificación: Sentinel-2 + Dynamic World (modelo de código abierto).

Dynamic World (https://dynamicworld.app) es un modelo de deep learning
entrenado por Google + WRI sobre Sentinel-2. Clasifica cada píxel en
9 tipos de cobertura a 10 metros de resolución. Todo el cómputo ocurre
en la nube de Google: aquí solo se construye y lanza la tarea.
"""

import ee
import config


def imagen_sentinel2(geometria: ee.Geometry) -> ee.ImageCollection:
    """Colección Sentinel-2 SR sin nubes marcadas de más de MAX_NUBES %."""
    return (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(geometria)
        .filterDate(config.FECHA_INICIO, config.FECHA_FIN)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", config.MAX_NUBES))
    )


def clasificar(geometria: ee.Geometry) -> ee.Image:
    """Aplica Dynamic World y devuelve una imagen etiquetada (0-8).

    Estrategia: para cada píxel se calcula la probabilidad media de cada
    clase a lo largo de todas las escenas de la ventana temporal, y se
    queda con la clase más probable (promedio temporal = menos ruido por
    nubes y sombras).
    """
    dw = (
        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
        .filterBounds(geometria)
        .filterDate(config.FECHA_INICIO, config.FECHA_FIN)
    )

    total = dw.size().getInfo()
    if total == 0:
        raise SystemExit(
            "No hay imágenes Dynamic World en la ventana de fechas. "
            "Amplía FECHA_INICIO/FECHA_FIN en config.py."
        )
    print(f"[OK] {total} escenas Dynamic World en {config.FECHA_INICIO} → {config.FECHA_FIN}")

    # Bandas de probabilidad de las 9 clases (sin la banda 'label').
    bandas = [
        "water",
        "trees",
        "grass",
        "crops",
        "shrub_and_scrub",
        "built",
        "bare",
        "snow_and_ice",
        "flooded_vegetation",
    ]

    # Promedio temporal de probabilidades → imagen con 9 bandas.
    promedio = dw.select(bandas).mean()

    # Argmax manual: el valor máximo de probabilidad entre las 9 bandas...
    maximo = promedio.reduce(ee.Reducer.max())
    # ...y la posición (índice) de esa banda = clase ganadora (0 a 8).
    etiquetas = ee.Image(0).rename("cobertura")
    for indice, banda in enumerate(bandas):
        etiquetas = etiquetas.where(promedio.select(banda).eq(maximo), indice)

    # Recorte exacto a los municipios.
    return etiquetas.clip(geometria).toByte()


def estadisticas_servidor(imagen: ee.Image, geometria: ee.Geometry) -> dict:
    """Calcula el % de superficie por clase en el servidor de Google.

    Cuenta píxeles por clase con 'frequencyHistogram'. Se fuerza la misma
    proyección (UTM 18N) y resolución (10 m) que la del ráster descargado,
    para que el CSV y el GeoTIFF digan exactamente lo mismo.

    Nota: todos los píxeles de Dynamic World tienen el mismo tamaño, por
    lo que el % de píxeles = % de superficie.
    """
    histograma = imagen.reduceRegion(
        reducer=ee.Reducer.frequencyHistogram(),
        geometry=geometria,
        scale=config.ESCALA_M,
        crs=config.CRS_SALIDA,
        maxPixels=1e13,
    ).getInfo()

    # getInfo devuelve {'cobertura': {'0': n, '1': n, ...}}
    conteos: dict = histograma.get("cobertura") or histograma
    if not conteos:
        return {}

    total = sum(conteos.values())
    if total == 0:
        return {}

    return {int(clase): 100.0 * cuenta / total for clase, cuenta in conteos.items()}
