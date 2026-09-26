# -*- coding: utf-8 -*-
"""Compañía comercial del local, que no siempre es la dueña del stock.

En un esquema de franquicias el almacén pertenece a la casa central —la mercadería es
suya hasta que se vende— pero la operación comercial la factura el franquiciado. Para
un árbol de objetivos comerciales el local tiene que colgar de QUIEN VENDE, no de
quien es dueño de la mercadería: si cuelga del dueño del stock, sus ventas se cuentan
dos veces, una en la rama de la casa central y otra en la del franquiciado.
"""
from odoo import models, fields, api


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    target_company_id = fields.Many2one(
        'res.company', string='Compañía comercial', ondelete='set null', index=True,
        compute='_compute_target_company_id', store=True, readonly=False,
        help='Compañía de la que depende este local a efectos de objetivos: la que '
             'factura sus ventas. Por defecto es la dueña del almacén, y se cambia '
             'cuando el local lo opera un franquiciado.')

    @api.depends('company_id')
    def _compute_target_company_id(self):
        """Por defecto la comercial es la dueña del almacén, y queda editable."""
        for warehouse in self:
            if not warehouse.target_company_id:
                warehouse.target_company_id = warehouse.company_id
