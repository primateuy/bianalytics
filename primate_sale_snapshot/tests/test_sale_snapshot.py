# -*- coding: utf-8 -*-
"""El congelado de venta: que congele, y que no se mueva después."""
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'primate_sale_snapshot')
class TestSaleSnapshot(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.env['res.currency'].create({
            'name': 'PSS', 'symbol': 'PSS', 'rounding': 0.01,
        })
        cls.company.management_currency_id = cls.currency
        cls.env['res.currency.rate'].create({
            'currency_id': cls.currency.id, 'company_id': cls.company.id,
            'name': '2020-01-01', 'rate': 1.0 / 45.0,
        })

        cls.familia = cls.env['product.category'].create({'name': 'PSS Familia'})
        cls.subfamilia = cls.env['product.category'].create({
            'name': 'PSS Subfamilia', 'parent_id': cls.familia.id})
        cls.etiqueta = cls.env['product.tag'].create({'name': 'PSS Etiqueta'})
        cls.product = cls.env['product.product'].create({
            'name': 'PSS Producto',
            'type': 'consu',
            'categ_id': cls.subfamilia.id,
            'product_tag_ids': [(6, 0, cls.etiqueta.ids)],
            'list_price': 300.0,
        })
        # Igual que arriba: el cálculo pendiente tiene que bajar a la base antes del
        # UPDATE crudo, o el flush lo pisa.
        cls.product.ultimo_costo_mr
        cls.env.flush_all()
        cls.env.cr.execute(
            'UPDATE product_product SET ultimo_costo_mr = 10.0 WHERE id = %s',
            (cls.product.id,))
        cls.product.invalidate_recordset()

        cls.partner = cls.env['res.partner'].create({'name': 'PSS Cliente'})
        # Diario propio, fuera del circuito de facturación electrónica: la localización
        # uruguaya resuelve el tipo de documento de DGI solo en los diarios de CFE, y
        # eso exige parámetros que no son asunto de este módulo.
        cls.journal = cls.env['account.journal'].create({
            'name': 'PSS Ventas', 'code': 'PSSV', 'type': 'sale',
            'company_id': cls.company.id,
        })
        if 'diario_cfe' in cls.journal._fields:
            cls.journal.diario_cfe = False

    def _factura(self):
        """Una factura de cliente con una línea del producto, ya congelada.

        No se publica: la localización uruguaya exige configuración de CFE por tipo de
        documento, que no es asunto de este módulo y haría que el test dependiera de los
        parámetros de facturación electrónica de la base. Se llama directo al
        constructor, que es exactamente lo que hace _post.
        """
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'journal_id': self.journal.id,
            'partner_id': self.partner.id,
            'invoice_date': fields.Date.context_today(self.env['account.move']),
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'quantity': 3.0,
                'price_unit': 250.0,
            })],
        })
        move._build_sale_snapshot()
        return move

    def test_congela_al_publicar(self):
        """Publicar la factura deja la foto del producto."""
        move = self._factura()
        self.assertEqual(len(move.sale_snapshot_ids), 1)
        snapshot = move.sale_snapshot_ids
        self.assertEqual(snapshot.product_id, self.product)
        self.assertEqual(snapshot.categ_id, self.subfamilia)
        self.assertEqual(snapshot.categ_parent_id, self.familia)
        self.assertEqual(snapshot.tag_ids, self.etiqueta)
        self.assertAlmostEqual(snapshot.list_price, 300.0, places=2)
        self.assertEqual(snapshot.quantity, 3.0)

    def test_el_costo_de_gestion_queda_congelado_con_su_tipo_de_cambio(self):
        """Diez de costo MR a un cambio de 45 dan 450, y por tres unidades 1.350."""
        snapshot = self._factura().sale_snapshot_ids
        self.assertAlmostEqual(snapshot.cost_report, 10.0, places=2)
        self.assertAlmostEqual(snapshot.management_rate, 45.0, places=4)
        self.assertAlmostEqual(snapshot.management_cost, 450.0, places=2)
        self.assertAlmostEqual(snapshot.management_value, 1350.0, places=2)

    def test_no_se_mueve_cuando_cambia_el_producto(self):
        """Es el punto del módulo: recategorizar no reescribe la venta."""
        snapshot = self._factura().sale_snapshot_ids
        otra_familia = self.env['product.category'].create({'name': 'PSS Otra'})
        self.product.categ_id = otra_familia
        self.product.list_price = 999.0
        self.product.product_tag_ids = [(5, 0, 0)]
        snapshot.invalidate_recordset()
        self.assertEqual(snapshot.categ_id, self.subfamilia)
        self.assertEqual(snapshot.categ_parent_id, self.familia)
        self.assertAlmostEqual(snapshot.list_price, 300.0, places=2)
        self.assertEqual(snapshot.tag_ids, self.etiqueta)

    def test_es_inmutable(self):
        """No se edita ni se borra a mano."""
        snapshot = self._factura().sale_snapshot_ids
        with self.assertRaises(UserError):
            snapshot.list_price = 1.0
        with self.assertRaises(UserError):
            snapshot.unlink()

    def test_publicar_dos_veces_no_duplica(self):
        """Volver a pasar por la publicación no vuelve a congelar."""
        move = self._factura()
        move._build_sale_snapshot()
        self.assertEqual(len(move.sale_snapshot_ids), 1)

    def test_campos_configurables(self):
        """Lo declarado en la configuración viaja al campo genérico."""
        campo = self.env['ir.model.fields'].search([
            ('model', '=', 'product.template'),
            ('name', '=', 'description_sale')], limit=1)
        self.env['primate.snapshot.field'].create({'field_id': campo.id})
        self.product.description_sale = 'Como estaba al venderse'
        snapshot = self._factura().sale_snapshot_ids
        self.assertEqual(
            snapshot.extra_values.get('description_sale'), 'Como estaba al venderse')
        # Y no se mueve cuando cambia el producto.
        self.product.description_sale = 'Cambiado después'
        snapshot.invalidate_recordset()
        self.assertEqual(
            snapshot.extra_values.get('description_sale'), 'Como estaba al venderse')

    def test_solo_campos_de_producto(self):
        """La configuración no acepta campos de otros modelos."""
        from odoo.exceptions import ValidationError
        campo = self.env['ir.model.fields'].search([
            ('model', '=', 'res.partner'), ('name', '=', 'name')], limit=1)
        with self.assertRaises(ValidationError):
            self.env['primate.snapshot.field'].create({'field_id': campo.id})
