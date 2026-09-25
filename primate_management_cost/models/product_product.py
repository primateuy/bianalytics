# -*- coding: utf-8 -*-
"""Costo de gestión del producto."""
import logging

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    management_cost = fields.Float(
        string='Costo de gestión', digits='Product Price',
        compute='_compute_management_cost',
        help='El costo en moneda de reportería (UCMR) llevado a pesos con el tipo de '
             'cambio de gestión. Es el costo con el que decide la empresa, no el '
             'contable ni el del mercado.')
    management_rate = fields.Float(
        string='TC de gestión', digits=(12, 6),
        compute='_compute_management_cost',
        help='Tipo de cambio de gestión vigente hoy.')

    @api.depends('ultimo_costo_mr')
    def _compute_management_cost(self):
        """Convierte el UCMR de cada producto al cambio de gestión de su compañía."""
        for product in self:
            company = product.company_id or self.env.company
            rate = company._get_management_rate()
            product.management_rate = rate
            product.management_cost = (product.ultimo_costo_mr or 0.0) * rate


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    management_cost = fields.Float(
        string='Costo de gestión', digits='Product Price',
        compute='_compute_management_cost',
        help='El costo en moneda de reportería (UCMR) llevado a pesos con el tipo de '
             'cambio de gestión.')

    @api.depends('ultimo_costo_mr')
    def _compute_management_cost(self):
        """Toma el costo de gestión de la primera variante, igual que hace el UCMR."""
        for template in self:
            variants = template.product_variant_ids
            template.management_cost = variants[:1].management_cost if variants else 0.0
