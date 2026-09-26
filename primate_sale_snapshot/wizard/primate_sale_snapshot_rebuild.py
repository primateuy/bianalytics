# -*- coding: utf-8 -*-
"""Regeneración de congelados de venta.

Es la única puerta para rehacer un congelado, y existe para arreglar corridas fallidas
o para poblar el histórico de facturas anteriores a la instalación del módulo. Rehacer
un congelado vuelve a leer el producto de HOY: sirve para completar lo que falta, no
para recuperar cómo estaba el producto en una venta vieja, que si no se congeló en su
momento ya no está en ningún lado.
"""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

from ..models.primate_sale_snapshot import REBUILD_CONTEXT

_logger = logging.getLogger(__name__)


class PrimateSaleSnapshotRebuild(models.TransientModel):
    _name = 'primate.sale.snapshot.rebuild'
    _description = 'Regenerar congelados de venta'

    date_from = fields.Date(string='Desde', required=True)
    date_to = fields.Date(
        string='Hasta', required=True, default=lambda self: fields.Date.context_today(self))
    scope = fields.Selection(
        [('missing', 'Solo las que no tienen congelado'),
         ('all', 'Todas, rehaciendo las que ya lo tienen')],
        string='Alcance', default='missing', required=True,
        help='Rehacer una que ya lo tiene vuelve a leer el producto de hoy y pisa la '
             'foto anterior. Se usa solo para arreglar una corrida fallida.')
    include_pos = fields.Boolean(
        string='Incluir ventas sin factura', default=True,
        help='Las órdenes de punto de venta que no llegaron a una factura.')

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        """El rango tiene que ser válido."""
        for wizard in self:
            if wizard.date_from > wizard.date_to:
                raise ValidationError(_(
                    'La fecha desde no puede ser posterior a la fecha hasta.'))

    def action_run(self):
        """Regenera los congelados del rango y abre el resultado."""
        self.ensure_one()
        snapshot_model = self.env['primate.sale.snapshot']
        rebuild = self.with_context(**{REBUILD_CONTEXT: True})

        moves = self.env['account.move'].search([
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '=', 'posted'),
            ('invoice_date', '>=', self.date_from),
            ('invoice_date', '<=', self.date_to),
        ])
        if self.scope == 'missing':
            moves = moves.filtered(lambda move: not move.sale_snapshot_ids)
        else:
            existing = snapshot_model.with_context(
                **{REBUILD_CONTEXT: True}).search([('move_id', 'in', moves.ids)])
            existing.unlink()
            self.env['primate.sale.snapshot.payment'].with_context(
                **{REBUILD_CONTEXT: True}).search([('move_id', 'in', moves.ids)]).unlink()
        moves.with_context(**{REBUILD_CONTEXT: True})._build_sale_snapshot()

        orders = self.env['pos.order']
        if self.include_pos:
            orders = self.env['pos.order'].search([
                ('account_move', '=', False),
                ('date_order', '>=', fields.Datetime.to_datetime(self.date_from)),
                ('date_order', '<=', fields.Datetime.to_datetime(self.date_to)),
            ])
            if self.scope == 'all':
                snapshot_model.with_context(**{REBUILD_CONTEXT: True}).search(
                    [('pos_order_id', 'in', orders.ids)]).unlink()
                self.env['primate.sale.snapshot.payment'].with_context(
                    **{REBUILD_CONTEXT: True}).search(
                    [('pos_order_id', 'in', orders.ids)]).unlink()
            orders.with_context(**{REBUILD_CONTEXT: True})._build_sale_snapshot()

        _logger.info(
            'Congelados regenerados: %s facturas y %s órdenes sin factura.',
            len(moves), len(orders))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Congelados de venta'),
            'res_model': 'primate.sale.snapshot',
            'view_mode': 'tree,form',
            'domain': [('sale_date', '>=', self.date_from),
                       ('sale_date', '<=', self.date_to)],
            'target': 'current',
        }
