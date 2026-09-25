# -*- coding: utf-8 -*-
"""Reconstrucción de saldos y lectura de una medida de saldo."""
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'primate_stock_balance')
class TestStockBalance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.balance = cls.env['primate.stock.balance']
        cls.today = fields.Date.context_today(cls.balance)

        cls.warehouse = cls.env['stock.warehouse'].create({
            'name': 'PSB Local', 'code': 'PSB1',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'PSB Producto', 'type': 'product',
        })
        cls.supplier_location = cls.env.ref('stock.stock_location_suppliers')
        cls.customer_location = cls.env.ref('stock.stock_location_customers')

        # Cortes semanales los domingos, que es el valor con el que sale el módulo.
        cls.env['ir.config_parameter'].sudo().set_param(
            'primate_stock_balance.cadence', 'weekly')
        cls.env['ir.config_parameter'].sudo().set_param(
            'primate_stock_balance.cutoff_weekday', '7')

    def _move(self, quantity, source, destination, date):
        """Registra un movimiento validado y le fuerza la fecha histórica.

        Odoo pisa la fecha al validar, así que hay que escribirla después, en el
        movimiento y en sus líneas.
        """
        move = self.env['stock.move'].create({
            'name': 'PSB movimiento',
            'product_id': self.product.id,
            'product_uom': self.product.uom_id.id,
            'product_uom_qty': quantity,
            'location_id': source.id,
            'location_dest_id': destination.id,
        })
        move._action_confirm()
        move._action_assign()
        move.move_line_ids.quantity = quantity
        move.picked = True
        move._action_done()
        move.date = date
        move.move_line_ids.date = date
        return move

    # =========================================================================
    # Cadencia
    # =========================================================================
    def test_cutoff_dates_weekly(self):
        """Los cortes semanales caen todos en el día configurado."""
        cutoffs = self.balance.cutoff_dates(
            self.today - timedelta(days=28), self.today)
        self.assertTrue(cutoffs, 'Cuatro semanas tienen que contener algún corte.')
        for cutoff in cutoffs:
            self.assertEqual(cutoff.isoweekday(), 7, 'El corte semanal cae en domingo.')
        for previous, following in zip(cutoffs, cutoffs[1:]):
            self.assertEqual((following - previous).days, 7)

    def test_cutoff_dates_daily(self):
        """En cadencia diaria hay un corte por día del rango."""
        self.env['ir.config_parameter'].sudo().set_param(
            'primate_stock_balance.cadence', 'daily')
        cutoffs = self.balance.cutoff_dates(
            self.today - timedelta(days=6), self.today)
        self.assertEqual(len(cutoffs), 7)

    # =========================================================================
    # Reconstrucción
    # =========================================================================
    def test_rebuild_reconstruye_el_saldo_de_cada_corte(self):
        """El saldo de un corte pasado no es el de hoy: excluye lo posterior."""
        stock_location = self.warehouse.lot_stock_id
        # Hace cinco semanas entran 100 unidades; hace una semana salen 30.
        self._move(100, self.supplier_location, stock_location,
                   fields.Datetime.to_datetime(self.today - timedelta(days=35)))
        self._move(30, stock_location, self.customer_location,
                   fields.Datetime.to_datetime(self.today - timedelta(days=7)))

        self.balance.rebuild(self.today - timedelta(days=42), self.today)
        rows = self.balance.search([
            ('product_id', '=', self.product.id),
            ('warehouse_id', '=', self.warehouse.id),
        ], order='date')
        self.assertTrue(rows, 'La reconstrucción tiene que dejar saldos.')

        # El último corte ya refleja la salida; uno anterior a ella, no.
        self.assertEqual(rows[-1].quantity, 70.0)
        antes_de_la_salida = rows.filtered(
            lambda row: row.date < self.today - timedelta(days=7)
            and row.date > self.today - timedelta(days=35))
        self.assertTrue(antes_de_la_salida, 'Tiene que haber cortes entre las dos fechas.')
        for row in antes_de_la_salida:
            self.assertEqual(row.quantity, 100.0)

    def test_rebuild_coincide_con_el_calculo_del_core(self):
        """El saldo del corte coincide con el qty_available a esa fecha del core."""
        stock_location = self.warehouse.lot_stock_id
        self._move(80, self.supplier_location, stock_location,
                   fields.Datetime.to_datetime(self.today - timedelta(days=30)))
        self._move(50, stock_location, self.customer_location,
                   fields.Datetime.to_datetime(self.today - timedelta(days=3)))

        self.balance.rebuild(self.today - timedelta(days=35), self.today)
        row = self.balance.search([
            ('product_id', '=', self.product.id),
            ('warehouse_id', '=', self.warehouse.id),
        ], order='date desc', limit=1)
        self.assertTrue(row)

        del_core = self.product.with_context(
            to_date=fields.Datetime.to_datetime(row.date + timedelta(days=1)),
            warehouse=self.warehouse.id,
        ).qty_available
        self.assertAlmostEqual(row.quantity, del_core, places=2)

    def test_rebuild_es_idempotente(self):
        """Correr dos veces el mismo rango no duplica filas."""
        self._move(10, self.supplier_location, self.warehouse.lot_stock_id,
                   fields.Datetime.to_datetime(self.today - timedelta(days=20)))
        domain = [('product_id', '=', self.product.id),
                  ('warehouse_id', '=', self.warehouse.id)]
        self.balance.rebuild(self.today - timedelta(days=28), self.today)
        primera = self.balance.search_count(domain)
        self.balance.rebuild(self.today - timedelta(days=28), self.today)
        self.assertEqual(self.balance.search_count(domain), primera)

    def test_traslado_interno_no_altera_el_saldo(self):
        """Mover entre dos ubicaciones internas del mismo almacén se cancela solo."""
        stock_location = self.warehouse.lot_stock_id
        interna = self.env['stock.location'].create({
            'name': 'PSB Interna', 'usage': 'internal',
            'location_id': stock_location.id,
        })
        self._move(40, self.supplier_location, stock_location,
                   fields.Datetime.to_datetime(self.today - timedelta(days=21)))
        self._move(15, stock_location, interna,
                   fields.Datetime.to_datetime(self.today - timedelta(days=10)))

        self.balance.rebuild(self.today - timedelta(days=28), self.today)
        rows = self.balance.search([
            ('product_id', '=', self.product.id),
            ('warehouse_id', '=', self.warehouse.id),
        ], order='date')
        for row in rows.filtered(lambda r: r.date > self.today - timedelta(days=21)):
            self.assertEqual(row.quantity, 40.0,
                             'Un traslado dentro del almacén no cambia su saldo.')
