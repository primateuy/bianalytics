# -*- coding: utf-8 -*-
"""Costo de gestión: conversión con el tipo de cambio que fija la empresa."""
from datetime import date

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'primate_management_cost')
class TestManagementCost(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.env['res.currency'].create({
            'name': 'PMG', 'symbol': 'PMG', 'rounding': 0.01,
        })
        cls.company.management_currency_id = cls.currency
        # 40 unidades de la moneda de la compañía por una de gestión, y 45 desde
        # noviembre: es la forma en que FORUM sostiene el tipo de cambio en el tiempo.
        cls.env['res.currency.rate'].create([
            {'currency_id': cls.currency.id, 'company_id': cls.company.id,
             'name': '2025-01-01', 'rate': 1.0 / 40.0},
            {'currency_id': cls.currency.id, 'company_id': cls.company.id,
             'name': '2025-11-01', 'rate': 1.0 / 45.0},
        ])

    def test_tipo_de_cambio_vigente_a_la_fecha(self):
        """Cada fecha toma la cotización que estaba en pie ese día, no la de hoy."""
        self.assertAlmostEqual(
            self.company._get_management_rate(date(2025, 6, 30)), 40.0, places=4)
        self.assertAlmostEqual(
            self.company._get_management_rate(date(2025, 11, 15)), 45.0, places=4)

    def test_antes_de_la_primera_cotizacion_no_hay_tipo_de_cambio(self):
        """Sin cotización devuelve cero, para que quien llama decida qué hacer."""
        self.assertEqual(self.company._get_management_rate(date(2024, 1, 1)), 0.0)

    def test_sin_moneda_de_gestion_no_hay_tipo_de_cambio(self):
        """Una compañía sin moneda de gestión no inventa un número."""
        self.company.management_currency_id = False
        self.assertEqual(self.company._get_management_rate(date(2025, 12, 1)), 0.0)

    def test_conversion(self):
        """Diez dólares de reportería a un cambio de 45 son 450 pesos de gestión."""
        self.assertAlmostEqual(
            self.company._convert_report_to_management(10.0, date(2025, 12, 1)),
            450.0, places=2)

    def test_costo_de_gestion_del_producto(self):
        """El producto muestra su UCMR llevado al cambio de gestión."""
        producto = self.env['product.product'].create({
            'name': 'PMG Producto', 'type': 'product',
        })
        # ultimo_costo_mr es calculado y almacenado (de tchistorico). Hay que dejar que
        # se calcule y se escriba ANTES del UPDATE crudo: si queda pendiente, el flush
        # posterior pisa lo que escribamos.
        producto.ultimo_costo_mr
        self.env.flush_all()
        self.env.cr.execute(
            'UPDATE product_product SET ultimo_costo_mr = 10.0 WHERE id = %s',
            (producto.id,))
        producto.invalidate_recordset()
        esperado = 10.0 * self.company._get_management_rate()
        self.assertAlmostEqual(producto.management_cost, esperado, places=2)

    def test_el_reporte_expone_las_columnas(self):
        """El reporte de existencias trae las columnas nuevas y son consultables."""
        reporte = self.env['stock.quant.product.location.report']
        for campo in ('management_rate', 'management_cost', 'management_value'):
            self.assertIn(campo, reporte._fields)
        # La agrupación tiene que resolverse en Postgres sin error.
        reporte.read_group([], ['management_value:sum'], ['product_id'], limit=1)
