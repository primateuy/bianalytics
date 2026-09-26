# -*- coding: utf-8 -*-
"""Dashboard: conjunto de componentes, filtros y layout (secciones 8 y 9)."""
import logging

from babel.dates import format_date

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class PrimateDashboard(models.Model):
    _name = 'primate.dashboard'
    _description = 'Dashboard'
    _order = 'sequence, name'

    name = fields.Char(string='Nombre', required=True, translate=True)
    code = fields.Char(string='Código', required=True, index=True, copy=False)
    sequence = fields.Integer(string='Secuencia', default=10)
    active = fields.Boolean(string='Activo', default=True)
    company_id = fields.Many2one(
        'res.company', string='Compañía', ondelete='cascade', index=True,
        help='Vacío = visible para todas las compañías.')
    description = fields.Text(string='Descripción')
    component_ids = fields.One2many(
        'primate.dashboard.component', 'dashboard_id', string='Componentes', copy=True)
    filter_id = fields.Many2one(
        'primate.dashboard.filter', string='Filtro por defecto', ondelete='set null', copy=True)
    component_count = fields.Integer(
        string='Cantidad de componentes', compute='_compute_component_count')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Ya existe un dashboard con ese código.'),
    ]

    @api.depends('component_ids')
    def _compute_component_count(self):
        for dashboard in self:
            dashboard.component_count = len(dashboard.component_ids)

    # ------------------------------------------------------------------
    # Opciones de la barra de filtros
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_options(self):
        """Catálogo de períodos y comparativos que puede elegir el usuario.

        La barra de filtros se arma con esto: la capa visual no conoce los códigos
        de período ni de comparación, solo pinta lo que sale de acá.
        """
        period_types = self.env['primate.period.type'].search([])
        comparisons = self.env['primate.comparison'].search([])
        return {
            'period_types': [
                {'id': period.id, 'code': period.code, 'name': period.name}
                for period in period_types
            ],
            'comparisons': [
                {'id': comparison.id, 'code': comparison.code, 'name': comparison.name}
                for comparison in comparisons
            ],
        }

    # ------------------------------------------------------------------
    # Payload
    # ------------------------------------------------------------------
    def get_dashboard_data(self, filter_values=None):
        """Devuelve el payload completo del dashboard, ya calculado.

        La capa visual solo pinta lo que sale de acá: no calcula, no filtra y no
        conoce el modelo de métricas. Es lo que permite reconstruir el frontend en
        una versión nueva de Odoo sin tocar el motor.

        ``filter_values`` admite, además de los filtros de dimensión, el período y
        el comparativo elegidos en pantalla: ``period_type_id``, ``period_offset``,
        ``date_from`` / ``date_to`` y ``comparison_id``.
        """
        self.ensure_one()
        filter_values = filter_values or {}
        dashboard_filter = self.filter_id
        period_type, date_from, date_to = self._resolve_period(
            dashboard_filter, filter_values)
        filters = dashboard_filter.to_dict(filter_values)
        comparison_override = self._resolve_comparison(dashboard_filter, filter_values)

        components = []
        for component in self.component_ids.sorted(lambda c: (c.sequence, c.id)):
            try:
                components.append(component.get_data(
                    date_from, date_to, filters, period_type,
                    comparison=comparison_override))
            except Exception as error:
                _logger.exception('Falló el componente %s del dashboard %s',
                                  component.display_name, self.code)
                components.append({
                    'id': component.id,
                    'name': component.name,
                    'component_type': component.component_type,
                    'error': str(error),
                })

        effective_comparison = (
            dashboard_filter.comparison_id if comparison_override is None
            else comparison_override)
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'date_from': fields.Date.to_string(date_from),
            'date_to': fields.Date.to_string(date_to),
            'period_type_id': period_type.id if period_type else False,
            'period_code': period_type.code if period_type else False,
            'period_offset': filter_values.get('period_offset') or 0,
            'period_label': self._period_label(period_type, date_from, date_to),
            'comparison_id': effective_comparison.id if effective_comparison else False,
            'components': components,
            'options': self.get_dashboard_options(),
        }

    # ------------------------------------------------------------------
    # Resolución de período y comparativo
    # ------------------------------------------------------------------
    @api.model
    def _resolve_period(self, dashboard_filter, filter_values=None):
        """Resuelve (tipo de período, desde, hasta) efectivos.

        Precedencia: lo que manda la pantalla pisa al filtro guardado, y un rango
        explícito pisa al tipo de período. El offset corre el período sobre el
        calendario y es lo que usa la navegación anterior/siguiente.
        """
        filter_values = filter_values or {}
        period_model = self.env['primate.period.type']

        if filter_values.get('period_type_id'):
            period_type = period_model.browse(filter_values['period_type_id'])
        elif dashboard_filter and dashboard_filter.period_type_id:
            period_type = dashboard_filter.period_type_id
        else:
            period_type = period_model.search([('code', '=', 'month')], limit=1)

        # Rango explícito: el usuario eligió fechas a mano (o el tipo es rango libre).
        date_from = filter_values.get('date_from')
        date_to = filter_values.get('date_to')
        if date_from and date_to:
            return period_type, fields.Date.to_date(date_from), fields.Date.to_date(date_to)

        # Sin rango en pantalla, el filtro guardado puede traer uno propio.
        if dashboard_filter and dashboard_filter.date_from and dashboard_filter.date_to \
                and not filter_values.get('period_type_id'):
            return period_type, dashboard_filter.date_from, dashboard_filter.date_to

        today = fields.Date.context_today(self)
        if not period_type or period_type.code == 'custom':
            # El rango libre no deriva de una fecha: se cae al mes en curso.
            month = period_model.search([('code', '=', 'month')], limit=1)
            if month:
                return period_type or month, *month.get_period(today)
            return period_type, today.replace(day=1), today

        date_from, date_to = period_type.get_period(today)
        offset = filter_values.get('period_offset') or 0
        if offset:
            date_from, date_to = period_type.shift(date_from, date_to, offset)
        return period_type, date_from, date_to

    @api.model
    def _resolve_comparison(self, dashboard_filter, filter_values=None):
        """Resuelve el comparativo global elegido en pantalla.

        Devuelve None cuando la pantalla no se pronunció, para que cada componente
        siga usando el comparativo con el que fue configurado. Un recordset vacío es
        un apagado explícito y silencia la comparación en todo el tablero.
        """
        filter_values = filter_values or {}
        if 'comparison_id' not in filter_values:
            return None
        comparison_id = filter_values.get('comparison_id')
        if not comparison_id:
            return self.env['primate.comparison']
        return self.env['primate.comparison'].browse(comparison_id)

    @api.model
    def _period_label(self, period_type, date_from, date_to):
        """Etiqueta legible del período, resuelta en Python.

        El formato de fecha depende del idioma, así que se arma acá y no en la capa
        visual, que no tiene por qué conocer el calendario ni el locale.
        """
        if not date_from or not date_to:
            return ''
        locale = (self.env.context.get('lang') or self.env.user.lang or 'es_UY')
        code = period_type.code if period_type else 'custom'

        def _fmt(value, pattern):
            try:
                return format_date(value, format=pattern, locale=locale)
            except Exception:
                return fields.Date.to_string(value)

        if code == 'day':
            return _fmt(date_from, 'd MMMM y').capitalize()
        if code == 'iso_week':
            iso_year, iso_week, _iso_day = date_from.isocalendar()
            return _('Semana %(week)s de %(year)s', week=iso_week, year=iso_year)
        if code == 'month':
            return _fmt(date_from, 'MMMM y').capitalize()
        if code == 'quarter':
            quarter = (date_from.month - 1) // 3 + 1
            return 'T%s %s' % (quarter, date_from.year)
        if code == 'year':
            return str(date_from.year)
        return '%s – %s' % (_fmt(date_from, 'dd/MM/y'), _fmt(date_to, 'dd/MM/y'))

    def action_open_dashboard(self):
        """Abre el dashboard en la vista OWL."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'primate_dashboard.view',
            'name': self.name,
            'params': {'dashboard_id': self.id},
        }
