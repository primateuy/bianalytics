# -*- coding: utf-8 -*-
"""Casos borde de fechas del motor de comparativos (secciones 6 y 6.1)."""
from datetime import date

from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install', 'primate_advanced_dashboard')
class TestPeriodType(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.period = cls.env['primate.period.type']
        cls.month = cls.period.search([('code', '=', 'month')], limit=1)
        cls.iso_week = cls.period.search([('code', '=', 'iso_week')], limit=1)
        cls.year = cls.period.search([('code', '=', 'year')], limit=1)
        cls.quarter = cls.period.search([('code', '=', 'quarter')], limit=1)

    def test_month_period(self):
        """El mes va del primero al último día, incluso en febrero bisiesto."""
        self.assertEqual(
            self.month.get_period(date(2024, 2, 15)),
            (date(2024, 2, 1), date(2024, 2, 29)))
        self.assertEqual(
            self.month.get_period(date(2026, 2, 15)),
            (date(2026, 2, 1), date(2026, 2, 28)))

    def test_iso_week_period(self):
        """La semana ISO arranca en lunes y termina en domingo."""
        # El 20/08/2026 es jueves.
        start, end = self.iso_week.get_period(date(2026, 8, 20))
        self.assertEqual(start.isoweekday(), 1)
        self.assertEqual(end.isoweekday(), 7)
        self.assertEqual((end - start).days, 6)

    def test_quarter_period(self):
        """El trimestre cubre tres meses completos."""
        self.assertEqual(
            self.quarter.get_period(date(2026, 5, 10)),
            (date(2026, 4, 1), date(2026, 6, 30)))

    def test_shift_month_preserves_month_bounds(self):
        """Correr un mes atrás da el mes anterior completo, no 30 días atrás."""
        self.assertEqual(
            self.month.shift(date(2026, 3, 1), date(2026, 3, 31), -1),
            (date(2026, 2, 1), date(2026, 2, 28)))

    def test_shift_year_iso_week_compares_week_numbers(self):
        """Semana ISO 22 contra semana ISO 22 del año anterior, no fecha calendario."""
        start, end = self.iso_week.get_period(date(2026, 5, 28))
        iso_week_number = start.isocalendar()[1]
        cmp_start, _cmp_end = self.iso_week.shift_year(start, end, 1)
        self.assertEqual(cmp_start.isocalendar()[1], iso_week_number)
        self.assertEqual(cmp_start.isocalendar()[0], start.isocalendar()[0] - 1)

    def test_shift_year_handles_leap_day(self):
        """El 29 de febrero contra un año no bisiesto no explota."""
        cmp_start, _cmp_end = self.month.shift_year(date(2024, 2, 29), date(2024, 2, 29), 1)
        self.assertEqual(cmp_start, date(2023, 2, 28))


@tagged('post_install', '-at_install', 'primate_advanced_dashboard')
class TestComparison(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.month = cls.env['primate.period.type'].search([('code', '=', 'month')], limit=1)
        cls.yoy = cls.env.ref('primate_advanced_dashboard.comparison_same_period_last_year')
        cls.prev = cls.env.ref('primate_advanced_dashboard.comparison_prev_period')

    def test_same_period_last_year(self):
        """El comparable es el mismo rango del año anterior."""
        self.assertEqual(
            self.yoy.resolve(date(2026, 8, 1), date(2026, 8, 20), self.month),
            (date(2025, 8, 1), date(2025, 8, 20)))

    def test_prev_period(self):
        """El período anterior de un mes es el mes anterior completo."""
        self.assertEqual(
            self.prev.resolve(date(2026, 8, 1), date(2026, 8, 31), self.month),
            (date(2026, 7, 1), date(2026, 7, 31)))

    def test_variation_with_zero_comparable(self):
        """Con comparable en cero el porcentaje es None, para mostrar N/D."""
        result = self.env['primate.comparison'].compute_variation(100.0, 0.0)
        self.assertEqual(result['absolute'], 100.0)
        self.assertIsNone(result['percent'])

    def test_variation_percent(self):
        """La variación porcentual sale del comparable, no del actual."""
        result = self.env['primate.comparison'].compute_variation(18000000.0, 16500000.0)
        self.assertAlmostEqual(result['absolute'], 1500000.0, places=2)
        self.assertAlmostEqual(result['percent'], 9.0909, places=3)
