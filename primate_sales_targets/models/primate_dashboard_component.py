# -*- coding: utf-8 -*-
"""Componente de dashboard que muestra el avance de un conjunto de objetivos."""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PrimateDashboardComponent(models.Model):
    _inherit = 'primate.dashboard.component'

    component_type = fields.Selection(
        selection_add=[('target_progress', 'Avance de objetivos')],
        ondelete={'target_progress': 'cascade'})
    target_definition_id = fields.Many2one(
        'primate.target.definition', string='Definición de objetivo',
        ondelete='restrict',
        help='Objetivos que muestra el componente. Se listan los que se solapan con '
             'el período del dashboard.')

    @api.model
    def _metric_less_types(self):
        """El avance de objetivos lee objetivos, no una métrica suelta."""
        return super()._metric_less_types() + ['target_progress']

    @api.constrains('component_type', 'target_definition_id')
    def _check_target_definition(self):
        """Un componente de objetivos sin definición no tiene qué mostrar."""
        for component in self:
            if component.component_type == 'target_progress' \
                    and not component.target_definition_id:
                raise ValidationError(_(
                    'El componente "%s" necesita una definición de objetivo.'
                ) % component.name)

    def get_data(self, date_from, date_to, filters, period_type=None, comparison=None):
        """Agrega el payload del avance de objetivos.

        Los objetivos ya traen su valor actual precalculado, así que el componente
        solo los lee: no dispara un recálculo del motor al pintar el tablero.
        """
        self.ensure_one()
        if self.component_type != 'target_progress':
            return super().get_data(
                date_from, date_to, filters, period_type, comparison=comparison)

        definition = self.target_definition_id
        if not definition:
            return {
                'id': self.id,
                'name': self.name,
                'component_type': self.component_type,
                'error': _('El componente no tiene una definición de objetivo.'),
            }

        targets = self.env['primate.target'].search([
            ('definition_id', '=', definition.id),
            ('state', '!=', 'draft'),
            ('date_from', '<=', date_to),
            ('date_to', '>=', date_from),
        ], order='progress desc', limit=self.row_limit or None)

        return {
            'id': self.id,
            'name': self.name,
            'component_type': self.component_type,
            'colspan': self.colspan or 1,
            'unit_type': definition.unit_type,
            'digits': definition.digits,
            'metric_state': 'confirmed',
            'gap_ref': '',
            'direction': definition.direction,
            'rows': [{
                'id': target.id,
                'label': target._get_subject().display_name,
                'period': target.period_label,
                'value': target.current_value,
                'target': target.target_value,
                'progress': target.progress,
                'state': target.state,
            } for target in targets],
        }
