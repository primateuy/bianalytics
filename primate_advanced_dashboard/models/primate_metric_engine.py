# -*- coding: utf-8 -*-
"""Motor de lectura y cálculo de métricas.

Único punto de entrada para obtener valores de métricas. Toda la lógica vive acá, en
Python, de modo que la capa visual sea reconstruible y la API de la Fase 3 pueda
exponer estas mismas operaciones sin duplicar cálculo (secciones 3.1 y 10).
"""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Traducción de las claves de filtro a la columna de la tabla de hechos.
FILTER_COLUMNS = {
    'company_ids': 'company_id',
    'warehouse_ids': 'warehouse_id',
    'employee_ids': 'employee_id',
    'user_ids': 'user_id',
    'team_ids': 'team_id',
    'categ_ids': 'categ_id',
    'categ_parent_ids': 'categ_parent_id',
    'product_tmpl_ids': 'product_tmpl_id',
    'product_ids': 'product_id',
}


class PrimateMetricEngine(models.AbstractModel):
    _name = 'primate.metric.engine'
    _description = 'Motor de cálculo de métricas'

    # =========================================================================
    # Lectura de métricas
    # =========================================================================
    @api.model
    def compute(self, version, date_from, date_to, dimension=None, filters=None, limit=None):
        """Calcula una métrica en un rango, opcionalmente desglosada por dimensión.

        Devuelve una lista de diccionarios con la clave de dimensión, su etiqueta y el
        valor. Sin dimensión devuelve una única fila con el total del rango.
        """
        version.ensure_one()
        if version.calc_type == 'ratio' and version.ratio_mode == 'aggregate_divide':
            rows = self._compute_ratio(version, date_from, date_to, dimension, filters, limit)
        else:
            rows = self._compute_from_facts(
                version, date_from, date_to, dimension, filters, limit)
        return self._apply_display_factor(version, rows)

    @api.model
    def _apply_display_factor(self, version, rows):
        """Lleva el valor a la unidad en la que se lee la métrica.

        Se aplica una sola vez, acá, para que los umbrales y la capa visual trabajen
        siempre con el valor ya escalado y no cada uno con su propia conversión.
        """
        factor = version.metric_id.display_factor or 1.0
        if factor == 1.0:
            return rows
        for row in rows:
            row['value'] = row['value'] * factor
        return rows

    @api.model
    def _compute_from_facts(self, version, date_from, date_to, dimension=None,
                            filters=None, limit=None):
        """Agrega la tabla de hechos de una versión que sí guarda hechos propios."""
        domain = self._build_domain(version, date_from, date_to, filters)
        column = dimension.fact_column if dimension else None
        aggregates = ['numerator:sum', 'denominator:sum']
        if version.aggregation == 'min':
            aggregates.append('value:min')
        elif version.aggregation == 'max':
            aggregates.append('value:max')
        else:
            aggregates.append('value:sum')

        groupby = [column] if column else []
        results = self.env['primate.metric.fact']._read_group(domain, groupby, aggregates)

        rows = []
        for result in results:
            if column:
                key, numerator, denominator, value = result
            else:
                key = None
                numerator, denominator, value = result
            rows.append({
                'key': self._key_id(key),
                'label': self._key_label(key, column),
                'numerator': numerator or 0.0,
                'denominator': denominator or 0.0,
                'value': self._final_value(version, numerator, denominator, value),
            })
        rows.sort(key=lambda row: row['value'], reverse=True)
        if limit:
            rows = rows[:limit]
        if not rows and not column:
            rows = [{'key': None, 'label': '', 'numerator': 0.0,
                     'denominator': 0.0, 'value': 0.0}]
        return rows

    @api.model
    def _compute_ratio(self, version, date_from, date_to, dimension=None,
                       filters=None, limit=None):
        """Resuelve un ratio en modo "agregado y dividir" (sección 5.1).

        Agrega numerador y denominador por separado y divide al final, que es el
        criterio correcto al desglosar por dimensión o aplicar filtros.
        """
        numerator_rows = self._compute_from_facts(
            version.numerator_version_id, date_from, date_to, dimension, filters)
        denominator_rows = self._compute_from_facts(
            version.denominator_version_id, date_from, date_to, dimension, filters)
        denominators = {row['key']: row['value'] for row in denominator_rows}

        rows = []
        for row in numerator_rows:
            denominator = denominators.get(row['key']) or 0.0
            rows.append({
                'key': row['key'],
                'label': row['label'],
                'numerator': row['value'],
                'denominator': denominator,
                'value': (row['value'] / denominator) if denominator else 0.0,
            })
        rows.sort(key=lambda row: row['value'], reverse=True)
        if limit:
            rows = rows[:limit]
        if not rows and not dimension:
            rows = [{'key': None, 'label': '', 'numerator': 0.0,
                     'denominator': 0.0, 'value': 0.0}]
        return rows

    @api.model
    def compute_matrix(self, version, date_from, date_to, row_dimension,
                       column_dimension, filters=None):
        """Calcula una métrica cruzada por dos dimensiones.

        Es lo que necesita el heatmap de día x franja horaria: una celda por
        combinación, más los totales de fila y de columna.
        """
        version.ensure_one()
        if version.calc_type == 'ratio' and version.ratio_mode == 'aggregate_divide':
            raise UserError(_(
                'El componente cruzado todavía no soporta ratios en modo "agregado y '
                'dividir". Usá una métrica simple para el heatmap.'))
        domain = self._build_domain(version, date_from, date_to, filters)
        groupby = [row_dimension.fact_column, column_dimension.fact_column]
        results = self.env['primate.metric.fact']._read_group(
            domain, groupby, ['numerator:sum', 'denominator:sum', 'value:sum'])
        cells = []
        for row_key, column_key, numerator, denominator, value in results:
            cells.append({
                'row': self._key_id(row_key),
                'row_label': self._key_label(row_key, row_dimension.fact_column),
                'column': self._key_id(column_key),
                'column_label': self._key_label(column_key, column_dimension.fact_column),
                'value': self._final_value(version, numerator, denominator, value),
            })
        return self._apply_display_factor(version, cells)

    @api.model
    def compute_with_comparison(self, version, date_from, date_to, comparison,
                                dimension=None, filters=None, period_type=None, limit=None):
        """Calcula la métrica y su período comparable, con la variación entre ambos.

        El filtro afecta simultáneamente al período actual y al comparable, como pide
        la sección 8.
        """
        current = self.compute(version, date_from, date_to, dimension, filters, limit)
        if not comparison:
            return {'current': current, 'comparable': [], 'date_from': date_from,
                    'date_to': date_to, 'comparable_from': None, 'comparable_to': None}
        comparable_from, comparable_to = comparison.resolve(date_from, date_to, period_type)
        comparable = self.compute(version, comparable_from, comparable_to, dimension, filters)
        comparable_by_key = {row['key']: row['value'] for row in comparable}
        for row in current:
            variation = self.env['primate.comparison'].compute_variation(
                row['value'], comparable_by_key.get(row['key'], 0.0))
            row['comparable'] = comparable_by_key.get(row['key'], 0.0)
            row['variation'] = variation['absolute']
            row['variation_percent'] = variation['percent']
        return {
            'current': current,
            'comparable': comparable,
            'date_from': date_from,
            'date_to': date_to,
            'comparable_from': comparable_from,
            'comparable_to': comparable_to,
        }

    # =========================================================================
    # Auxiliares
    # =========================================================================
    @api.model
    def _build_domain(self, version, date_from, date_to, filters=None):
        """Dominio de lectura de hechos: versión, rango y filtros globales."""
        domain = [
            ('metric_version_id', '=', version.id),
            ('date', '>=', fields.Date.to_date(date_from)),
            ('date', '<=', fields.Date.to_date(date_to)),
        ]
        for key, column in FILTER_COLUMNS.items():
            values = (filters or {}).get(key)
            if values:
                domain.append((column, 'in', list(values)))
        extra = (filters or {}).get('domain')
        if extra:
            domain += list(extra)
        return domain

    @api.model
    def _final_value(self, version, numerator, denominator, value):
        """Aplica el modo de agregación al leer, no al guardar."""
        if version.aggregation == 'avg':
            return (numerator / denominator) if denominator else 0.0
        return value or 0.0

    @api.model
    def _key_id(self, key):
        """Normaliza la clave de agrupación a un id o valor simple."""
        if isinstance(key, models.BaseModel):
            return key.id or None
        return key

    @api.model
    def _key_label(self, key, column):
        """Etiqueta legible de la clave de agrupación.

        El nombre del valor de una dimensión se lee con sudo a propósito: quien tiene
        permiso de ver el dashboard tiene que poder leer las etiquetas del desglose
        aunque no pertenezca a los grupos de Inventario o de RRHH. Lo que sigue sujeto
        a los permisos del usuario es el acceso a la tabla de hechos y a los dashboards;
        acá solo se traduce un id que ya salió de esa lectura autorizada.
        """
        if key is None or key is False:
            return _('Sin asignar')
        if isinstance(key, models.BaseModel):
            return key.sudo().display_name or _('Sin asignar')
        if column == 'weekday':
            days = [_('Lunes'), _('Martes'), _('Miércoles'), _('Jueves'),
                    _('Viernes'), _('Sábado'), _('Domingo')]
            return days[int(key) - 1] if 1 <= int(key) <= 7 else str(key)
        if column == 'hour_slot':
            return '%02d:00' % int(key)
        return str(key)

    # =========================================================================
    # Superficie de operaciones (base de la API de la Fase 3, sección 10)
    # =========================================================================
    @api.model
    def get_available_metrics(self, company=None):
        """Lista las métricas disponibles con su versión vigente para la compañía."""
        company = company or self.env.company
        metrics = self.env['primate.metric'].search([])
        available = []
        for metric in metrics:
            version = metric.get_version(company)
            if not version:
                continue
            available.append({
                'metric_id': metric.id,
                'code': metric.code,
                'name': metric.name,
                'unit_type': metric.unit_type,
                'version_id': version.id,
                'version': version.version,
                'state': version.state,
                'gap_ref': version.gap_ref or '',
                'dimensions': version.dimension_ids.mapped('code'),
            })
        return available

    @api.model
    def create_metric(self, values, version_values=None):
        """Crea una métrica con su primera versión en borrador.

        Es la operación que la Fase 3 va a exponer para que un agente formalice una
        métrica nueva en lugar de calcular al vuelo (sección 23).
        """
        if not values.get('code'):
            raise UserError(_('La métrica necesita un código.'))
        metric = self.env['primate.metric'].create(values)
        if version_values:
            self.env['primate.metric.version'].create(
                dict(version_values, metric_id=metric.id))
        return metric
