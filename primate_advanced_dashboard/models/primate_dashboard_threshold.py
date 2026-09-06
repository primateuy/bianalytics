# -*- coding: utf-8 -*-
"""Umbrales configurables para semáforos e indicadores (sección 9)."""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PrimateDashboardThreshold(models.Model):
    _name = 'primate.dashboard.threshold'
    _description = 'Umbral de indicador'
    _order = 'component_id, sequence, id'

    component_id = fields.Many2one(
        'primate.dashboard.component', string='Componente', required=True,
        ondelete='cascade', index=True)
    name = fields.Char(string='Etiqueta', required=True, translate=True)
    sequence = fields.Integer(string='Secuencia', default=10)
    value_from = fields.Float(string='Desde', help='Vacío = sin límite inferior.')
    value_to = fields.Float(string='Hasta', help='Vacío = sin límite superior.')
    has_lower_bound = fields.Boolean(string='Tiene límite inferior', default=True)
    has_upper_bound = fields.Boolean(string='Tiene límite superior', default=True)
    state = fields.Selection(
        [('good', 'Favorable'), ('warning', 'Atención'), ('bad', 'Desfavorable')],
        string='Estado', required=True, default='warning')
    color = fields.Char(string='Color', help='Color CSS opcional; si está vacío usa el estado.')

    @api.constrains('value_from', 'value_to', 'has_lower_bound', 'has_upper_bound')
    def _check_bounds(self):
        """El rango tiene que ser coherente."""
        for threshold in self:
            if threshold.has_lower_bound and threshold.has_upper_bound and \
                    threshold.value_from > threshold.value_to:
                raise ValidationError(_(
                    'En el umbral "%s" el valor desde es mayor que el valor hasta.'
                ) % threshold.name)

    def matches(self, value):
        """Indica si el valor cae dentro del umbral."""
        self.ensure_one()
        if self.has_lower_bound and value < self.value_from:
            return False
        if self.has_upper_bound and value > self.value_to:
            return False
        return True
