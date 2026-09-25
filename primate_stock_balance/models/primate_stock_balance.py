# -*- coding: utf-8 -*-
"""Saldo de stock por fecha de corte, variante y almacén.

El stock es un saldo y no un flujo: stock.quant guarda la existencia de hoy y su
write_date dice cuándo se tocó el registro, no a qué fecha corresponde el saldo. Una
métrica que lea el quant por write_date produce una serie plana con un pico en el día
de la última escritura.

Acá el saldo histórico se reconstruye hacia atrás desde la existencia actual restando
los movimientos posteriores, que es el mismo mecanismo del parámetro to_date de
qty_available en el core (addons/stock/models/product.py).
"""
import logging
from collections import defaultdict
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)

# Cadencia de los cortes y día de la semana en el que caen los semanales.
CADENCE_PARAMETER = 'primate_stock_balance.cadence'
CUTOFF_WEEKDAY_PARAMETER = 'primate_stock_balance.cutoff_weekday'
CRON_CUTOFFS_PARAMETER = 'primate_stock_balance.cron_cutoffs'
DEFAULT_CADENCE = 'weekly'
DEFAULT_CUTOFF_WEEKDAY = 7  # Domingo, en numeración ISO.
DEFAULT_CRON_CUTOFFS = 2

# Lote de lectura de los movimientos, para no traer el histórico entero a memoria.
BATCH_SIZE = 20000


class PrimateStockBalance(models.Model):
    _name = 'primate.stock.balance'
    _description = 'Saldo de stock a una fecha de corte'
    _order = 'date desc, warehouse_id, product_id'
    _rec_name = 'product_id'

    date = fields.Date(
        string='Fecha de corte', required=True, index=True,
        help='Saldo al cierre de este día.')
    product_id = fields.Many2one(
        'product.product', string='Variante', required=True, ondelete='cascade', index=True)
    product_tmpl_id = fields.Many2one(
        'product.template', string='Producto base', related='product_id.product_tmpl_id',
        store=True, index=True)
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Local', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(
        'res.company', string='Compañía', required=True, ondelete='cascade', index=True,
        help='La compañía dueña del almacén. Para el stock el dueño es quien tiene la '
             'mercadería, no quien la factura.')
    quantity = fields.Float(
        string='Cantidad', digits='Product Unit of Measure',
        help='Unidades en la unidad de medida del producto.')

    _sql_constraints = [
        ('date_product_warehouse_uniq', 'unique(date, product_id, warehouse_id)',
         'Ya existe un saldo para esa variante, ese almacén y esa fecha de corte.'),
    ]

    def init(self):
        """Índice compuesto para la lectura típica: un corte y un almacén."""
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS primate_stock_balance_date_warehouse_idx
            ON primate_stock_balance (date, warehouse_id)
        """)

    # =========================================================================
    # Cadencia de los cortes
    # =========================================================================
    @api.model
    def _get_cadence(self):
        """Cadencia configurada. Semanal por defecto."""
        parameter = self.env['ir.config_parameter'].sudo()
        cadence = parameter.get_param(CADENCE_PARAMETER, DEFAULT_CADENCE)
        return cadence if cadence in ('daily', 'weekly') else DEFAULT_CADENCE

    @api.model
    def _get_cutoff_weekday(self):
        """Día ISO de la semana en el que cae el corte semanal (1 lunes, 7 domingo)."""
        parameter = self.env['ir.config_parameter'].sudo()
        try:
            weekday = int(parameter.get_param(
                CUTOFF_WEEKDAY_PARAMETER, DEFAULT_CUTOFF_WEEKDAY))
        except (TypeError, ValueError):
            return DEFAULT_CUTOFF_WEEKDAY
        return weekday if 1 <= weekday <= 7 else DEFAULT_CUTOFF_WEEKDAY

    @api.model
    def cutoff_dates(self, date_from, date_to):
        """Fechas de corte que caen dentro del rango, de la más vieja a la más nueva."""
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        if date_from > date_to:
            raise UserError(_('La fecha desde no puede ser posterior a la fecha hasta.'))
        if self._get_cadence() == 'daily':
            span = (date_to - date_from).days
            return [date_from + timedelta(days=offset) for offset in range(span + 1)]
        weekday = self._get_cutoff_weekday()
        # Primer corte: el primer día del rango que cae en el día de corte.
        offset = (weekday - date_from.isoweekday()) % 7
        current = date_from + timedelta(days=offset)
        cutoffs = []
        while current <= date_to:
            cutoffs.append(current)
            current += timedelta(days=7)
        return cutoffs

    # =========================================================================
    # Reconstrucción
    # =========================================================================
    @api.model
    def rebuild(self, date_from, date_to):
        """Reconstruye los saldos de todos los cortes del rango.

        Borra primero lo que hubiera en el rango, así la misma llamada sirve para el
        cron y para un backfill histórico.
        """
        cutoffs = self.cutoff_dates(date_from, date_to)
        if not cutoffs:
            _logger.info(
                'Saldos de stock [%s..%s]: el rango no contiene ninguna fecha de corte.',
                date_from, date_to)
            return 0

        self.search([('date', '>=', cutoffs[0]), ('date', '<=', cutoffs[-1])]).unlink()

        running = self._current_balances()
        deltas = self._movement_deltas(cutoffs[0])
        pending_days = sorted(deltas, reverse=True)
        index = 0
        rows = []
        warehouse_company = self._warehouse_company_map()

        for cutoff in reversed(cutoffs):
            # El saldo del corte es el de hoy menos todo lo que se movió después.
            while index < len(pending_days) and pending_days[index] > cutoff:
                for key, quantity in deltas[pending_days[index]].items():
                    running[key] = running.get(key, 0.0) - quantity
                index += 1
            for (product_id, warehouse_id), quantity in running.items():
                if float_is_zero(quantity, precision_digits=4):
                    continue
                company_id = warehouse_company.get(warehouse_id)
                if not company_id:
                    continue
                rows.append({
                    'date': cutoff,
                    'product_id': product_id,
                    'warehouse_id': warehouse_id,
                    'company_id': company_id,
                    'quantity': quantity,
                })

        # Se crea por lotes: un backfill largo puede dar decenas de miles de filas.
        for chunk_start in range(0, len(rows), BATCH_SIZE):
            self.create(rows[chunk_start:chunk_start + BATCH_SIZE])
        _logger.info(
            'Saldos de stock [%s..%s]: %s cortes, %s filas.',
            cutoffs[0], cutoffs[-1], len(cutoffs), len(rows))
        return len(rows)

    @api.model
    def _current_balances(self):
        """Existencia actual por variante y almacén, leída de los quants internos."""
        locations = self._internal_location_map()
        if not locations:
            return {}
        groups = self.env['stock.quant'].sudo()._read_group(
            [('location_id', 'in', list(locations))],
            ['product_id', 'location_id'],
            ['quantity:sum'])
        balances = defaultdict(float)
        for product, location, quantity in groups:
            warehouse_id = locations.get(location.id)
            if not warehouse_id:
                continue
            balances[(product.id, warehouse_id)] += quantity or 0.0
        return dict(balances)

    @api.model
    def _movement_deltas(self, oldest_cutoff):
        """Movimiento neto por día, variante y almacén, desde el corte más viejo.

        Devuelve {día: {(variante, almacén): cantidad}}. Un traslado entre dos
        ubicaciones internas del mismo almacén se cancela solo y no aporta nada.
        """
        locations = self._internal_location_map()
        if not locations:
            return {}
        # Margen de un día en el límite inferior: la fecha se guarda en UTC y el día
        # real se resuelve después en el huso de la compañía.
        floor = fields.Datetime.to_string(
            fields.Datetime.to_datetime(oldest_cutoff) - timedelta(days=1))
        move_lines = self.env['stock.move.line'].sudo().search([
            ('state', '=', 'done'),
            ('date', '>', floor),
            '|', ('location_id', 'in', list(locations)),
                 ('location_dest_id', 'in', list(locations)),
        ], order='id')

        fact_model = self.env['primate.metric.fact']
        deltas = defaultdict(lambda: defaultdict(float))
        for chunk_start in range(0, len(move_lines), BATCH_SIZE):
            chunk = move_lines[chunk_start:chunk_start + BATCH_SIZE]
            for line in chunk:
                day = self._resolve_day(line, fact_model)
                if not day or day <= oldest_cutoff:
                    continue
                quantity = line.quantity_product_uom
                if not quantity:
                    continue
                product_id = line.product_id.id
                source = locations.get(line.location_id.id)
                destination = locations.get(line.location_dest_id.id)
                if destination:
                    deltas[day][(product_id, destination)] += quantity
                if source:
                    deltas[day][(product_id, source)] -= quantity
            move_lines.invalidate_recordset()
        return {day: dict(values) for day, values in deltas.items()}

    @api.model
    def _resolve_day(self, move_line, fact_model):
        """Día del movimiento en el huso de su compañía.

        Usa el mismo criterio que el precálculo de hechos: nunca el huso del usuario
        que ejecuta, para que el resultado no dependa de quién corre la reconstrucción.
        """
        timezone = fact_model._get_timezone(move_line.company_id)
        local = fields.Datetime.context_timestamp(
            move_line.with_context(tz=timezone), move_line.date)
        return local.date()

    @api.model
    def _internal_location_map(self):
        """Ubicaciones internas que pertenecen a un almacén, mapeadas a su almacén."""
        locations = self.env['stock.location'].sudo().search_read(
            [('usage', '=', 'internal'), ('warehouse_id', '!=', False)],
            ['warehouse_id'])
        return {location['id']: location['warehouse_id'][0] for location in locations}

    @api.model
    def _warehouse_company_map(self):
        """Compañía dueña de cada almacén."""
        warehouses = self.env['stock.warehouse'].sudo().search_read([], ['company_id'])
        return {warehouse['id']: warehouse['company_id'][0]
                for warehouse in warehouses if warehouse['company_id']}

    # =========================================================================
    # Cron
    # =========================================================================
    @api.model
    def cron_build_balances(self):
        """Rehace los últimos cortes, para absorber correcciones retroactivas."""
        parameter = self.env['ir.config_parameter'].sudo()
        try:
            cutoffs = int(parameter.get_param(
                CRON_CUTOFFS_PARAMETER, DEFAULT_CRON_CUTOFFS))
        except (TypeError, ValueError):
            cutoffs = DEFAULT_CRON_CUTOFFS
        cutoffs = max(cutoffs, 1)
        today = fields.Date.context_today(self)
        span = cutoffs if self._get_cadence() == 'daily' else cutoffs * 7
        return self.rebuild(today - timedelta(days=span), today)
