# -*- coding: utf-8 -*-
"""Versión inmutable de una métrica (secciones 5.1, 5.2 y 5.3)."""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Campos que definen el cálculo. Una vez confirmada la versión son inmutables:
# cambiarlos exige crear una versión nueva (sección 5.3).
CALCULATION_FIELDS = (
    'calc_type', 'source_model', 'value_field', 'aggregation', 'distinct_field',
    'domain', 'date_field', 'refund_treatment', 'refund_field', 'ratio_mode',
    'numerator_version_id', 'denominator_version_id', 'company_id',
)

AGGREGATIONS = [
    ('sum', 'Suma'),
    ('count', 'Conteo'),
    ('count_distinct', 'Conteo de valores distintos'),
    ('avg', 'Promedio'),
    ('min', 'Mínimo'),
    ('max', 'Máximo'),
]


class PrimateMetricVersion(models.Model):
    _name = 'primate.metric.version'
    _description = 'Versión de métrica'
    _inherit = ['mail.thread']
    _order = 'metric_id, version desc'
    _rec_name = 'display_name'

    metric_id = fields.Many2one(
        'primate.metric', string='Métrica', required=True, ondelete='cascade', index=True)
    version = fields.Integer(string='Versión', default=1, required=True, copy=False)
    state = fields.Selection(
        [('draft', 'Borrador'), ('confirmed', 'Confirmada'), ('archived', 'Archivada')],
        string='Estado', default='draft', required=True, copy=False, tracking=True,
        help='Borrador: definición provisoria, usable pero pendiente de confirmación. '
             'Confirmada: definición cerrada e inmutable.')
    company_id = fields.Many2one(
        'res.company', string='Compañía', ondelete='cascade', index=True,
        help='Vacío = definición base compartida. Con valor = override para esa compañía.')
    gap_ref = fields.Char(
        string='Gap', index=True, tracking=True,
        help='Identificador del gap de negocio que mantiene provisoria esta definición '
             '(ej. G-01). Permite listar en bloque lo que falta confirmar.')

    # --- Definición del cálculo -------------------------------------------------
    calc_type = fields.Selection(
        [('simple', 'Simple'), ('ratio', 'Ratio')],
        string='Tipo de cálculo', default='simple', required=True)
    source_model = fields.Char(
        string='Modelo origen',
        help='Modelo transaccional desde el que se agrega (ej. pos.order.line).')
    value_field = fields.Char(
        string='Campo de valor',
        help='Campo numérico a agregar. Vacío cuando la agregación es un conteo.')
    aggregation = fields.Selection(
        AGGREGATIONS, string='Agregación', default='sum')
    distinct_field = fields.Char(
        string='Campo para distintos',
        help='Campo por el que se cuentan valores distintos (ej. order_id para boletas).')
    domain = fields.Char(string='Dominio', default='[]')
    date_field = fields.Char(
        string='Campo de fecha',
        help='Campo fecha/datetime que define a qué día se imputa el hecho.')
    dimension_ids = fields.Many2many(
        'primate.metric.dimension', string='Dimensiones permitidas',
        help='Dimensiones por las que esta métrica puede desglosarse. Una métrica de '
             'inventario, por ejemplo, no admite la dimensión vendedor.')

    # --- Devoluciones -----------------------------------------------------------
    refund_treatment = fields.Selection(
        [('include', 'Incluir'), ('exclude', 'Excluir'), ('only', 'Solo devoluciones')],
        string='Tratamiento de devoluciones', default='include', required=True)
    refund_field = fields.Char(
        string='Campo de devolución',
        help='Campo booleano o relacional que marca el registro como devolución '
             '(ej. refunded_orderline_id).')

    # --- Ratio (sección 5.1) ----------------------------------------------------
    ratio_mode = fields.Selection(
        [('aggregate_divide', 'Agregado y dividir'), ('average_rows', 'Promedio de filas')],
        string='Modo de cálculo del ratio', default='aggregate_divide',
        help='Agregado y dividir: se suman numerador y denominador del grupo y se divide '
             'al final (estándar en BI). Promedio de filas: se calcula el ratio fila a '
             'fila y se promedia (estadísticamente sesgado).')
    numerator_version_id = fields.Many2one(
        'primate.metric.version', string='Numerador', ondelete='restrict')
    denominator_version_id = fields.Many2one(
        'primate.metric.version', string='Denominador', ondelete='restrict')

    notes = fields.Text(string='Notas')
    fact_count = fields.Integer(string='Hechos precalculados', compute='_compute_fact_count')

    _sql_constraints = [
        ('metric_version_company_uniq', 'unique(metric_id, version, company_id)',
         'Ya existe esa versión de la métrica para esa compañía.'),
    ]

    @api.depends('metric_id.name', 'version', 'company_id', 'state')
    def _compute_display_name(self):
        for version in self:
            suffix = version.company_id.name or _('base')
            version.display_name = '%s · v%s (%s)' % (
                version.metric_id.name or '', version.version, suffix)

    def _compute_fact_count(self):
        """Cuenta los hechos precalculados de cada versión."""
        fact_model = self.env['primate.metric.fact']
        data = fact_model._read_group(
            [('metric_version_id', 'in', self.ids)], ['metric_version_id'], ['__count'])
        mapped = {version.id: count for version, count in data}
        for version in self:
            version.fact_count = mapped.get(version.id, 0)

    @api.constrains('calc_type', 'source_model', 'aggregation', 'numerator_version_id',
                    'denominator_version_id', 'distinct_field', 'date_field',
                    'refund_field', 'refund_treatment')
    def _check_definition(self):
        """Valida que la definición sea completa según el tipo de cálculo."""
        for version in self:
            if version.calc_type == 'ratio':
                if not (version.numerator_version_id and version.denominator_version_id):
                    raise ValidationError(_(
                        'La métrica ratio "%s" necesita numerador y denominador.'
                    ) % version.display_name)
                if version.numerator_version_id == version or \
                        version.denominator_version_id == version:
                    raise ValidationError(_(
                        'Una métrica ratio no puede referenciarse a sí misma.'))
                continue
            if not version.source_model:
                raise ValidationError(_(
                    'La métrica "%s" necesita un modelo origen.') % version.display_name)
            if version.source_model not in self.env:
                raise ValidationError(_(
                    'El modelo origen "%s" no existe.') % version.source_model)
            if not version.date_field:
                raise ValidationError(_(
                    'La métrica "%s" necesita un campo de fecha para el grano diario.'
                ) % version.display_name)
            if version.aggregation == 'count_distinct' and not version.distinct_field:
                raise ValidationError(_(
                    'La métrica "%s" cuenta valores distintos y necesita el campo por el '
                    'cual contarlos.') % version.display_name)
            if version.refund_field and version.refund_treatment != 'include':
                refund = self.env['primate.metric.fact']._get_field_by_path(
                    self.env[version.source_model], version.refund_field)
                if not refund:
                    raise ValidationError(_(
                        'El campo de devolución "%(field)s" no existe en %(model)s.'
                    ) % {'field': version.refund_field, 'model': version.source_model})
                if not refund.store:
                    raise ValidationError(_(
                        'El campo de devolución "%(field)s" no es almacenado, así que no se '
                        'puede filtrar por él. Usá un campo almacenado equivalente (por '
                        'ejemplo lines.refunded_orderline_id en lugar de is_refunded).'
                    ) % {'field': version.refund_field})
            if version.aggregation not in ('count', 'count_distinct') and not version.value_field:
                raise ValidationError(_(
                    'La métrica "%s" necesita un campo de valor para agregar.'
                ) % version.display_name)

    def write(self, vals):
        """Impide alterar el cálculo de una versión ya confirmada (sección 5.3)."""
        touched = set(vals) & set(CALCULATION_FIELDS)
        if touched:
            frozen = self.filtered(lambda v: v.state == 'confirmed')
            if frozen and vals.get('state') != 'draft':
                raise UserError(_(
                    'La versión "%s" está confirmada y su definición es inmutable. '
                    'Usá "Nueva versión" para cambiar el cálculo sin alterar los '
                    'dashboards que ya la usan.'
                ) % frozen[0].display_name)
        return super().write(vals)

    def action_confirm(self):
        """Confirma la versión, congelando su definición y su modo de cálculo."""
        for version in self:
            if version.state != 'draft':
                raise UserError(_('Solo se puede confirmar una versión en borrador.'))
        self.write({'state': 'confirmed'})
        return True

    def action_new_version(self):
        """Crea una versión nueva en borrador a partir de esta.

        Los consumidores existentes siguen apuntando a la versión anterior hasta que
        se los actualice explícitamente (sección 5.3).
        """
        self.ensure_one()
        last = self.search(
            [('metric_id', '=', self.metric_id.id), ('company_id', '=', self.company_id.id)],
            order='version desc', limit=1)
        new_version = self.copy({
            'version': (last.version or self.version) + 1,
            'state': 'draft',
        })
        new_version.message_post(body=_('Versión creada a partir de %s.') % self.display_name)
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': new_version.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_archive_version(self):
        """Archiva la versión sin borrar sus hechos precalculados."""
        self.write({'state': 'archived'})
        return True

    # --- Utilidades para el motor ----------------------------------------------
    def get_dimension(self, code):
        """Devuelve la dimensión permitida con ese código, o un recordset vacío."""
        self.ensure_one()
        return self.dimension_ids.filtered(lambda d: d.code == code)[:1]

    def get_refund_domain(self):
        """Traduce el tratamiento de devoluciones a un dominio adicional."""
        self.ensure_one()
        if not self.refund_field or self.refund_treatment == 'include':
            return []
        if self.refund_treatment == 'exclude':
            return [(self.refund_field, '=', False)]
        return [(self.refund_field, '!=', False)]
