# -*- coding: utf-8 -*-
"""Lectura de medidas de saldo: no se acumulan en el tiempo, sí entre dimensiones."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'primate_advanced_dashboard')
class TestBalanceMeasure(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.engine = cls.env['primate.metric.engine']
        cls.fact = cls.env['primate.metric.fact']
        cls.today = fields.Date.context_today(cls.env['primate.metric'])

        cls.company_a = cls.env['res.company'].create({'name': 'PAD Compañía A'})
        cls.company_b = cls.env['res.company'].create({'name': 'PAD Compañía B'})
        cls.dimension = cls.env['primate.metric.dimension'].create({
            'name': 'Compañía de prueba',
            'code': 'pad_test_company',
            'fact_column': 'company_id',
            'model_name': 'res.company',
        })

        metric = cls.env['primate.metric'].create({
            'name': 'PAD Saldo', 'code': 'pad_test_balance', 'unit_type': 'qty'})
        cls.version = cls.env['primate.metric.version'].create({
            'metric_id': metric.id,
            'source_model': 'product.template',
            'date_field': 'create_date',
            'value_field': 'list_price',
            'aggregation': 'sum',
            'measure_type': 'balance',
            'balance_mode': 'closing',
            'dimension_ids': [(6, 0, cls.dimension.ids)],
        })

        # Tres cortes semanales, con el saldo repartido en dos compañías.
        cls.cutoffs = [cls.today - timedelta(days=14),
                       cls.today - timedelta(days=7),
                       cls.today]
        valores = {cls.cutoffs[0]: (100.0, 50.0),
                   cls.cutoffs[1]: (200.0, 60.0),
                   cls.cutoffs[2]: (300.0, 70.0)}
        for cutoff, (valor_a, valor_b) in valores.items():
            for company, valor in ((cls.company_a, valor_a), (cls.company_b, valor_b)):
                cls.fact.create({
                    'metric_version_id': cls.version.id,
                    'date': cutoff,
                    'company_id': company.id,
                    'numerator': valor,
                    'denominator': 1.0,
                    'value': valor,
                })

    def test_el_saldo_no_se_suma_en_el_tiempo(self):
        """El total del período es el del último corte, no la suma de los tres."""
        rows = self.engine.compute(self.version, self.cutoffs[0], self.cutoffs[2])
        # Sumar daría 780; el saldo de cierre es 300 + 70.
        self.assertEqual(rows[0]['value'], 370.0)

    def test_el_saldo_se_suma_entre_dimensiones(self):
        """Desglosado por compañía, cada una muestra su saldo del último corte."""
        rows = self.engine.compute(
            self.version, self.cutoffs[0], self.cutoffs[2], dimension=self.dimension)
        por_compania = {row['key']: row['value'] for row in rows}
        self.assertEqual(por_compania[self.company_a.id], 300.0)
        self.assertEqual(por_compania[self.company_b.id], 70.0)

    def test_saldo_de_cierre_de_un_periodo_intermedio(self):
        """Un período que corta en el medio toma su propio último corte."""
        rows = self.engine.compute(self.version, self.cutoffs[0], self.cutoffs[1])
        self.assertEqual(rows[0]['value'], 260.0)

    def test_saldo_promedio(self):
        """En modo promedio se divide por la cantidad de cortes del período."""
        self.version.balance_mode = 'average'
        rows = self.engine.compute(self.version, self.cutoffs[0], self.cutoffs[2])
        # (150 + 260 + 370) / 3
        self.assertAlmostEqual(rows[0]['value'], 260.0, places=4)

    def test_arrastre_del_ultimo_saldo_conocido(self):
        """Un período sin ningún corte arrastra el último saldo, dentro del tope."""
        self.env['ir.config_parameter'].sudo().set_param(
            'primate_advanced_dashboard.balance_carry_days', '10')
        desde = self.cutoffs[1] + timedelta(days=1)
        hasta = self.cutoffs[1] + timedelta(days=3)
        rows = self.engine.compute(self.version, desde, hasta)
        self.assertEqual(rows[0]['value'], 260.0)

    def test_sin_arrastre_no_inventa_saldo(self):
        """Pasado el tope de arrastre no se muestra un saldo viejo como si fuera de hoy."""
        self.env['ir.config_parameter'].sudo().set_param(
            'primate_advanced_dashboard.balance_carry_days', '1')
        desde = self.cutoffs[2] + timedelta(days=20)
        hasta = self.cutoffs[2] + timedelta(days=25)
        rows = self.engine.compute(self.version, desde, hasta)
        self.assertEqual(rows[0]['value'], 0.0)

    def test_un_flujo_sigue_sumandose(self):
        """El cambio no altera la lectura de las métricas de flujo."""
        self.version.measure_type = 'flow'
        rows = self.engine.compute(self.version, self.cutoffs[0], self.cutoffs[2])
        self.assertEqual(rows[0]['value'], 780.0)

    def test_un_ratio_no_puede_ser_saldo(self):
        """El saldo se declara en el numerador o el denominador, no en el ratio."""
        metric = self.env['primate.metric'].create({
            'name': 'PAD Ratio', 'code': 'pad_test_ratio', 'unit_type': 'qty'})
        with self.assertRaises(ValidationError):
            self.env['primate.metric.version'].create({
                'metric_id': metric.id,
                'calc_type': 'ratio',
                'numerator_version_id': self.version.id,
                'denominator_version_id': self.version.id,
                'measure_type': 'balance',
            })

    def test_un_saldo_tiene_que_sumar(self):
        """Una medida de saldo con otra agregación no tiene sentido y se rechaza."""
        with self.assertRaises(ValidationError):
            self.version.aggregation = 'avg'
