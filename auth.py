"""Autenticación con Google Earth Engine.

Uso:
    import auth
    ee = auth.conectar()   # devuelve un cliente de Earth Engine listo
"""

import ee

import config


def conectar() -> ee.Initialize:
    """Inicializa Earth Engine con manejo claro de errores.

    Si nunca te has autenticado, llama a ee.Authenticate() automáticamente
    y abre el navegador para que autorices tu cuenta de Google.
    """
    if not config.PROYECTO_GEE:
        raise SystemExit(
            "Falta el proyecto de Google Cloud.\n"
            "Solución: define la variable de entorno EE_PROJECT_ID con el ID "
            "de tu proyecto (ejemplo: mi-proyecto-123) y vuelve a ejecutar.\n"
            "  PowerShell:  $env:EE_PROJECT_ID = 'mi-proyecto-123'\n"
            "O edítalo directamente en config.py (línea PROYECTO_GEE)."
        )

    try:
        ee.Initialize(project=config.PROYECTO_GEE)
    except Exception:
        # Primera vez: abre el navegador para autorizar la cuenta.
        ee.Authenticate()
        ee.Initialize(project=config.PROYECTO_GEE)

    print(f"[OK] Google Earth Engine conectado (proyecto: {config.PROYECTO_GEE})")
    return ee
