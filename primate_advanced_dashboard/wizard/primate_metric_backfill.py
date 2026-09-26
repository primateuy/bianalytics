# -*- coding: utf-8 -*-
"""Wizard de recálculo histórico de la tabla de hechos (sección 7).

La estrategia de recálculo ante correcciones de datos históricos queda resuelta acá:
el cron cubre la ventana reciente y este wizard permite rehacer un rango arbitrario
cuando se corrige el pasado.
"""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PrimateMetricBackfill(models.TransientModel):
    _name = 'primate.metric.backfill'
    _description = 'Recálculo de métricas'

    date_from = fields.Date(string='Desde', required=True)
    date_to = fields.Date(
        string='Hasta', required=True, default=lambda self: fields.Date.context_today(self))
    scope = fields.Selection(
        [('all', 'Todas las métricas'), ('selected', 'Métricas seleccionadas')],
        string='Alcance', default='all', required=True)
    version_ids = fields.Many2many(
        'primate.metric.version', string='Versiones',
        domain="[('state', '!=', 'archived')]")

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        """El rango tiene que ser válido."""
        for wizard in self:
            if wizard.date_from > wizard.date_to:
                raise ValidationError(_(
                    'La fecha desde no puede ser posterior a la fecha hasta.'))

    def action_run(self):
        """Lanza el recálculo y abre la corrida resultante."""
        self.ensure_one()
        if self.scope == 'selected':
            versions = self.version_ids
        else:
            versions = self.env['primate.metric.version'].search([('state', '!=', 'archived')])
        versions = versions.filtered(
            lambda v: not (v.calc_type == 'ratio' and v.ratio_mode == 'aggregate_divide'))
        if not versions:
            raise UserError(_('No hay versiones de métrica para recalcular.'))
        run = self.env['primate.metric.fact.run'].launch(
            versions, self.date_from, self.date_to, origin='backfill')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'primate.metric.fact.run',
            'res_id': run.id,
            'view_mode': 'form',
            'target': 'current',
        }
