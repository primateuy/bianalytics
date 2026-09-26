# -*- coding: utf-8 -*-
"""Mapeo del punto de venta a su local."""
from odoo import models, fields


class PosConfig(models.Model):
    _inherit = 'pos.config'

    # Cada local tiene varias cajas. Se guarda el local explícitamente en lugar de
    # parsear el prefijo del nombre ("001 - GAUCHO - CAJA 1") en cada consulta.
    pad_local_id = fields.Many2one(
        'stock.warehouse', string='Local (dashboards)', ondelete='set null', index=True,
        help='Local físico donde está esta caja.')
