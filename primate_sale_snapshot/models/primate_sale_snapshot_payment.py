# -*- coding: utf-8 -*-
"""Cómo se pagó la venta, congelado junto con el resto."""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .primate_sale_snapshot import REBUILD_CONTEXT

_logger = logging.getLogger(__name__)


class PrimateSaleSnapshotPayment(models.Model):
    _name = 'primate.sale.snapshot.payment'
    _description = 'Pago congelado de una venta'
    _order = 'move_id, id'

    move_id = fields.Many2one(
        'account.move', string='Factura', ondelete='cascade', index=True)
    pos_order_id = fields.Many2one(
        'pos.order', string='Orden de POS', ondelete='cascade', index=True)
    payment_method_id = fields.Many2one(
        'pos.payment.method', string='Forma de pago', ondelete='set null')
    payment_method_name = fields.Char(
        string='Forma de pago (texto)',
        help='El nombre que tenía la forma de pago al cobrarse. Sobrevive aunque después '
             'la renombren o la borren.')
    amount = fields.Monetary(string='Importe', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Moneda', ondelete='set null')
    payment_date = fields.Datetime(string='Fecha del pago')

    def write(self, vals):
        """Se regenera con la venta, no se edita."""
        if not self.env.context.get(REBUILD_CONTEXT):
            raise UserError(_('Un pago congelado no se modifica a mano.'))
        return super().write(vals)

    def unlink(self):
        """Se regenera con la venta, no se borra."""
        if not self.env.context.get(REBUILD_CONTEXT):
            raise UserError(_('Un pago congelado no se borra a mano.'))
        return super().unlink()
