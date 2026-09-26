# -*- coding: utf-8 -*-
"""Congelado de las ventas de punto de venta que no llegan a una factura.

En Uruguay cada venta emite un CFE, así que lo normal es que exista la factura. Pero lo
que no se factura solo llega al asiento de cierre de sesión, que agrupa por cuenta e
impuesto y pierde el producto: si no se congela acá, esa venta desaparece del detalle.
"""
import logging

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    sale_snapshot_ids = fields.One2many(
        'primate.sale.snapshot', 'pos_order_id', string='Congelado de la venta')
    sale_snapshot_count = fields.Integer(
        string='Líneas congeladas', compute='_compute_sale_snapshot_count')

    def _compute_sale_snapshot_count(self):
        """Cuenta las líneas congeladas de cada orden."""
        data = self.env['primate.sale.snapshot']._read_group(
            [('pos_order_id', 'in', self.ids)], ['pos_order_id'], ['__count'])
        mapped = {order.id: count for order, count in data}
        for order in self:
            order.sale_snapshot_count = mapped.get(order.id, 0)

    def _snapshot_warehouse(self):
        """Local al que se imputa la venta.

        Por defecto el almacén de la caja. Cada instalación resuelve el concepto de
        local como pueda: en FORUM las cajas apuntan a almacenes ficticios y el local
        real sale del usuario de sucursal, así que allá esto se sobrescribe.
        """
        self.ensure_one()
        return self.config_id.warehouse_id

    def _snapshot_line_employee(self, line):
        """Vendedor de una línea del punto de venta."""
        self.ensure_one()
        employee = line.user_id if 'user_id' in line._fields else False
        if employee and employee._name == 'hr.employee':
            return employee
        return self.employee_id if 'employee_id' in self._fields else False

    def _build_sale_snapshot(self):
        """Congela las líneas de las órdenes que no tienen factura."""
        snapshot_model = self.env['primate.sale.snapshot'].sudo()
        payment_model = self.env['primate.sale.snapshot.payment'].sudo()
        created = snapshot_model.browse()
        for order in self:
            if order.account_move:
                # La factura es el documento de la venta: se congela desde ahí.
                continue
            if order.sale_snapshot_ids:
                continue
            company = order.company_id
            date = fields.Date.to_date(order.date_order)
            warehouse = order._snapshot_warehouse()
            rows = []
            for line in order.lines:
                if not line.product_id:
                    continue
                values = snapshot_model._product_values(line.product_id, company, date)
                values.update({
                    'pos_order_id': order.id,
                    'pos_order_line_id': line.id,
                    'company_id': company.id,
                    'warehouse_id': warehouse.id if warehouse else False,
                    'employee_id': (order._snapshot_line_employee(line) or
                                    self.env['hr.employee']).id,
                    'session_id': order.session_id.id,
                    'config_id': order.config_id.id,
                    'sale_datetime': order.date_order,
                    'sale_date': date,
                    'quantity': line.qty,
                    'price_unit': line.price_unit,
                    'discount': line.discount,
                    'price_subtotal': line.price_subtotal,
                    'currency_id': order.currency_id.id,
                    'management_value': (values['management_cost'] or 0.0) * line.qty,
                })
                rows.append(values)
            if rows:
                created |= snapshot_model.create(rows)
            payment_model.create([{
                'pos_order_id': order.id,
                'payment_method_id': payment.payment_method_id.id,
                'payment_method_name': payment.payment_method_id.display_name,
                'amount': payment.amount,
                'currency_id': payment.currency_id.id,
                'payment_date': payment.payment_date,
            } for payment in order.payment_ids])
        return created

    def _create_order_picking(self):
        """Congela la venta al cerrarse la orden, junto con su movimiento de stock."""
        res = super()._create_order_picking()
        # Mismo motivo que en account_move._post: sin savepoint, atrapar un error
        # de base deja la transaccion abortada y el POS revienta despues, lejos de
        # aca, con un InFailedSqlTransaction que no dice nada.
        try:
            with self.env.cr.savepoint():
                self._build_sale_snapshot()
        except Exception:  # noqa: BLE001 - congelar no puede impedir cobrar
            _logger.exception(
                'No se pudo congelar la venta de las órdenes %s', self.ids)
        return res
