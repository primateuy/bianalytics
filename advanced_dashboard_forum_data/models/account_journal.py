# -*- coding: utf-8 -*-
"""El diario de venta identifica la sucursal del lado contable."""
from odoo import models, fields


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    # Los diarios de venta de FORUM son V001..V046, uno por local. Este campo
    # reemplaza al código interno de sucursal que había agregado Studio para el
    # proveedor de BI anterior, que era redundante con el código del diario.
    pad_local_id = fields.Many2one(
        'stock.warehouse', string='Local (dashboards)', ondelete='set null', index=True,
        help='Local al que imputan los comprobantes de este diario. Vacío en los '
             'diarios que no corresponden a un local físico (web, mayorista, franquicias).')
