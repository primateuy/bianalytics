# -*- coding: utf-8 -*-
"""Motor de lectura y cálculo de métricas.

Único punto de entrada para obtener valores de métricas. Toda la lógica vive acá, en
Python, de modo que la capa visual sea reconstruible y la API de la Fase 3 pueda
exponer estas mismas operaciones sin duplicar cálculo (secciones 3.1 y 10).
"""
import logging
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Días que se acepta arrastrar el último saldo conocido cuando el período consultado
# no contiene ninguna fecha de corte. Acotado a propósito: sin tope, una tabla de saldos
# que dejó de alimentarse seguiría mostrando el último valor para siempre.
BALANCE_CARRY_PARAMETER = 'primate_advanced_dashboard.balance_carry_days'
DEFAULT_BALANCE_CARRY_DAYS = 10

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
        if version.measure_type == 'balance':
            return self._compute_balance_from_facts(
                version, date_from, date_to, dimension, filters, limit)
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
        return rows or self._empty_rows(column)

    @api.model
    def _compute_balance_from_facts(self, version, date_from, date_to, dimension=None,
                                    filters=None, limit=None):
        """Lee una medida de saldo, que no se acumula a lo largo del período.

        Sumar los hechos de un saldo daría el disparate de multiplicar la existencia por
        la cantidad de cortes del rango. Entre dimensiones, en cambio, el saldo sí se
        suma: el stock de dos locales es la suma de los dos.
        """
        column = dimension.fact_column if dimension else None
        domain, divisor = self._balance_domain(version, date_from, date_to, filters)
        if not domain:
            return self._empty_rows(column)

        groupby = [column] if column else []
        results = self.env['primate.metric.fact']._read_group(
            domain, groupby, ['numerator:sum', 'denominator:sum', 'value:sum'])

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
                'numerator': (numerator or 0.0) / divisor,
                'denominator': (denominator or 0.0) / divisor,
                'value': (value or 0.0) / divisor,
            })
        rows.sort(key=lambda row: row['value'], reverse=True)
        if limit:
            rows = rows[:limit]
        return rows or self._empty_rows(column)

    @api.model
    def _balance_domain(self, version, date_from, date_to, filters=None):
        """Dominio y divisor con los que se lee un saldo en un período.

        En saldo de cierre el dominio se reduce a la última fecha de corte del período
        y el divisor es uno. En saldo promedio abarca todos los cortes y el divisor es
        cuántos son, contados sobre la versión entera y no sobre el subconjunto
        filtrado: un local sin existencia ese día no tiene fila, y su aporte al promedio
        tiene que ser cero, no la ausencia del día.
        """
        if version.balance_mode == 'average':
            dates = self._balance_snapshot_dates(version, date_from, date_to)
            if not dates:
                return None, 0.0
            return (self._build_domain(version, dates[0], dates[-1], filters),
                    float(len(dates)))
        cutoff = self._resolve_balance_date(version, date_from, date_to)
        if not cutoff:
            return None, 0.0
        return self._build_domain(version, cutoff, cutoff, filters), 1.0

    @api.model
    def _balance_snapshot_dates(self, version, date_from, date_to):
        """Fechas de corte con hechos de esa versión dentro del período."""
        # La granularidad es obligatoria al agrupar por una fecha: sin ella el grupo
        # sale por mes y los cortes de un mismo mes se contarían como uno solo.
        results = self.env['primate.metric.fact']._read_group([
            ('metric_version_id', '=', version.id),
            ('date', '>=', fields.Date.to_date(date_from)),
            ('date', '<=', fields.Date.to_date(date_to)),
        ], ['date:day'], [])
        return sorted(result[0] for result in results)

    @api.model
    def _resolve_balance_date(self, version, date_from, date_to):
        """Fecha de corte que representa el cierre del período.

        Es la última que cae dentro del período. Si el período no contiene ninguna
        —una consulta de tres días con cortes semanales— se arrastra el último saldo
        conocido, pero solo hasta donde llega el parámetro de arrastre: pasado eso es
        preferible no mostrar nada a mostrar una existencia vieja como si fuera la de
        hoy.
        """
        fact_model = self.env['primate.metric.fact']
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        latest = fact_model.search([
            ('metric_version_id', '=', version.id),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
        ], order='date desc', limit=1)
        if latest:
            return latest.date
        carry = self._get_balance_carry_days()
        latest = fact_model.search([
            ('metric_version_id', '=', version.id),
            ('date', '>=', date_to - timedelta(days=carry)),
            ('date', '<', date_from),
        ], order='date desc', limit=1)
        return latest.date if latest else None

    @api.model
    def _get_balance_carry_days(self):
        """Días de arrastre configurados para los saldos."""
        parameter = self.env['ir.config_parameter'].sudo()
        try:
            return max(int(parameter.get_param(
                BALANCE_CARRY_PARAMETER, DEFAULT_BALANCE_CARRY_DAYS)), 0)
        except (TypeError, ValueError):
            return DEFAULT_BALANCE_CARRY_DAYS

    @api.model
    def _empty_rows(self, column):
        """Fila neutra de un desglose vacío, para no romper la capa visual."""
        if column:
            return []
        return [{'key': None, 'label': '', 'numerator': 0.0,
                 'denominator': 0.0, 'value': 0.0}]

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
        if version.measure_type == 'balance':
            domain, divisor = self._balance_domain(version, date_from, date_to, filters)
            if not domain:
                return []
        else:
            domain = self._build_domain(version, date_from, date_to, filters)
            divisor = 1.0
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
                'value': self._final_value(version, numerator, denominator, value) / divisor,
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
