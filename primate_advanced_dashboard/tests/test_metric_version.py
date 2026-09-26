# -*- coding: utf-8 -*-
"""Versionado y resolución de métricas (secciones 5.1, 5.2 y 5.3)."""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import UserError, ValidationError


@tagged('post_install', '-at_install', 'primate_advanced_dashboard')
class TestMetricVersion(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.metric = cls.env['primate.metric'].create({
            'name': 'Precio de lista de productos',
            'code': 'test_list_price',
            'unit_type': 'money',
        })
        cls.version = cls.env['primate.metric.version'].create({
            'metric_id': cls.metric.id,
            'source_model': 'product.template',
            'value_field': 'list_price',
            'date_field': 'create_date',
            'aggregation': 'sum',
            'gap_ref': 'G-99',
        })

    def test_confirmed_definition_is_immutable(self):
        """Una versión confirmada no admite cambios de cálculo."""
        self.version.action_confirm()
        with self.assertRaises(UserError):
            self.version.aggregation = 'avg'

    def test_confirmed_allows_non_calculation_changes(self):
        """Los campos que no definen el cálculo sí se pueden tocar."""
        self.version.action_confirm()
        self.version.notes = 'Revisado con el equipo.'
        self.assertEqual(self.version.notes, 'Revisado con el equipo.')

    def test_new_version_increments_and_starts_draft(self):
        """Nueva versión arranca en borrador con el número siguiente."""
        self.version.action_confirm()
        self.version.action_new_version()
        versions = self.metric.version_ids.sorted('version')
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[1].version, 2)
        self.assertEqual(versions[1].state, 'draft')

    def test_get_version_prefers_confirmed(self):
        """La versión vigente es la última confirmada, no la borrador posterior."""
        self.version.action_confirm()
        self.version.action_new_version()
        self.assertEqual(self.metric.get_version(self.env.company), self.version)

    def test_get_version_falls_back_to_draft(self):
        """Sin ninguna confirmada se usa la borrador, para que el catálogo provisorio sirva."""
        self.assertEqual(self.metric.get_version(self.env.company), self.version)

    def test_company_override_wins(self):
        """El override de compañía tiene prioridad sobre la definición base (5.2)."""
        self.version.action_confirm()
        override = self.env['primate.metric.version'].create({
            'metric_id': self.metric.id,
            'company_id': self.env.company.id,
            'source_model': 'product.template',
            'value_field': 'standard_price',
            'date_field': 'create_date',
            'aggregation': 'sum',
            'version': 1,
        })
        override.action_confirm()
        self.assertEqual(self.metric.get_version(self.env.company), override)

    def test_ratio_requires_components(self):
        """Un ratio sin numerador y denominador no se puede guardar."""
        with self.assertRaises(ValidationError):
            self.env['primate.metric.version'].create({
                'metric_id': self.metric.id,
                'calc_type': 'ratio',
                'version': 5,
            })

    def test_ratio_defaults_to_aggregate_divide(self):
        """El modo por defecto de un ratio nuevo es agregado y dividir (5.1)."""
        second = self.env['primate.metric'].create({
            'name': 'Cantidad de productos', 'code': 'test_count', 'unit_type': 'count'})
        counter = self.env['primate.metric.version'].create({
            'metric_id': second.id,
            'source_model': 'product.template',
            'date_field': 'create_date',
            'aggregation': 'count',
        })
        ratio_metric = self.env['primate.metric'].create({
            'name': 'Precio promedio', 'code': 'test_avg_price', 'unit_type': 'ratio'})
        ratio = self.env['primate.metric.version'].create({
            'metric_id': ratio_metric.id,
            'calc_type': 'ratio',
            'numerator_version_id': self.version.id,
            'denominator_version_id': counter.id,
        })
        self.assertEqual(ratio.ratio_mode, 'aggregate_divide')

    def test_missing_date_field_is_rejected(self):
        """Sin campo de fecha no hay grano diario posible."""
        with self.assertRaises(ValidationError):
            self.env['primate.metric.version'].create({
                'metric_id': self.metric.id,
                'source_model': 'product.template',
                'value_field': 'list_price',
                'aggregation': 'sum',
                'version': 7,
            })

    def test_unknown_source_model_is_rejected(self):
        """Un modelo origen inexistente se detecta al guardar."""
        with self.assertRaises(ValidationError):
            self.env['primate.metric.version'].create({
                'metric_id': self.metric.id,
                'source_model': 'modelo.que.no.existe',
                'value_field': 'list_price',
                'date_field': 'create_date',
                'aggregation': 'sum',
                'version': 8,
            })

    def test_non_stored_refund_field_is_rejected(self):
        """Un campo de devolución no almacenado no se puede filtrar y hay que avisarlo.

        Sin esta validación el dominio se descartaba en silencio y la métrica devolvía
        el total sin excluir las devoluciones.
        """
        with self.assertRaises(ValidationError):
            self.env['primate.metric.version'].create({
                'metric_id': self.metric.id,
                'source_model': 'product.template',
                'value_field': 'list_price',
                'date_field': 'create_date',
                'aggregation': 'sum',
                'refund_treatment': 'exclude',
                'refund_field': 'display_name',
                'version': 9,
            })

    def test_unknown_refund_field_is_rejected(self):
        """Un campo de devolución inexistente se detecta al guardar."""
        with self.assertRaises(ValidationError):
            self.env['primate.metric.version'].create({
                'metric_id': self.metric.id,
                'source_model': 'product.template',
                'value_field': 'list_price',
                'date_field': 'create_date',
                'aggregation': 'sum',
                'refund_treatment': 'exclude',
                'refund_field': 'campo_que_no_existe',
                'version': 10,
            })
