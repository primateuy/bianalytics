# -*- coding: utf-8 -*-
"""Catálogo de dimensiones de desglose y su resolución desde cada modelo origen."""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Columnas typadas disponibles en la tabla de hechos (primate.metric.fact).
# Cada dimensión ocupa exactamente una de estas columnas, así que dos dimensiones
# que usen la misma columna no pueden convivir en un mismo desglose.
FACT_COLUMNS = [
    ('company_id', 'Compañía'),
    ('warehouse_id', 'Local'),
    ('employee_id', 'Vendedor'),
    ('user_id', 'Usuario'),
    ('team_id', 'Equipo comercial'),
    ('categ_id', 'Categoría de producto'),
    ('categ_parent_id', 'Familia (categoría padre)'),
    ('product_tmpl_id', 'Producto base'),
    ('product_id', 'Variante de producto'),
    ('hour_slot', 'Franja horaria'),
    ('weekday', 'Día de la semana'),
]

# Columnas que no guardan un id de registro sino un entero calculado de la fecha.
COMPUTED_COLUMNS = ('hour_slot', 'weekday')


class PrimateMetricDimension(models.Model):
    _name = 'primate.metric.dimension'
    _description = 'Dimensión de desglose de métricas'
    _order = 'sequence, name'

    name = fields.Char(string='Nombre', required=True, translate=True)
    code = fields.Char(string='Código', required=True, index=True, copy=False)
    sequence = fields.Integer(string='Secuencia', default=10)
    active = fields.Boolean(string='Activo', default=True)
    fact_column = fields.Selection(
        FACT_COLUMNS, string='Columna en tabla de hechos', required=True,
        help='Columna de primate.metric.fact donde se guarda esta dimensión.')
    model_name = fields.Char(
        string='Modelo destino',
        help='Modelo de los valores de la dimensión (ej. stock.warehouse). '
             'Vacío para dimensiones calculadas de la fecha.')
    path_ids = fields.One2many(
        'primate.metric.dimension.path', 'dimension_id', string='Rutas de resolución')
    notes = fields.Text(string='Notas')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'El código de la dimensión debe ser único.'),
    ]

    @api.constrains('fact_column', 'model_name')
    def _check_model_name(self):
        """Las dimensiones de registro necesitan modelo; las calculadas, no."""
        for dimension in self:
            is_computed = dimension.fact_column in COMPUTED_COLUMNS
            if is_computed and dimension.model_name:
                raise ValidationError(_(
                    'La dimensión "%s" es calculada de la fecha y no puede tener modelo destino.'
                ) % dimension.name)
            if not is_computed and not dimension.model_name:
                raise ValidationError(_(
                    'La dimensión "%s" necesita un modelo destino.') % dimension.name)

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for dimension in self:
            dimension.display_name = '%s (%s)' % (dimension.name, dimension.code)

    def get_path(self, source_model):
        """Devuelve la ruta de campos para resolver esta dimensión desde source_model.

        Busca primero una ruta exacta para el modelo y, si no existe, ninguna:
        una métrica no puede desglosarse por una dimensión que su modelo origen
        no sabe resolver.
        """
        self.ensure_one()
        path = self.path_ids.filtered(lambda p: p.source_model == source_model)
        return path[:1].field_path or False


class PrimateMetricDimensionPath(models.Model):
    _name = 'primate.metric.dimension.path'
    _description = 'Ruta de resolución de una dimensión desde un modelo origen'
    _order = 'dimension_id, source_model'

    dimension_id = fields.Many2one(
        'primate.metric.dimension', string='Dimensión', required=True,
        ondelete='cascade', index=True)
    source_model = fields.Char(
        string='Modelo origen', required=True, index=True,
        help='Modelo desde el que se agrega la métrica (ej. pos.order.line).')
    field_path = fields.Char(
        string='Ruta de campos', required=True,
        help='Ruta separada por puntos hasta el registro de la dimensión, '
             'ej. order_id.user_id.pad_local_id')

    _sql_constraints = [
        ('dimension_source_uniq', 'unique(dimension_id, source_model)',
         'Ya existe una ruta para esa dimensión y modelo origen.'),
    ]
