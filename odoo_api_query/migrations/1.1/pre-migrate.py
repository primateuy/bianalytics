# -*- coding: utf-8 -*-
"""Los parámetros de la API dejan de pisarse en cada actualización.

`noupdate` se guarda por registro en ir_model_data: cambiar el XML a
noupdate="1" no alcanza para las bases donde el módulo ya estaba instalado. Va
en PRE para que la carga de datos de esta misma actualización ya los respete.

No se rota la clave acá: cambiarla en medio de un deploy cortaría a quien
consume la API sin aviso. Si todavía es la del repo, se avisa en el log.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE ir_model_data SET noupdate = true
         WHERE module = 'odoo_api_query'
           AND name IN ('param_api_key', 'param_max_page_size')
    """)
    cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'api_query.api_key'")
    fila = cr.fetchone()
    if fila and fila[0] == "123456789":
        _logger.warning(
            "odoo_api_query: la clave de la API es la del repositorio (123456789). "
            "Cambiarla en Ajustes > Técnico > Parámetros del sistema > api_query.api_key "
            "y avisar a quien consume la API.")
