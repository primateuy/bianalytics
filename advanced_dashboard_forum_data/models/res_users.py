# -*- coding: utf-8 -*-
"""El usuario de POS identifica la sucursal en FORUM."""
from odoo import models, fields


class ResUsers(models.Model):
    _inherit = 'res.users'

    # En el POS de FORUM hay un usuario por sucursal y el vendedor se loguea como
    # empleado dentro de la sesión. Por eso el local de una pos.order se resuelve por
    # su user_id y no por pos.config.warehouse_id, que apunta a los almacenes dummy
    # de cada compañía.
    pad_local_id = fields.Many2one(
        'stock.warehouse', string='Local (dashboards)', ondelete='set null', index=True,
        help='Local que representa este usuario en los dashboards.')
