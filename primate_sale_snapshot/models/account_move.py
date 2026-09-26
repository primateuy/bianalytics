# -*- coding: utf-8 -*-
"""Congelado de la venta y datos del punto de venta en la factura.

Nada de esto se guarda en account.move.line. Es una tabla caliente, con validación de
cuadratura, conciliación y varios módulos de la localización escribiendo encima; un
satélite se escribe una vez, al publicar, y no se toca nunca más.
"""
import logging

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

# Tipos de asiento que representan una venta al cliente.
SALE_TYPES = ('out_invoice', 'out_refund')


class AccountMove(models.Model):
    _inherit = 'account.move'

    sale_snapshot_ids = fields.One2many(
        'primate.sale.snapshot', 'move_id', string='Congelado de la venta')
    sale_snapshot_payment_ids = fields.One2many(
        'primate.sale.snapshot.payment', 'move_id', string='Pagos del punto de venta')
    sale_snapshot_count = fields.Integer(
        string='Líneas congeladas', compute='_compute_sale_snapshot_count')

    # --- Cabezal del punto de venta -------------------------------------------
    # Se leen del congelado y no se guardan en la factura: escribir sobre un asiento ya
    # publicado choca con el sellado de la localización, y el dato congelado ya vive en
    # las líneas del snapshot.
    pos_session_id = fields.Many2one(
        'pos.session', string='Sesión de POS', compute='_compute_pos_snapshot_header')
    pos_config_id = fields.Many2one(
        'pos.config', string='Caja', compute='_compute_pos_snapshot_header')
    pos_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Local', compute='_compute_pos_snapshot_header')
    pos_sale_datetime = fields.Datetime(
        string='Fecha y hora de la venta', compute='_compute_pos_snapshot_header',
        help='El momento real de la venta. La factura guarda solo el día.')

    @api.depends('sale_snapshot_ids')
    def _compute_pos_snapshot_header(self):
        """El cabezal del punto de venta sale de la primera línea congelada."""
        for move in self:
            snapshot = move.sale_snapshot_ids[:1]
            move.pos_session_id = snapshot.session_id
            move.pos_config_id = snapshot.config_id
            move.pos_warehouse_id = snapshot.warehouse_id
            move.pos_sale_datetime = snapshot.sale_datetime

    def _compute_sale_snapshot_count(self):
        """Cuenta las líneas congeladas de cada factura."""
        data = self.env['primate.sale.snapshot']._read_group(
            [('move_id', 'in', self.ids)], ['move_id'], ['__count'])
        mapped = {move.id: count for move, count in data}
        for move in self:
            move.sale_snapshot_count = mapped.get(move.id, 0)

    # =========================================================================
    # Construcción
    # =========================================================================
    def _snapshot_pos_order(self):
        """Orden de punto de venta que originó la factura, si la hay."""
        self.ensure_one()
        orders = self.pos_order_ids if 'pos_order_ids' in self._fields else False
        return orders[:1] if orders else self.env['pos.order']

    def _snapshot_line_pairs(self, order):
        """Empareja cada línea de factura con su línea de punto de venta.

        El core arma las líneas de la factura recorriendo las del POS en orden y
        agregando notas en el medio, así que el emparejamiento es posicional sobre las
        líneas de producto. Si las cantidades no coinciden se congela igual, pero sin
        el enlace: es preferible perder la trazabilidad de una línea que perder la foto.
        """
        self.ensure_one()
        invoice_lines = self.invoice_line_ids.filtered(
            lambda line: line.display_type == 'product' and line.product_id)
        if not order:
            return [(line, self.env['pos.order.line']) for line in invoice_lines]
        pos_lines = order.lines.filtered(lambda line: line.product_id)
        if len(pos_lines) != len(invoice_lines):
            _logger.info(
                'La factura %s tiene %s líneas de producto y su orden de POS %s: se '
                'congela sin enlazar línea a línea.',
                self.name, len(invoice_lines), len(pos_lines))
            return [(line, self.env['pos.order.line']) for line in invoice_lines]
        return list(zip(invoice_lines, pos_lines))

    def _build_sale_snapshot(self):
        """Congela las líneas de venta de cada factura publicada."""
        snapshot_model = self.env['primate.sale.snapshot'].sudo()
        payment_model = self.env['primate.sale.snapshot.payment'].sudo()
        for move in self:
            if move.move_type not in SALE_TYPES:
                continue
            if move.sale_snapshot_ids:
                continue
            order = move._snapshot_pos_order()
            company = move.company_id
            date = move.invoice_date or move.date or fields.Date.context_today(move)
            warehouse = order._snapshot_warehouse() if order else False
            sale_datetime = order.date_order if order else False

            pares = move._snapshot_line_pairs(order)

            # El congelado es por LINEA DE POS, no por factura: la constraint
            # pos_line_uniq es sobre pos_order_line_id. Una misma orden puede
            # terminar facturada dos veces —una anulacion y su reemplazo, o un
            # reintento del POS despues de un error—, y la segunda factura no
            # tiene snapshots propios, asi que la guarda de arriba no la frena.
            # Las lineas ya congeladas se saltean: el snapshot describe la venta,
            # no el comprobante, y volver a congelarla no agregaria informacion.
            ya_congeladas = set()
            pos_ids = [pl.id for _il, pl in pares if pl]
            if pos_ids:
                ya_congeladas = set(snapshot_model.search([
                    ('pos_order_line_id', 'in', pos_ids),
                ]).mapped('pos_order_line_id').ids)
                if ya_congeladas:
                    _logger.info(
                        'La factura %s tiene %s lineas de POS ya congeladas: se '
                        'saltean para no duplicar la venta.',
                        move.name, len(ya_congeladas))

            rows = []
            for invoice_line, pos_line in pares:
                if pos_line and pos_line.id in ya_congeladas:
                    continue
                product = invoice_line.product_id
                values = snapshot_model._product_values(product, company, date)
                employee = (order._snapshot_line_employee(pos_line)
                            if order and pos_line else False)
                quantity = invoice_line.quantity
                values.update({
                    'move_id': move.id,
                    'move_line_id': invoice_line.id,
                    'pos_order_id': order.id if order else False,
                    'pos_order_line_id': pos_line.id if pos_line else False,
                    'company_id': company.id,
                    'warehouse_id': warehouse.id if warehouse else False,
                    'employee_id': employee.id if employee else False,
                    'session_id': order.session_id.id if order else False,
                    'config_id': order.config_id.id if order else False,
                    'sale_datetime': sale_datetime or fields.Datetime.to_datetime(date),
                    'sale_date': date,
                    'quantity': quantity,
                    'price_unit': invoice_line.price_unit,
                    'discount': invoice_line.discount,
                    'price_subtotal': invoice_line.price_subtotal,
                    'currency_id': move.currency_id.id,
                    'management_value': (values['management_cost'] or 0.0) * quantity,
                })
                rows.append(values)
            if rows:
                snapshot_model.create(rows)
            if order:
                payment_model.create([{
                    'move_id': move.id,
                    'pos_order_id': order.id,
                    'payment_method_id': payment.payment_method_id.id,
                    'payment_method_name': payment.payment_method_id.display_name,
                    'amount': payment.amount,
                    'currency_id': payment.currency_id.id,
                    'payment_date': payment.payment_date,
                } for payment in order.payment_ids])

    def _post(self, soft=True):
        """Congela al publicar: publicada es cuando la venta es un hecho."""
        posted = super()._post(soft=soft)
        # El savepoint NO es opcional. Atrapar un error de psycopg2 sin el deja la
        # transaccion abortada, y todo lo que venga despues falla con
        # InFailedSqlTransaction — el que publica la factura se lleva un error que
        # no tiene nada que ver. Con savepoint, el fallo del congelado se revierte
        # solo y la transaccion sigue usable.
        try:
            with self.env.cr.savepoint():
                posted._build_sale_snapshot()
        except Exception:  # noqa: BLE001 - congelar no puede impedir publicar
            _logger.exception(
                'No se pudo congelar la venta de las facturas %s', posted.ids)
        return posted

    def action_view_sale_snapshot(self):
        """Abre el congelado de esta factura."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Congelado de la venta'),
            'res_model': 'primate.sale.snapshot',
            'view_mode': 'tree,form',
            'domain': [('move_id', '=', self.id)],
        }
