# -*- coding: utf-8 -*-
"""Componentes visuales del dashboard (sección 9).

El Heatmap día x franja horaria es una adición al catálogo original de la sección 9,
necesaria para el reporte R03 del catálogo de métricas de FORUM.
"""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

COMPONENT_TYPES = [
    ('kpi_card', 'KPI Card'),
    ('kpi_comparative', 'KPI comparativo'),
    ('ranking', 'Ranking'),
    ('table', 'Tabla'),
    ('indicator', 'Indicador'),
    ('heatmap', 'Heatmap'),
]

# Componentes que necesitan una dimensión de desglose para tener sentido.
NEEDS_DIMENSION = ('ranking', 'table', 'heatmap')


class PrimateDashboardComponent(models.Model):
    _name = 'primate.dashboard.component'
    _description = 'Componente de dashboard'
    _order = 'dashboard_id, sequence, id'

    dashboard_id = fields.Many2one(
        'primate.dashboard', string='Dashboard', required=True, ondelete='cascade', index=True)
    name = fields.Char(string='Título', required=True, translate=True)
    sequence = fields.Integer(string='Secuencia', default=10)
    component_type = fields.Selection(
        COMPONENT_TYPES, string='Tipo', required=True, default='kpi_card')
    metric_id = fields.Many2one(
        'primate.metric', string='Métrica', ondelete='restrict',
        help='Se resuelve a la versión vigente de la compañía activa.')
    metric_version_id = fields.Many2one(
        'primate.metric.version', string='Versión fija', ondelete='restrict',
        help='Fija una versión concreta. Si se deja vacío, el componente sigue la '
             'versión vigente de la métrica para la compañía activa.')
    comparison_id = fields.Many2one(
        'primate.comparison', string='Comparativo', ondelete='set null')
    dimension_id = fields.Many2one(
        'primate.metric.dimension', string='Dimensión', ondelete='restrict')
    column_dimension_id = fields.Many2one(
        'primate.metric.dimension', string='Dimensión de columna', ondelete='restrict',
        help='Segunda dimensión, solo para el heatmap.')
    row_limit = fields.Integer(
        string='Cantidad de filas', default=10,
        help='Tope de filas del ranking o de la tabla. 0 = sin tope.')
    colspan = fields.Integer(string='Ancho', default=1, help='Columnas de la grilla que ocupa.')
    show_share = fields.Boolean(
        string='Mostrar participación', default=False,
        help='Agrega la participación porcentual de cada fila sobre el total del desglose. '
             'Es la "Participación (%)" del catálogo: no es una métrica aparte sino una '
             'lectura de la misma métrica dentro del corte.')
    threshold_ids = fields.One2many(
        'primate.dashboard.threshold', 'component_id', string='Umbrales', copy=True)

    @api.model
    def _metric_less_types(self):
        """Tipos de componente que no se alimentan de una métrica suelta.

        Un módulo que agregue un componente con otra fuente de datos suma acá su tipo
        en lugar de tener que redefinir la validación entera.
        """
        return []

    @api.constrains('component_type', 'dimension_id', 'column_dimension_id',
                    'metric_id', 'metric_version_id')
    def _check_component(self):
        """Valida que el componente tenga lo que su tipo necesita."""
        metric_less = self._metric_less_types()
        for component in self:
            if component.component_type in metric_less:
                continue
            if not (component.metric_id or component.metric_version_id):
                raise ValidationError(_(
                    'El componente "%s" necesita una métrica.') % component.name)
            if component.component_type in NEEDS_DIMENSION and not component.dimension_id:
                raise ValidationError(_(
                    'El componente "%s" es de tipo %s y necesita una dimensión de desglose.'
                ) % (component.name, component.component_type))
            if component.component_type == 'heatmap' and not component.column_dimension_id:
                raise ValidationError(_(
                    'El heatmap "%s" necesita una segunda dimensión para las columnas.'
                ) % component.name)
            if component.dimension_id and component.column_dimension_id and \
                    component.dimension_id.fact_column == component.column_dimension_id.fact_column:
                raise ValidationError(_(
                    'Las dos dimensiones del componente "%s" usan la misma columna de la '
                    'tabla de hechos y no pueden cruzarse.') % component.name)

    @api.depends('name', 'dashboard_id.name')
    def _compute_display_name(self):
        for component in self:
            component.display_name = '%s / %s' % (
                component.dashboard_id.name or '', component.name or '')

    def _get_version(self):
        """Resuelve la versión de métrica que usa el componente.

        Una versión fija tiene prioridad: es lo que hace que un cambio de versión de
        la métrica no altere en silencio un dashboard ya construido (sección 5.3).
        """
        self.ensure_one()
        if self.metric_version_id:
            return self.metric_version_id
        return self.metric_id.get_version(self.env.company)

    def _invalid_dimension(self, version):
        """Devuelve la primera dimensión pedida que la versión no declara admitir.

        Si la versión no declara ninguna dimensión no se valida nada: un catálogo
        todavía sin dimensiones cargadas no debería bloquear el tablero.
        """
        self.ensure_one()
        allowed = version.dimension_ids
        if not allowed:
            return self.env['primate.metric.dimension']
        for dimension in (self.dimension_id, self.column_dimension_id):
            if dimension and dimension not in allowed:
                return dimension
        return self.env['primate.metric.dimension']

    def get_data(self, date_from, date_to, filters, period_type=None,
                 comparison=None):
        """Devuelve el payload ya calculado del componente.

        ``comparison`` es el comparativo elegido en la barra de filtros: pisa al
        del componente para que todo el tablero compare contra lo mismo. En None
        cada componente conserva el suyo; en recordset vacío la comparación se
        apaga.
        """
        effective_comparison = (
            self.comparison_id if comparison is None else comparison)
        self.ensure_one()
        version = self._get_version()
        if not version:
            return {
                'id': self.id,
                'name': self.name,
                'component_type': self.component_type,
                'error': _('La métrica no tiene ninguna versión aplicable.'),
            }
        # Un desglose que la métrica no admite devolvía ceros en silencio: es el caso
        # del ticket promedio por vendedor, donde la boleta vive en la orden y el
        # vendedor en la línea. Vale más un aviso visible que una tabla de ceros.
        invalid = self._invalid_dimension(version)
        if invalid:
            return {
                'id': self.id,
                'name': self.name,
                'component_type': self.component_type,
                'error': _(
                    'La métrica "%(metric)s" no admite el desglose por "%(dimension)s".'
                ) % {'metric': version.metric_id.name, 'dimension': invalid.name},
            }

        engine = self.env['primate.metric.engine']
        payload = {
            'id': self.id,
            'name': self.name,
            'component_type': self.component_type,
            'colspan': self.colspan or 1,
            'unit_type': version.metric_id.unit_type,
            'digits': version.metric_id.digits,
            'metric_state': version.state,
            'gap_ref': version.gap_ref or '',
        }

        if self.component_type == 'heatmap':
            payload['cells'] = engine.compute_matrix(
                version, date_from, date_to, self.dimension_id,
                self.column_dimension_id, filters)
            payload['row_label'] = self.dimension_id.name
            payload['column_label'] = self.column_dimension_id.name
            return payload

        limit = self.row_limit if self.component_type in ('ranking', 'table') else None
        result = engine.compute_with_comparison(
            version, date_from, date_to, effective_comparison,
            dimension=self.dimension_id or None, filters=filters,
            period_type=period_type, limit=limit or None)
        if self.show_share:
            self._add_share(result['current'])
        payload.update({
            'show_share': self.show_share,
            'rows': result['current'],
            'comparable_from': fields.Date.to_string(result['comparable_from'])
            if result['comparable_from'] else False,
            'comparable_to': fields.Date.to_string(result['comparable_to'])
            if result['comparable_to'] else False,
            'has_comparison': bool(effective_comparison),
            'comparison_name': effective_comparison.name or '',
        })
        if self.component_type == 'indicator' and payload['rows']:
            payload['threshold'] = self._evaluate_thresholds(payload['rows'][0]['value'])
        return payload

    @api.model
    def _add_share(self, rows):
        """Agrega a cada fila su participación sobre el total del desglose.

        Se calcula sobre el total de las filas devueltas, así que con un tope de filas
        la participación es sobre lo mostrado, no sobre el universo.
        """
        total = sum(row['value'] for row in rows)
        for row in rows:
            row['share'] = (row['value'] / total * 100.0) if total else None
        return rows

    def _evaluate_thresholds(self, value):
        """Evalúa los umbrales configurados y devuelve el primero que aplica."""
        self.ensure_one()
        for threshold in self.threshold_ids.sorted(lambda t: t.sequence):
            if threshold.matches(value):
                return {
                    'name': threshold.name,
                    'color': threshold.color,
                    'state': threshold.state,
                }
        return {}
