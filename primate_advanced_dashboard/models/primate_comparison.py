# -*- coding: utf-8 -*-
"""Motor de comparativos dinámicos entre períodos (sección 6)."""
import logging

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class PrimateComparison(models.Model):
    """Regla que enfrenta una métrica en un período contra otro período.

    El usuario nunca configura las fechas del período comparable: las deriva esta
    regla a partir del período seleccionado y su tipo.
    """
    _name = 'primate.comparison'
    _description = 'Comparativo de período'
    _order = 'sequence, id'

    name = fields.Char(string='Nombre', required=True, translate=True)
    code = fields.Char(string='Código', required=True, index=True, copy=False)
    sequence = fields.Integer(string='Secuencia', default=10)
    active = fields.Boolean(string='Activo', default=True)
    mode = fields.Selection(
        [('prev_period', 'Período inmediatamente anterior'),
         ('same_period_last_year', 'Mismo período del año anterior'),
         ('ptd_last_year', 'Acumulado del período contra el año anterior')],
        string='Modo', required=True, default='same_period_last_year')
    period_type_id = fields.Many2one(
        'primate.period.type', string='Tipo de período', ondelete='restrict',
        help='Tipo de período con el que se corre el rango. Vacío = se usa el tipo '
             'del filtro del dashboard.')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Ya existe un comparativo con ese código.'),
    ]

    def resolve(self, date_from, date_to, period_type=None):
        """Devuelve (desde, hasta) del período comparable.

        period_type permite que un mismo comparativo ("mismo período del año anterior")
        se comporte distinto según el tipo de período activo del dashboard: por semana
        ISO compara semana contra semana, por mes compara mes contra mes.
        """
        self.ensure_one()
        period_type = period_type or self.period_type_id
        if not period_type:
            period_type = self.env['primate.period.type'].search([('code', '=', 'custom')], limit=1)
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        if self.mode == 'prev_period':
            return period_type.shift(date_from, date_to, -1)
        if self.mode == 'same_period_last_year':
            return period_type.shift_year(date_from, date_to, 1)
        if self.mode == 'ptd_last_year':
            # Acumulado a la fecha (MTD / YTD): se corre el rango completo un año atrás
            # conservando la cantidad de días transcurridos.
            return period_type.shift_year(date_from, date_to, 1)
        return date_from, date_to

    @api.model
    def compute_variation(self, current, comparable):
        """Calcula la variación absoluta y porcentual entre dos valores.

        Devuelve None en el porcentaje cuando el comparable es cero, para que la capa
        visual muestre "N/D" en lugar de un crecimiento infinito.
        """
        current = current or 0.0
        comparable = comparable or 0.0
        absolute = current - comparable
        percent = (absolute / comparable * 100.0) if comparable else None
        return {'absolute': absolute, 'percent': percent}
