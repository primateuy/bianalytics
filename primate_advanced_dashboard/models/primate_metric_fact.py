# -*- coding: utf-8 -*-
"""Tabla de hechos precalculada y su motor de construcción (sección 7)."""
import logging
from collections import defaultdict

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

from .primate_metric_dimension import COMPUTED_COLUMNS

_logger = logging.getLogger(__name__)

# Tamaño de lote para recorrer los registros transaccionales sin agotar memoria.
BATCH_SIZE = 5000

# Huso horario de respaldo cuando la compañía no tiene uno definido. Nunca se usa el
# del usuario que ejecuta: el resultado del precálculo no puede depender de quién
# corre el cron.
TIMEZONE_PARAMETER = 'primate_advanced_dashboard.default_timezone'
FALLBACK_TIMEZONE = 'UTC'


class PrimateMetricFact(models.Model):
    """Agregado diario de una métrica por combinación de dimensiones.

    Los dashboards y, más adelante, Sagui leen siempre de acá y nunca de los modelos
    transaccionales. El grano es diario desde la Fase 1.
    """
    _name = 'primate.metric.fact'
    _description = 'Hecho precalculado de métrica'
    _order = 'date desc, id'
    _rec_name = 'metric_version_id'

    metric_version_id = fields.Many2one(
        'primate.metric.version', string='Versión de métrica', required=True,
        ondelete='cascade', index=True)
    date = fields.Date(string='Fecha', required=True, index=True)
    run_id = fields.Many2one(
        'primate.metric.fact.run', string='Corrida', ondelete='set null', index=True)

    # --- Columnas de dimensión (ver FACT_COLUMNS en primate_metric_dimension) ----
    company_id = fields.Many2one('res.company', string='Compañía', ondelete='cascade', index=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Local', ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', string='Vendedor', ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', string='Usuario', ondelete='cascade', index=True)
    team_id = fields.Many2one('crm.team', string='Equipo comercial', ondelete='cascade', index=True)
    categ_id = fields.Many2one(
        'product.category', string='Categoría de producto', ondelete='cascade', index=True)
    categ_parent_id = fields.Many2one(
        'product.category', string='Familia', ondelete='cascade', index=True,
        help='Categoría padre, para que familia y subfamilia se puedan cruzar.')
    product_tmpl_id = fields.Many2one(
        'product.template', string='Producto base', ondelete='cascade', index=True)
    product_id = fields.Many2one(
        'product.product', string='Variante de producto', ondelete='cascade', index=True)
    hour_slot = fields.Integer(string='Franja horaria', index=True)
    weekday = fields.Integer(string='Día de la semana', index=True)

    # --- Valores -----------------------------------------------------------------
    numerator = fields.Float(string='Numerador', digits=(16, 4))
    denominator = fields.Float(string='Denominador', digits=(16, 4))
    value = fields.Float(string='Valor', digits=(16, 4), index=True)

    def init(self):
        """Índice compuesto para la lectura típica: una métrica en un rango de fechas."""
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS primate_metric_fact_version_date_idx
            ON primate_metric_fact (metric_version_id, date)
        """)

    # =========================================================================
    # Construcción
    # =========================================================================
    @api.model
    def rebuild(self, versions, date_from, date_to, run=None):
        """Reconstruye los hechos de las versiones dadas en el rango de fechas.

        Borra primero los hechos existentes del rango para no duplicar, así la misma
        llamada sirve para el cron incremental y para un backfill histórico.
        """
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        if date_from > date_to:
            raise UserError(_('La fecha desde no puede ser posterior a la fecha hasta.'))
        self = self.with_context(pad_timezone_cache={})
        total = 0
        for version in versions:
            if version.state == 'archived':
                continue
            self.search([
                ('metric_version_id', '=', version.id),
                ('date', '>=', date_from),
                ('date', '<=', date_to),
            ]).unlink()
            rows = self._build_version(version, date_from, date_to)
            if rows:
                for row in rows:
                    row['run_id'] = run.id if run else False
                self.create(rows)
                total += len(rows)
            _logger.info(
                'Precálculo %s [%s..%s]: %s hechos',
                version.display_name, date_from, date_to, len(rows))
        return total

    @api.model
    def _build_version(self, version, date_from, date_to):
        """Devuelve la lista de valores de hecho para una versión y rango."""
        if version.calc_type == 'ratio' and version.ratio_mode == 'aggregate_divide':
            # No guarda hechos propios: se resuelve en lectura dividiendo los agregados
            # de numerador y denominador (sección 5.1).
            return []
        if version.calc_type == 'ratio':
            return self._build_ratio_rows(version, date_from, date_to)
        return self._build_simple_rows(version, date_from, date_to)

    @api.model
    def _get_source_records(self, version, date_from, date_to):
        """Busca los registros transaccionales del rango, aplicando dominio y devoluciones."""
        model = self.env[version.source_model].with_context(active_test=False)
        domain = safe_eval(version.domain or '[]')
        domain = list(domain) + version.get_refund_domain()
        date_field = version.date_field
        field = self._get_field_by_path(model, date_field)
        if not field:
            raise UserError(_(
                'El campo de fecha "%s" no existe en %s.') % (date_field, version.source_model))
        if field.type == 'datetime':
            # El rango se acota con margen de un día y el día exacto se resuelve
            # después en el huso de la compañía.
            domain += [(date_field, '>=', fields.Date.to_string(date_from) + ' 00:00:00'),
                       (date_field, '<=', fields.Date.to_string(date_to) + ' 23:59:59')]
        else:
            domain += [(date_field, '>=', date_from), (date_field, '<=', date_to)]
        return model.search(domain)

    @api.model
    def _get_active_dimensions(self, version):
        """Dimensiones de la versión que su modelo origen sabe resolver."""
        dimensions = []
        for dimension in version.dimension_ids:
            if dimension.fact_column in COMPUTED_COLUMNS:
                dimensions.append((dimension, False))
                continue
            path = dimension.get_path(version.source_model)
            if path:
                dimensions.append((dimension, path))
            else:
                _logger.debug(
                    'La dimensión %s no tiene ruta desde %s; se omite en %s',
                    dimension.code, version.source_model, version.display_name)
        return dimensions

    @api.model
    def _build_simple_rows(self, version, date_from, date_to):
        """Agrega una métrica simple por día y combinación de dimensiones."""
        records = self._get_source_records(version, date_from, date_to)
        dimensions = self._get_active_dimensions(version)
        aggregation = version.aggregation
        value_field = version.value_field
        distinct_field = version.distinct_field

        buckets = defaultdict(lambda: {'num': 0.0, 'den': 0.0, 'distinct': set(),
                                       'min': None, 'max': None})
        for chunk_start in range(0, len(records), BATCH_SIZE):
            chunk = records[chunk_start:chunk_start + BATCH_SIZE]
            for record in chunk:
                day, hour = self._resolve_day_and_hour(record, version.date_field)
                if not day or day < date_from or day > date_to:
                    continue
                key = self._build_key(record, dimensions, day, hour)
                bucket = buckets[key]
                if aggregation == 'count':
                    bucket['num'] += 1.0
                    bucket['den'] += 1.0
                    continue
                if aggregation == 'count_distinct':
                    target = self._resolve_path(record, distinct_field)
                    if target is not None:
                        bucket['distinct'].add(target)
                    continue
                amount = self._resolve_path(record, value_field) or 0.0
                bucket['den'] += 1.0
                if aggregation == 'sum':
                    bucket['num'] += amount
                elif aggregation == 'avg':
                    bucket['num'] += amount
                elif aggregation == 'min':
                    bucket['min'] = amount if bucket['min'] is None else min(bucket['min'], amount)
                elif aggregation == 'max':
                    bucket['max'] = amount if bucket['max'] is None else max(bucket['max'], amount)
            records.invalidate_recordset()

        return [self._bucket_to_row(version, key, bucket, aggregation)
                for key, bucket in buckets.items()]

    @api.model
    def _build_ratio_rows(self, version, date_from, date_to):
        """Agrega un ratio en modo "promedio de filas".

        Exige que numerador y denominador compartan el modelo origen, porque el ratio
        se calcula fila a fila antes de promediar.
        """
        numerator = version.numerator_version_id
        denominator = version.denominator_version_id
        if numerator.source_model != denominator.source_model:
            raise UserError(_(
                'El ratio "%s" está configurado como promedio de filas, pero su numerador '
                'y su denominador salen de modelos distintos (%s y %s). Usá el modo '
                '"agregado y dividir".'
            ) % (version.display_name, numerator.source_model, denominator.source_model))

        records = self._get_source_records(numerator, date_from, date_to)
        dimensions = self._get_active_dimensions(numerator)
        buckets = defaultdict(lambda: {'num': 0.0, 'den': 0.0, 'distinct': set(),
                                       'min': None, 'max': None})
        for chunk_start in range(0, len(records), BATCH_SIZE):
            chunk = records[chunk_start:chunk_start + BATCH_SIZE]
            for record in chunk:
                day, hour = self._resolve_day_and_hour(record, numerator.date_field)
                if not day or day < date_from or day > date_to:
                    continue
                den_value = self._resolve_path(record, denominator.value_field) or 0.0
                if not den_value:
                    continue
                num_value = self._resolve_path(record, numerator.value_field) or 0.0
                key = self._build_key(record, dimensions, day, hour)
                buckets[key]['num'] += num_value / den_value
                buckets[key]['den'] += 1.0
            records.invalidate_recordset()

        return [self._bucket_to_row(version, key, bucket, 'avg')
                for key, bucket in buckets.items()]

    @api.model
    def _build_key(self, record, dimensions, day, hour):
        """Arma la clave del bucket: día más el valor de cada dimensión activa."""
        key = [('date', day)]
        for dimension, path in dimensions:
            column = dimension.fact_column
            if column == 'hour_slot':
                key.append((column, hour if hour is not None else 0))
            elif column == 'weekday':
                key.append((column, day.isoweekday()))
            else:
                key.append((column, self._resolve_path(record, path) or False))
        return tuple(key)

    @api.model
    def _bucket_to_row(self, version, key, bucket, aggregation):
        """Traduce un bucket acumulado a los valores de una fila de hecho."""
        row = dict(key)
        row['metric_version_id'] = version.id
        if aggregation == 'count_distinct':
            count = float(len(bucket['distinct']))
            row.update(numerator=count, denominator=count, value=count)
            return row
        if aggregation == 'min':
            value = bucket['min'] or 0.0
            row.update(numerator=value, denominator=bucket['den'], value=value)
            return row
        if aggregation == 'max':
            value = bucket['max'] or 0.0
            row.update(numerator=value, denominator=bucket['den'], value=value)
            return row
        numerator = bucket['num']
        denominator = bucket['den']
        if aggregation == 'avg':
            value = numerator / denominator if denominator else 0.0
        else:
            value = numerator
        row.update(numerator=numerator, denominator=denominator, value=value)
        return row

    @api.model
    def _get_field_by_path(self, model, path):
        """Devuelve el campo al final de una ruta separada por puntos.

        Permite que el campo de fecha de una métrica viva en un modelo relacionado,
        como order_id.date_order en las líneas de POS.
        """
        parts = (path or '').split('.')
        current = model
        for part in parts[:-1]:
            field = current._fields.get(part)
            if not field or not field.comodel_name:
                return None
            current = self.env[field.comodel_name]
        return current._fields.get(parts[-1])

    @api.model
    def _resolve_path(self, record, path):
        """Recorre una ruta separada por puntos y devuelve el id final o el valor.

        Devuelve None si la ruta se corta en un campo vacío, para que el hecho quede
        con la dimensión sin asignar en lugar de perderse.
        """
        if not path:
            return None
        current = record
        for part in path.split('.'):
            if current is None:
                return None
            if not isinstance(current, models.BaseModel):
                return None
            if not current:
                return None
            current = current[:1][part]
        if isinstance(current, models.BaseModel):
            return current[:1].id or None
        return current

    @api.model
    def _get_timezone(self, company):
        """Huso horario a usar para una compañía, de forma determinística.

        Orden: huso del partner de la compañía, luego el parámetro de sistema del
        módulo, luego UTC. Deliberadamente NO se considera el huso del usuario que
        ejecuta, porque el mismo precálculo tiene que dar el mismo resultado lo corra
        el cron, un backfill manual o un test.
        """
        cache = self.env.context.get('pad_timezone_cache')
        key = company.id if company else 0
        if cache is not None and key in cache:
            return cache[key]
        timezone = company.partner_id.tz if company else False
        if not timezone:
            timezone = self.env['ir.config_parameter'].sudo().get_param(
                TIMEZONE_PARAMETER, FALLBACK_TIMEZONE)
            if company:
                _logger.warning(
                    'La compañía "%s" no tiene huso horario configurado; el precálculo '
                    'usa %s. Definí el huso en la compañía o en el parámetro %s.',
                    company.name, timezone, TIMEZONE_PARAMETER)
        if cache is not None:
            cache[key] = timezone
        return timezone

    @api.model
    def _resolve_day_and_hour(self, record, date_field):
        """Devuelve (día, hora) del registro en el huso de su compañía.

        Es lo que evita que el heatmap por franja horaria salga corrido: las fechas
        datetime se guardan en UTC y Uruguay está tres horas atrás.
        """
        raw = self._resolve_path(record, date_field)
        if not raw:
            return None, None
        field = self._get_field_by_path(record, date_field)
        if not field:
            return None, None
        if field.type == 'date':
            return raw, None
        company = record.company_id if 'company_id' in record._fields else record.env.company
        timezone = self._get_timezone(company)
        local = fields.Datetime.context_timestamp(record.with_context(tz=timezone), raw)
        return local.date(), local.hour
