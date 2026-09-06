# -*- coding: utf-8 -*-
"""Precálculo de la tabla de hechos y lectura del motor (secciones 5.1, 7 y 9)."""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo import fields


@tagged('post_install', '-at_install', 'primate_advanced_dashboard')
class TestFactPrecompute(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env['primate.metric'])
        cls.categ_a = cls.env['product.category'].create({'name': 'PAD Categoría A'})
        cls.categ_b = cls.env['product.category'].create({'name': 'PAD Categoría B'})
        cls.env['product.template'].create([
            {'name': 'PAD Producto 1', 'list_price': 100.0, 'categ_id': cls.categ_a.id},
            {'name': 'PAD Producto 2', 'list_price': 300.0, 'categ_id': cls.categ_a.id},
            {'name': 'PAD Producto 3', 'list_price': 200.0, 'categ_id': cls.categ_b.id},
        ])

        # Dimensión de prueba: categoría de producto resuelta desde product.template.
        cls.dimension = cls.env['primate.metric.dimension'].create({
            'name': 'Categoría de prueba',
            'code': 'pad_test_categ',
            'fact_column': 'categ_id',
            'model_name': 'product.category',
            'path_ids': [(0, 0, {
                'source_model': 'product.template',
                'field_path': 'categ_id',
            })],
        })

        cls.amount_metric = cls.env['primate.metric'].create({
            'name': 'PAD Importe', 'code': 'pad_test_amount', 'unit_type': 'money'})
        cls.amount = cls.env['primate.metric.version'].create({
            'metric_id': cls.amount_metric.id,
            'source_model': 'product.template',
            'value_field': 'list_price',
            'date_field': 'create_date',
            'aggregation': 'sum',
            'domain': "[('name', 'like', 'PAD Producto')]",
            'dimension_ids': [(6, 0, cls.dimension.ids)],
        })

        cls.count_metric = cls.env['primate.metric'].create({
            'name': 'PAD Conteo', 'code': 'pad_test_count', 'unit_type': 'count'})
        cls.counter = cls.env['primate.metric.version'].create({
            'metric_id': cls.count_metric.id,
            'source_model': 'product.template',
            'date_field': 'create_date',
            'aggregation': 'count',
            'domain': "[('name', 'like', 'PAD Producto')]",
            'dimension_ids': [(6, 0, cls.dimension.ids)],
        })
        cls.engine = cls.env['primate.metric.engine']

    def _rebuild(self, versions):
        return self.env['primate.metric.fact'].rebuild(versions, self.today, self.today)

    def test_facts_are_grouped_by_dimension(self):
        """El precálculo genera una fila por día y valor de dimensión."""
        self._rebuild(self.amount)
        facts = self.env['primate.metric.fact'].search([
            ('metric_version_id', '=', self.amount.id)])
        self.assertEqual(len(facts), 2)
        by_categ = {fact.categ_id: fact.value for fact in facts}
        self.assertAlmostEqual(by_categ[self.categ_a], 400.0, places=2)
        self.assertAlmostEqual(by_categ[self.categ_b], 200.0, places=2)

    def test_rebuild_is_idempotent(self):
        """Recalcular el mismo rango no duplica hechos."""
        self._rebuild(self.amount)
        first = self.env['primate.metric.fact'].search_count([
            ('metric_version_id', '=', self.amount.id)])
        self._rebuild(self.amount)
        second = self.env['primate.metric.fact'].search_count([
            ('metric_version_id', '=', self.amount.id)])
        self.assertEqual(first, second)

    def test_engine_total_without_dimension(self):
        """Sin dimensión el motor devuelve el total del rango."""
        self._rebuild(self.amount)
        rows = self.engine.compute(self.amount, self.today, self.today)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]['value'], 600.0, places=2)

    def test_engine_breakdown_sorted_desc(self):
        """El desglose viene ordenado de mayor a menor, como pide el ranking."""
        self._rebuild(self.amount)
        rows = self.engine.compute(self.amount, self.today, self.today, self.dimension)
        self.assertEqual(len(rows), 2)
        self.assertGreaterEqual(rows[0]['value'], rows[1]['value'])

    def test_engine_respects_limit(self):
        """El tope de filas del ranking se aplica después de ordenar."""
        self._rebuild(self.amount)
        rows = self.engine.compute(
            self.amount, self.today, self.today, self.dimension, limit=1)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]['value'], 400.0, places=2)

    def test_ratio_aggregate_divide(self):
        """Agregado y dividir: suma numerador y denominador y divide al final (5.1)."""
        ratio_metric = self.env['primate.metric'].create({
            'name': 'PAD Promedio', 'code': 'pad_test_ratio', 'unit_type': 'ratio'})
        ratio = self.env['primate.metric.version'].create({
            'metric_id': ratio_metric.id,
            'calc_type': 'ratio',
            'ratio_mode': 'aggregate_divide',
            'numerator_version_id': self.amount.id,
            'denominator_version_id': self.counter.id,
            'dimension_ids': [(6, 0, self.dimension.ids)],
        })
        self._rebuild(self.amount | self.counter)
        rows = self.engine.compute(ratio, self.today, self.today)
        # 600 de importe sobre 3 productos = 200 de promedio.
        self.assertAlmostEqual(rows[0]['value'], 200.0, places=2)

    def test_ratio_aggregate_divide_stores_no_facts(self):
        """El ratio en modo agregado y dividir no guarda hechos propios."""
        ratio_metric = self.env['primate.metric'].create({
            'name': 'PAD Promedio 2', 'code': 'pad_test_ratio_2', 'unit_type': 'ratio'})
        ratio = self.env['primate.metric.version'].create({
            'metric_id': ratio_metric.id,
            'calc_type': 'ratio',
            'numerator_version_id': self.amount.id,
            'denominator_version_id': self.counter.id,
        })
        self._rebuild(ratio)
        self.assertEqual(
            self.env['primate.metric.fact'].search_count([
                ('metric_version_id', '=', ratio.id)]), 0)

    def test_ratio_per_dimension_divides_within_group(self):
        """Al desglosar, el ratio se divide dentro de cada grupo, no sobre el total."""
        ratio_metric = self.env['primate.metric'].create({
            'name': 'PAD Promedio 3', 'code': 'pad_test_ratio_3', 'unit_type': 'ratio'})
        ratio = self.env['primate.metric.version'].create({
            'metric_id': ratio_metric.id,
            'calc_type': 'ratio',
            'numerator_version_id': self.amount.id,
            'denominator_version_id': self.counter.id,
            'dimension_ids': [(6, 0, self.dimension.ids)],
        })
        self._rebuild(self.amount | self.counter)
        rows = self.engine.compute(ratio, self.today, self.today, self.dimension)
        by_key = {row['key']: row['value'] for row in rows}
        # Categoría A: 400 sobre 2 productos = 200. Categoría B: 200 sobre 1 = 200.
        self.assertAlmostEqual(by_key[self.categ_a.id], 200.0, places=2)
        self.assertAlmostEqual(by_key[self.categ_b.id], 200.0, places=2)

    def test_display_factor_scales_the_value(self):
        """El factor de escala lleva un ratio 0-1 a la unidad en la que se lee.

        Sin esto un margen del 23,77 % se mostraba como "0,24 %".
        """
        ratio_metric = self.env['primate.metric'].create({
            'name': 'PAD Ratio escalado', 'code': 'pad_test_scaled',
            'unit_type': 'percent', 'display_factor': 100.0})
        ratio = self.env['primate.metric.version'].create({
            'metric_id': ratio_metric.id,
            'calc_type': 'ratio',
            'numerator_version_id': self.amount.id,
            'denominator_version_id': self.amount.id,
        })
        self._rebuild(self.amount)
        rows = self.engine.compute(ratio, self.today, self.today)
        # Numerador igual a denominador: el ratio es 1 y escalado da 100.
        self.assertAlmostEqual(rows[0]['value'], 100.0, places=2)

    def test_display_factor_one_leaves_value_intact(self):
        """Con factor 1 el valor no se toca."""
        self._rebuild(self.amount)
        rows = self.engine.compute(self.amount, self.today, self.today)
        self.assertAlmostEqual(rows[0]['value'], 600.0, places=2)

    def test_comparison_payload_includes_variation(self):
        """El motor devuelve actual, comparable y variación en una sola llamada."""
        self._rebuild(self.amount)
        comparison = self.env.ref('primate_advanced_dashboard.comparison_same_period_last_year')
        month = self.env['primate.period.type'].search([('code', '=', 'month')], limit=1)
        result = self.engine.compute_with_comparison(
            self.amount, self.today, self.today, comparison, period_type=month)
        self.assertIn('current', result)
        self.assertIn('comparable_from', result)
        # El año anterior no tiene hechos, así que el comparable es cero y el
        # porcentaje queda en None para que la vista muestre N/D.
        self.assertAlmostEqual(result['current'][0]['comparable'], 0.0, places=2)
        self.assertIsNone(result['current'][0]['variation_percent'])

    def test_run_records_audit(self):
        """La corrida deja registro con la cantidad de hechos generados."""
        run = self.env['primate.metric.fact.run'].launch(
            self.amount, self.today, self.today, origin='manual')
        self.assertEqual(run.state, 'done')
        self.assertEqual(run.fact_count, 2)


@tagged('post_install', '-at_install', 'primate_advanced_dashboard')
class TestFactTimezone(TransactionCase):
    """El huso del precálculo no puede depender de quién lo ejecuta."""

    def test_company_timezone_wins(self):
        """Si la compañía tiene huso, se usa el de la compañía."""
        company = self.env.company
        company.partner_id.tz = 'America/Montevideo'
        self.assertEqual(
            self.env['primate.metric.fact']._get_timezone(company),
            'America/Montevideo')

    def test_parameter_is_used_when_company_has_no_timezone(self):
        """Sin huso en la compañía se usa el parámetro del módulo, no el del usuario."""
        company = self.env.company
        company.partner_id.tz = False
        self.env.user.tz = 'Europe/Madrid'
        self.env['ir.config_parameter'].sudo().set_param(
            'primate_advanced_dashboard.default_timezone', 'America/Montevideo')
        self.assertEqual(
            self.env['primate.metric.fact']._get_timezone(company),
            'America/Montevideo')

    def test_falls_back_to_utc(self):
        """Sin compañía ni parámetro, UTC."""
        company = self.env.company
        company.partner_id.tz = False
        self.env['ir.config_parameter'].sudo().search(
            [('key', '=', 'primate_advanced_dashboard.default_timezone')]).unlink()
        self.assertEqual(self.env['primate.metric.fact']._get_timezone(company), 'UTC')


@tagged('post_install', '-at_install', 'primate_advanced_dashboard')
class TestDashboardAccess(TransactionCase):
    """Un usuario de dashboards no necesita permisos de Inventario ni de RRHH."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.viewer = cls.env['res.users'].create({
            'name': 'PAD Lector de prueba',
            'login': 'pad_test_viewer',
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('primate_advanced_dashboard.group_dashboard_user').id,
            ])],
        })
        cls.categ = cls.env['product.category'].create({'name': 'PAD Acceso'})
        cls.env['product.template'].create(
            {'name': 'PAD Acceso Producto', 'list_price': 50.0, 'categ_id': cls.categ.id})
        cls.dimension = cls.env['primate.metric.dimension'].create({
            'name': 'Categoría de acceso',
            'code': 'pad_test_access_categ',
            'fact_column': 'categ_id',
            'model_name': 'product.category',
            'path_ids': [(0, 0, {
                'source_model': 'product.template',
                'field_path': 'categ_id',
            })],
        })
        metric = cls.env['primate.metric'].create({
            'name': 'PAD Acceso Importe', 'code': 'pad_test_access', 'unit_type': 'money'})
        cls.version = cls.env['primate.metric.version'].create({
            'metric_id': metric.id,
            'source_model': 'product.template',
            'value_field': 'list_price',
            'date_field': 'create_date',
            'aggregation': 'sum',
            'domain': "[('name', '=', 'PAD Acceso Producto')]",
            'dimension_ids': [(6, 0, cls.dimension.ids)],
        })
        cls.today = fields.Date.context_today(cls.env['primate.metric'])
        cls.env['primate.metric.fact'].rebuild(cls.version, cls.today, cls.today)

    def test_viewer_can_read_dimension_labels(self):
        """El desglose devuelve la etiqueta aunque el usuario no lea el modelo destino."""
        engine = self.env['primate.metric.engine'].with_user(self.viewer)
        rows = engine.compute(
            self.version.with_user(self.viewer), self.today, self.today, self.dimension)
        self.assertTrue(rows)
        self.assertEqual(rows[0]['label'], self.categ.name)
