# -*- coding: utf-8 -*-
"""Cómo estaba configurado el producto en el momento en que se vendió."""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Contexto que habilita escribir o borrar un congelado ya escrito. Lo pone el asistente
# de regeneración, que es la única puerta para rehacerlo.
REBUILD_CONTEXT = 'primate_snapshot_rebuild'


class PrimateSaleSnapshot(models.Model):
    _name = 'primate.sale.snapshot'
    _description = 'Congelado de una línea de venta'
    _order = 'sale_datetime desc, id'
    _rec_name = 'product_id'

    # --- De dónde viene -------------------------------------------------------
    move_id = fields.Many2one(
        'account.move', string='Factura', ondelete='cascade', index=True)
    move_line_id = fields.Many2one(
        'account.move.line', string='Línea de factura', ondelete='cascade', index=True)
    pos_order_id = fields.Many2one(
        'pos.order', string='Orden de POS', ondelete='cascade', index=True)
    pos_order_line_id = fields.Many2one(
        'pos.order.line', string='Línea de POS', ondelete='cascade', index=True)

    # --- Contexto de la venta -------------------------------------------------
    company_id = fields.Many2one(
        'res.company', string='Compañía', required=True, ondelete='cascade', index=True)
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Local', ondelete='set null', index=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Vendedor', ondelete='set null', index=True,
        help='El vendedor de esta línea. En el punto de venta vive en la línea y no en '
             'la orden, y en la contabilidad no existe: por eso se congela acá.')
    session_id = fields.Many2one(
        'pos.session', string='Sesión', ondelete='set null')
    config_id = fields.Many2one(
        'pos.config', string='Caja', ondelete='set null')
    sale_datetime = fields.Datetime(
        string='Fecha y hora de la venta', index=True,
        help='El momento real de la venta. La factura guarda solo el día, así que la '
             'hora se pierde en la contabilidad.')
    sale_date = fields.Date(string='Fecha', index=True)

    # --- Producto -------------------------------------------------------------
    product_id = fields.Many2one(
        'product.product', string='Variante', required=True, ondelete='restrict',
        index=True)
    product_tmpl_id = fields.Many2one(
        'product.template', string='Producto base', ondelete='restrict', index=True)
    product_name = fields.Char(
        string='Descripción', help='El nombre que tenía el producto al venderse.')
    default_code = fields.Char(string='Referencia')

    # --- Atributos congelados -------------------------------------------------
    categ_id = fields.Many2one(
        'product.category', string='Subfamilia', ondelete='set null', index=True,
        help='La categoría que tenía el producto al venderse.')
    categ_parent_id = fields.Many2one(
        'product.category', string='Familia', ondelete='set null', index=True)
    tag_ids = fields.Many2many(
        'product.tag', string='Etiquetas',
        help='Las etiquetas que tenía el producto al venderse.')
    list_price = fields.Float(
        string='Precio de referencia', digits='Product Price',
        help='Precio de lista del producto al momento de la venta, que no es lo mismo '
             'que el precio al que se vendió.')
    standard_price = fields.Float(
        string='Costo', digits='Product Price',
        help='Costo del producto en moneda de la compañía al momento de la venta.')

    # --- Costo en moneda de reportería y de gestión ---------------------------
    cost_report = fields.Float(
        string='Costo MR', digits='Product Price',
        help='Costo unitario en moneda de reportería (el UCMR del producto) al vender.')
    report_currency_id = fields.Many2one(
        'res.currency', string='Moneda de reportería', ondelete='set null')
    management_rate = fields.Float(
        string='TC de gestión', digits=(12, 6),
        help='El tipo de cambio de gestión que estaba vigente ese día. Se guarda para '
             'poder rehacer la cuenta aunque después lo cambien.')
    management_cost = fields.Float(
        string='Costo de gestión', digits='Product Price',
        help='Costo unitario en pesos al cambio de gestión de ese día.')
    management_value = fields.Float(
        string='Costo de gestión total', digits='Product Price',
        help='Cantidad por el costo de gestión unitario.')

    # --- Medidas de la venta --------------------------------------------------
    quantity = fields.Float(string='Cantidad', digits='Product Unit of Measure')
    price_unit = fields.Float(string='Precio unitario', digits='Product Price')
    discount = fields.Float(string='Descuento (%)', digits='Discount')
    price_subtotal = fields.Monetary(string='Subtotal', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', string='Moneda', ondelete='set null')

    # --- Lo declarado en la configuración -------------------------------------
    extra_values = fields.Json(
        string='Otros campos congelados',
        help='Los campos del producto declarados en la configuración, con el valor que '
             'tenían al venderse.')

    _sql_constraints = [
        ('move_line_uniq', 'unique(move_line_id)',
         'Esa línea de factura ya tiene su congelado.'),
        ('pos_line_uniq', 'unique(pos_order_line_id)',
         'Esa línea de punto de venta ya tiene su congelado.'),
    ]

    def init(self):
        """Índice para la lectura típica: un producto en un rango de fechas."""
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS primate_sale_snapshot_date_product_idx
            ON primate_sale_snapshot (sale_date, product_id)
        """)

    # =========================================================================
    # Inmutabilidad
    # =========================================================================
    def write(self, vals):
        """Un congelado no se corrige: se regenera, y solo por el asistente."""
        if not self.env.context.get(REBUILD_CONTEXT):
            raise UserError(_(
                'Un congelado de venta no se modifica: es la foto de cómo estaba el '
                'producto al venderse. Si hay que rehacerlo, usá "Regenerar congelados '
                'de venta".'))
        return super().write(vals)

    def unlink(self):
        """Igual que la escritura: solo el asistente puede borrarlos."""
        if not self.env.context.get(REBUILD_CONTEXT):
            raise UserError(_(
                'Un congelado de venta no se borra a mano. Usá "Regenerar congelados '
                'de venta".'))
        return super().unlink()

    # =========================================================================
    # Construcción
    # =========================================================================
    @api.model
    def _product_values(self, product, company, date):
        """Los atributos del producto tal como están ahora, listos para congelarse."""
        cost_report = product.ultimo_costo_mr or 0.0
        rate = company._get_management_rate(date)
        return {
            'product_id': product.id,
            'product_tmpl_id': product.product_tmpl_id.id,
            'product_name': product.display_name,
            'default_code': product.default_code,
            'categ_id': product.categ_id.id,
            'categ_parent_id': product.categ_id.parent_id.id,
            'tag_ids': [(6, 0, product.product_tag_ids.ids)],
            'list_price': product.lst_price,
            'standard_price': product.standard_price,
            'cost_report': cost_report,
            'report_currency_id': company.monedaDeReporte.id,
            'management_rate': rate,
            'management_cost': cost_report * rate,
            'extra_values': self._extra_values(product),
        }

    @api.model
    def _extra_values(self, product):
        """Lee los campos declarados en la configuración."""
        declared = self.env['primate.snapshot.field'].search([])
        if not declared:
            return {}
        values = {}
        for record in declared:
            # Leer un campo declarado puede fallar contra la base —un related roto,
            # una columna que ya no existe—. Sin savepoint eso aborta la transaccion
            # y el except, que existe justamente para que un campo roto no tumbe la
            # venta, termina tumbandola igual unas capas mas arriba.
            try:
                with self.env.cr.savepoint():
                    values[record.field_id.name] = record._read_value(product)
            except Exception:  # noqa: BLE001 - un campo roto no puede tumbar una venta
                _logger.exception(
                    'No se pudo congelar el campo %s del producto %s',
                    record.field_id.name, product.display_name)
        return values
