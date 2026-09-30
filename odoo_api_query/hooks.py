# -*- coding: utf-8 -*-
"""Al instalar, la clave de la API no puede quedar en el valor del repo."""
import logging
import secrets

_logger = logging.getLogger(__name__)

CLAVE_MARCADOR = "123456789"


def post_init_hook(env):
    """Reemplaza el marcador del XML por una clave aleatoria.

    El XML trae 123456789 porque el parámetro necesita un valor, y ese valor
    está en el repositorio: cualquiera que lo lea podría consultar la API.
    """
    Param = env["ir.config_parameter"].sudo()
    if Param.get_param("api_query.api_key") in (False, "", CLAVE_MARCADOR):
        Param.set_param("api_query.api_key", secrets.token_urlsafe(48))
        _logger.info("odoo_api_query: se generó una clave de API aleatoria "
                     "(Ajustes > Técnico > Parámetros del sistema > api_query.api_key).")
