# -*- coding: utf-8 -*-
"""Pertenencia del empleado a una sucursal, para poder desagregar objetivos.

Odoo no relaciona hr.employee con stock.warehouse: el vendedor puede facturar en
cualquier local. Pero un árbol de objetivos necesita saber de qué sucursal cuelga
cada vendedor, así que esa pertenencia se declara explícitamente acá.
"""
from odoo import models, fields


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    target_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Sucursal de objetivos', ondelete='set null', index=True,
        help='Sucursal de la que depende este empleado a efectos de objetivos. Es la '
             'que se usa al desagregar la meta de un local entre sus vendedores; no '
             'restringe dónde puede vender.')
