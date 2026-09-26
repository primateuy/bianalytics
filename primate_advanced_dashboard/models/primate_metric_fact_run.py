# -*- coding: utf-8 -*-
"""Auditoría de las corridas de precálculo (sección 7)."""
import logging
from datetime import timedelta

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

# Días hacia atrás que recalcula el cron en cada corrida. Cubre correcciones
# retroactivas recientes sin barrer todo el histórico cada noche.
DEFAULT_LOOKBACK_DAYS = 7


class PrimateMetricFactRun(models.Model):
    _name = 'primate.metric.fact.run'
    _description = 'Corrida de precálculo de métricas'
    _order = 'create_date desc'

    name = fields.Char(string='Referencia', required=True, copy=False, readonly=True,
                       default=lambda self: _('Nueva corrida'))
    date_from = fields.Date(string='Desde', required=True, readonly=True)
    date_to = fields.Date(string='Hasta', required=True, readonly=True)
    origin = fields.Selection(
        [('cron', 'Cron'), ('manual', 'Manual'), ('backfill', 'Backfill')],
        string='Origen', required=True, default='manual', readonly=True)
    state = fields.Selection(
        [('running', 'En curso'), ('done', 'Terminada'), ('error', 'Con error')],
        string='Estado', default='running', required=True, readonly=True)
    version_ids = fields.Many2many(
        'primate.metric.version', string='Versiones procesadas', readonly=True)
    fact_count = fields.Integer(string='Hechos generados', readonly=True)
    duration = fields.Float(string='Duración (s)', readonly=True)
    user_id = fields.Many2one(
        'res.users', string='Lanzada por', ondelete='set null', readonly=True,
        default=lambda self: self.env.user)
    log = fields.Text(string='Detalle', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        """Numera la corrida con una secuencia legible."""
        for vals in vals_list:
            if vals.get('name', _('Nueva corrida')) == _('Nueva corrida'):
                vals['name'] = fields.Datetime.now().strftime('PAD/%Y%m%d/%H%M%S')
        return super().create(vals_list)

    @api.model
    def launch(self, versions, date_from, date_to, origin='manual'):
        """Ejecuta el precálculo dejando registro de la corrida y de su resultado."""
        started = fields.Datetime.now()
        run = self.create({
            'date_from': date_from,
            'date_to': date_to,
            'origin': origin,
            'version_ids': [(6, 0, versions.ids)],
        })
        try:
            count = self.env['primate.metric.fact'].rebuild(versions, date_from, date_to, run=run)
        except Exception as error:
            _logger.exception('Falló el precálculo de métricas')
            run.write({
                'state': 'error',
                'log': str(error),
                'duration': (fields.Datetime.now() - started).total_seconds(),
            })
            raise
        run.write({
            'state': 'done',
            'fact_count': count,
            'duration': (fields.Datetime.now() - started).total_seconds(),
            'log': _('%(versions)s versiones procesadas, %(facts)s hechos generados.') % {
                'versions': len(versions), 'facts': count},
        })
        return run

    @api.model
    def cron_build_facts(self, lookback_days=None):
        """Punto de entrada del cron diario de precálculo.

        Recalcula la ventana reciente de todas las versiones no archivadas. Las
        versiones de tipo ratio en modo "agregado y dividir" no guardan hechos
        propios, así que se saltean.
        """
        lookback_days = lookback_days or DEFAULT_LOOKBACK_DAYS
        today = fields.Date.context_today(self)
        date_from = today - timedelta(days=lookback_days)
        versions = self.env['primate.metric.version'].search([
            ('state', '!=', 'archived'),
        ]).filtered(lambda v: not (v.calc_type == 'ratio' and v.ratio_mode == 'aggregate_divide'))
        if not versions:
            _logger.info('Precálculo: no hay versiones de métrica para procesar')
            return False
        return self.launch(versions, date_from, today, origin='cron')
