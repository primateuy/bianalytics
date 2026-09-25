# -*- coding: utf-8 -*-
"""Qué campos del producto se copian al congelar la venta.

Los atributos que el catálogo de métricas usa para desglosar viven en columnas propias
del snapshot: una dimensión tiene que poder agruparse, y para eso necesita una columna.
Todo lo demás que se quiera conservar se declara acá y va al campo genérico, sin tocar
código.
"""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Modelos de los que se puede copiar un campo al snapshot.
ALLOWED_MODELS = ('product.product', 'product.template')

# Tipos que se pueden serializar sin ambigüedad al campo genérico.
ALLOWED_TYPES = ('char', 'text', 'integer', 'float', 'monetary', 'boolean',
                 'date', 'datetime', 'selection', 'many2one')


class PrimateSnapshotField(models.Model):
    _name = 'primate.snapshot.field'
    _description = 'Campo de producto a congelar en la venta'
    _order = 'sequence, id'

    field_id = fields.Many2one(
        'ir.model.fields', string='Campo', required=True, ondelete='cascade',
        domain=[('model', 'in', list(ALLOWED_MODELS)),
                ('ttype', 'in', list(ALLOWED_TYPES))],
        help='Campo del producto cuyo valor se copia al vender.')
    name = fields.Char(
        string='Etiqueta', help='Nombre con el que se muestra. Si se deja vacío se usa '
                                'el del campo.')
    sequence = fields.Integer(string='Secuencia', default=10)
    active = fields.Boolean(string='Activo', default=True)
    notes = fields.Text(string='Notas')

    _sql_constraints = [
        ('field_uniq', 'unique(field_id)',
         'Ese campo ya está declarado para congelarse.'),
    ]

    @api.constrains('field_id')
    def _check_field(self):
        """Solo campos de producto, y de un tipo que se pueda guardar sin ambigüedad."""
        for record in self:
            field = record.field_id
            if field.model not in ALLOWED_MODELS:
                raise ValidationError(_(
                    'Solo se pueden congelar campos del producto. "%(field)s" es de '
                    '%(model)s.') % {'field': field.name, 'model': field.model})
            if field.ttype not in ALLOWED_TYPES:
                raise ValidationError(_(
                    'El campo "%(field)s" es de tipo %(type)s y no se puede guardar en '
                    'el congelado. Si hace falta desglosar por él, necesita una columna '
                    'propia en el snapshot.'
                ) % {'field': field.name, 'type': field.ttype})

    @api.depends('field_id', 'name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = record.name or record.field_id.field_description or ''

    @api.model
    def _get_active_fields(self):
        """Campos declarados, agrupados por el modelo del que se leen."""
        by_model = {}
        for record in self.search([]):
            by_model.setdefault(record.field_id.model, []).append(record)
        return by_model

    def _read_value(self, product):
        """Lee el valor del campo en el producto y lo deja listo para guardar.

        Un many2one se guarda como id y como texto: el id sirve para volver al registro
        y el texto sobrevive aunque el registro se borre o le cambien el nombre, que es
        justamente lo que se está tratando de conservar.
        """
        self.ensure_one()
        field = self.field_id
        record = product if field.model == 'product.product' else product.product_tmpl_id
        if field.name not in record._fields:
            return None
        value = record[field.name]
        if field.ttype == 'many2one':
            return {'id': value.id or False, 'name': value.display_name or ''} \
                if value else {'id': False, 'name': ''}
        if field.ttype in ('date', 'datetime'):
            return fields.Datetime.to_string(value) if value else False
        if field.ttype == 'selection':
            return {'value': value or False,
                    'label': dict(record._fields[field.name]._description_selection(
                        record.env)).get(value, '')}
        return value
