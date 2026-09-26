# -*- coding: utf-8 -*-
"""Archiva la v1 de Stock disponible, que leía stock.quant por write_date.

Los datos del módulo son noupdate, así que la v1 ya instalada no cambia sola de estado
al actualizar: la v2 se crea, pero la v1 quedaría en borrador y el precálculo seguiría
recorriéndola para producir una serie que ya se sabe que no significa nada.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Deja la v1 archivada si la v2 ya está en su lugar."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    v1 = env.ref('advanced_dashboard_forum_data.version_stock_disponible',
                 raise_if_not_found=False)
    v2 = env.ref('advanced_dashboard_forum_data.version_stock_disponible_v2',
                 raise_if_not_found=False)
    if not v1 or not v2:
        return
    if v1.state != 'archived':
        v1.state = 'archived'
        _logger.info(
            'Stock disponible v1 archivada: la reemplaza la v2 sobre la tabla de saldos.')
    # Los hechos de la v1 describen una serie que no representa el saldo de cada fecha.
    facts = env['primate.metric.fact'].search([('metric_version_id', '=', v1.id)])
    if facts:
        count = len(facts)
        facts.unlink()
        _logger.info('Borrados %s hechos de la v1 de Stock disponible.', count)
