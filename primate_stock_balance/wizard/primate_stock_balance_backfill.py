# -*- coding: utf-8 -*-
"""Wizard de reconstrucción histórica de los saldos de stock."""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PrimateStockBalanceBackfill(models.TransientModel):
    _name = 'primate.stock.balance.backfill'
    _description = 'Reconstrucción de saldos de stock'

    date_from = fields.Date(string='Desde', required=True)
    date_to = fields.Date(
        string='Hasta', required=True, default=lambda self: fields.Date.context_today(self))
    rebuild_facts = fields.Boolean(
        string='Recalcular también los hechos', default=True,
        help='Rehace la tabla de hechos de las métricas que leen los saldos, para que '
             'el dashboard refleje la reconstrucción sin un segundo paso.')

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        """El rango tiene que ser válido."""
        for wizard in self:
            if wizard.date_from > wizard.date_to:
                raise ValidationError(_(
                    'La fecha desde no puede ser posterior a la fecha hasta.'))

    def action_run(self):
        """Reconstruye los saldos del rango y, si se pidió, recalcula los hechos."""
        self.ensure_one()
        balance_model = self.env['primate.stock.balance']
        cutoffs = balance_model.cutoff_dates(self.date_from, self.date_to)
        if not cutoffs:
            raise UserError(_(
                'El rango elegido no contiene ninguna fecha de corte. Con la cadencia '
                'semanal hace falta un rango de al menos una semana.'))
        rows = balance_model.rebuild(self.date_from, self.date_to)

        if self.rebuild_facts:
            versions = self.env['primate.metric.version'].search([
                ('state', '!=', 'archived'),
                ('source_model', '=', 'primate.stock.balance'),
            ])
            if versions:
                self.env['primate.metric.fact.run'].launch(
                    versions, cutoffs[0], cutoffs[-1], origin='backfill')

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'primate.stock.balance',
            'name': _('Saldos de stock'),
            'view_mode': 'tree,form',
            'domain': [('date', '>=', cutoffs[0]), ('date', '<=', cutoffs[-1])],
            'target': 'current',
            'context': {'rebuilt_rows': rows},
        }
