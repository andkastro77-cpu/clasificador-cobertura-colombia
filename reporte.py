"""Generación de resultados: mapa temático (PNG), estadísticas (CSV) y GeoTIFF."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Patch
import numpy as np
import geopandas as gpd
import pandas as pd
import rasterio
from rasterio.features import geometry_mask

import ee
import config


def descargar_raster(imagen: ee.Image, geometria: ee.Geometry, ruta: Path) -> Path:
    """Descarga la imagen clasificada como GeoTIFF (abrible en QGIS)."""
    region = geometria.bounds().getInfo()["coordinates"]

    url = imagen.getDownloadURL(
        {
            "scale": config.ESCALA_M,
            "crs": config.CRS_SALIDA,
            "region": region,
            "format": "GEO_TIFF",
            "filePerBand": False,
        }
    )

    import urllib.request

    with urllib.request.urlopen(url, timeout=300) as respuesta:
        datos = respuesta.read()

    ruta.write_bytes(datos)
    print(f"[OK] Ráster guardado: {ruta.name} ({len(datos) / 1e6:.2f} MB)")
    return ruta


def formato_porcentaje(valor: float) -> str:
    """Evita mostrar '0.0%' cuando el valor es pequeño pero no cero."""
    if valor == 0:
        return "0%"
    if valor < 0.1:
        return "<0.1%"
    return f"{valor:.1f}%"


def tabla_estadisticas(porcentajes: dict) -> pd.DataFrame:
    """Convierte {clase: %} en una tabla ordenada y legible."""
    filas = [
        {
            "Clase": config.CLASES[c]["nombre"],
            "Cobertura (%)": round(p, 2),
        }
        for c, p in sorted(porcentajes.items(), key=lambda x: -x[1])
        if c in config.CLASES
    ]
    return pd.DataFrame(filas)


def _paleta_clases() -> tuple[ListedColormap, BoundaryNorm, list]:
    """Mapa de colores y límites para dibujar las 9 clases del modelo."""
    colores = [config.CLASES[c]["color"] for c in sorted(config.CLASES)]
    cmap = ListedColormap(colores, "cobertura")
    # Los píxeles tienen valores enteros 0..8; los límites mitad a mitad
    # evitan que el color se mezcle entre clases vecinas.
    limites = [c - 0.5 for c in sorted(config.CLASES)] + [len(colores) - 0.5]
    norm = BoundaryNorm(limites, cmap.N)
    return cmap, norm, colores


def graficar_mapa(
    ruta_tif: Path,
    gdf: gpd.GeoDataFrame,
    porcentajes: dict,
    ruta_png: Path,
) -> Path:
    """Mapa temático: ráster clasificado de fondo + límites municipales.

    El ráster se lee con rasterio y se recorta a los municipios para que
    no se dibuje el área rectangular que queda fuera de sus límites.
    """
    cmap, norm, _ = _paleta_clases()
    gdf_m = gdf.to_crs(config.CRS_SALIDA)  # misma proyección del ráster

    with rasterio.open(ruta_tif) as src:
        datos = src.read(1)
        transform = src.transform
        limites = src.bounds

    # Enmascara todo lo que quede fuera de los municipios.
    dentro = ~geometry_mask(
        list(gdf_m.geometry),
        out_shape=datos.shape,
        transform=transform,
    )
    datos = np.ma.masked_where(~dentro, datos)

    # Figura: mapa grande + barra de proporciones debajo.
    fig = plt.figure(figsize=(11, 12))
    rejilla = fig.add_gridspec(2, 1, height_ratios=[4.5, 1])
    ax_mapa = fig.add_subplot(rejilla[0])
    ax_barra = fig.add_subplot(rejilla[1])

    # --- Mapa ---
    ax_mapa.imshow(
        datos,
        cmap=cmap,
        norm=norm,
        interpolation="nearest",
        extent=(limites.left, limites.right, limites.bottom, limites.top),
    )
    gdf_m.boundary.plot(ax=ax_mapa, color="black", linewidth=1.4)

    for _, fila in gdf_m.iterrows():
        punto = fila.geometry.representative_point()
        ax_mapa.annotate(
            fila["nombre"],
            xy=(punto.x, punto.y),
            ha="center",
            fontsize=13,
            fontweight="bold",
            color="black",
            bbox=dict(boxstyle="round,pad=0.35", fc="white", alpha=0.85),
        )

    ax_mapa.set_title(
        "Cobertura terrestre — Envigado y Sabaneta (Antioquia)\n"
        "Modelo Dynamic World · Sentinel-2 · 10 m",
        fontsize=15,
        fontweight="bold",
    )
    ax_mapa.set_xlabel("Este (m) · UTM 18N")
    ax_mapa.set_ylabel("Norte (m) · UTM 18N")

    # Rosa de los vientos (flecha N).
    ax_mapa.annotate(
        "N",
        xy=(0.96, 0.95),
        xycoords="axes fraction",
        ha="center",
        va="center",
        fontsize=13,
        fontweight="bold",
    )
    ax_mapa.annotate(
        "",
        xy=(0.96, 0.90),
        xytext=(0.96, 0.99),
        xycoords="axes fraction",
        arrowprops=dict(arrowstyle="-|>", color="black", lw=2),
    )

    # --- Barra de proporciones ---
    disponibles = [c for c in sorted(config.CLASES) if porcentajes.get(c, 0) > 0]
    izquierda = 0.0
    for clase in disponibles:
        ancho = porcentajes[clase]
        ax_barra.barh(
            0, ancho, left=izquierda, height=1.0,
            color=config.CLASES[clase]["color"], edgecolor="white", linewidth=1.2,
        )
        if ancho >= 5:  # etiqueta solo si cabe dentro del bloque
            ax_barra.text(
                izquierda + ancho / 2, 0, formato_porcentaje(ancho),
                ha="center", va="center", fontsize=10, fontweight="bold",
            )
        izquierda += ancho

    ax_barra.set_xlim(0, 100)
    ax_barra.set_ylim(-0.5, 0.5)
    ax_barra.set_yticks([])
    ax_barra.set_xlabel("% de superficie de los dos municipios")
    ax_barra.set_title("Composición total", fontsize=12, fontweight="bold")
    for eje in ("top", "right", "left"):
        ax_barra.spines[eje].set_visible(False)

    # --- Leyenda ---
    leyenda = [
        Patch(
            facecolor=config.CLASES[c]["color"],
            label=f"{config.CLASES[c]['nombre']} — "
                  f"{formato_porcentaje(porcentajes.get(c, 0))}",
        )
        for c in disponibles
    ]
    ax_mapa.legend(
        handles=leyenda,
        loc="lower left",
        fontsize=10,
        framealpha=0.92,
        title="Tipo de cobertura",
        title_fontsize=11,
    )

    fig.tight_layout()
    fig.savefig(ruta_png, dpi=150)
    plt.close(fig)
    print(f"[OK] Mapa guardado: {ruta_png.name}")
    return ruta_png
