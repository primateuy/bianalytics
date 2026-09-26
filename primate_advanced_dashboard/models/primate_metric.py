# -*- coding: utf-8 -*-
"""Definición base de una métrica reutilizable (sección 5 de la especificación)."""
import logging

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

UNIT_TYPES = [
    ('count', 'Conteo'),
    ('qty', 'Cantidad'),
    ('money', 'Monetario'),
    ('percent', 'Porcentaje'),
    ('ratio', 'Ratio'),
]


class PrimateMetric(models.Model):
    """Concepto de negocio estable (ej. "Ventas totales").

    La definición base guarda solo el concepto: nombre, unidad y formato. El cómo se
    calcula vive en primate.metric.version, que además admite una versión distinta
    por compañía (sección 5.2).
    """
    _name = 'primate.metric'
    _description = 'Métrica'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(string='Nombre', required=True, translate=True, tracking=True)
    code = fields.Char(string='Código', required=True, index=True, copy=False, tracking=True)
    description = fields.Text(string='Descripción')
    active = fields.Boolean(string='Activo', default=True)
    unit_type = fields.Selection(
        UNIT_TYPES, string='Unidad de medida', required=True, default='qty', tracking=True)
    digits = fields.Integer(
        string='Decimales', default=2, help='Decimales con los que se formatea el valor.')
    display_factor = fields.Float(
        string='Factor de escala', default=1.0, digits=(16, 6), tracking=True,
        help='Multiplicador aplicado al valor calculado para llevarlo a la unidad en la '
             'que se lee la métrica. Un margen que sale como ratio 0-1 y se lee en '
             'porcentaje usa 100. Un descuento que ya viene 0-100 usa 1. Los umbrales '
             'se comparan contra el valor ya escalado.')
    version_ids = fields.One2many(
        'primate.metric.version', 'metric_id', string='Versiones', copy=False)
    version_count = fields.Integer(string='Cantidad de versiones', compute='_compute_version_count')
    draft_version_count = fields.Integer(
        string='Versiones en borrador', compute='_compute_version_count')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'El código de la métrica debe ser único.'),
    ]

    @api.depends('version_ids', 'version_ids.state')
    def _compute_version_count(self):
        for metric in self:
            versions = metric.version_ids
            metric.version_count = len(versions)
            metric.draft_version_count = len(versions.filtered(lambda v: v.state == 'draft'))

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for metric in self:
            metric.display_name = metric.name or metric.code or ''

    def get_version(self, company=None):
        """Resuelve la versión vigente de la métrica para una compañía.

        Prioriza la versión específica de la compañía sobre la base compartida
        (sección 5.2) y, dentro de cada grupo, la última confirmada. Si no hay
        ninguna confirmada devuelve la última en borrador, para que el catálogo
        provisorio de un cliente sea usable antes de cerrar sus gaps.
        """
        self.ensure_one()
        company = company or self.env.company
        versions = self.version_ids.filtered(lambda v: v.state != 'archived')
        for candidates in (versions.filtered(lambda v: v.company_id == company),
                           versions.filtered(lambda v: not v.company_id)):
            if not candidates:
                continue
            confirmed = candidates.filtered(lambda v: v.state == 'confirmed')
            pool = confirmed or candidates
            return pool.sorted(lambda v: v.version, reverse=True)[:1]
        return self.env['primate.metric.version']

    def action_view_versions(self):
        """Abre las versiones de la métrica."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Versiones de %s') % self.name,
            'res_model': 'primate.metric.version',
            'view_mode': 'tree,form',
            'domain': [('metric_id', '=', self.id)],
            'context': {'default_metric_id': self.id},
        }
