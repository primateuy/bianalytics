# -*- coding: utf-8 -*-
"""Filtros globales del dashboard (sección 8)."""
import logging

from odoo import models, fields, _

_logger = logging.getLogger(__name__)


class PrimateDashboardFilter(models.Model):
    """Filtro global que afecta simultáneamente a la métrica actual, al período
    comparable, a los gráficos y a los rankings."""
    _name = 'primate.dashboard.filter'
    _description = 'Filtro de dashboard'

    name = fields.Char(string='Nombre', required=True, default=lambda self: _('Filtro'))
    period_type_id = fields.Many2one(
        'primate.period.type', string='Tipo de período', ondelete='restrict')
    date_from = fields.Date(string='Desde')
    date_to = fields.Date(string='Hasta')
    comparison_id = fields.Many2one(
        'primate.comparison', string='Comparativo', ondelete='set null')
    company_ids = fields.Many2many('res.company', string='Compañías')
    warehouse_ids = fields.Many2many('stock.warehouse', string='Locales')
    employee_ids = fields.Many2many('hr.employee', string='Vendedores')
    team_ids = fields.Many2many('crm.team', string='Equipos comerciales')
    categ_ids = fields.Many2many('product.category', string='Categorías')
    product_tmpl_ids = fields.Many2many('product.template', string='Productos base')
    product_ids = fields.Many2many('product.product', string='Variantes')

    def to_dict(self, overrides=None):
        """Traduce el filtro a la estructura que consume el motor.

        Acepta un recordset vacío (dashboard sin filtro por defecto) y overrides para
        que la capa visual cambie el filtro sin persistirlo.
        """
        overrides = overrides or {}
        keys = ('company_ids', 'warehouse_ids', 'employee_ids', 'team_ids',
                'categ_ids', 'product_tmpl_ids', 'product_ids')
        values = {key: [] for key in keys}
        if self:
            self.ensure_one()
            values = {key: self[key].ids for key in keys}
        for key in keys:
            if key in overrides:
                values[key] = overrides[key] or []
        return values
