# -*- coding: utf-8 -*-
"""Definición de objetivo: qué se persigue, con qué grano y sobre qué sujeto."""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Tipos de sujeto sobre los que se puede fijar un objetivo. Cada uno se traduce a un
# filtro del motor de métricas, así el avance sale de la misma tabla de hechos que
# alimenta al dashboard.
SUBJECT_TYPES = [
    ('company', 'Compañía'),
    ('warehouse', 'Local'),
    ('employee', 'Empleado'),
    ('user', 'Usuario'),
]

# Orden de desagregación del árbol. Una compañía con compañías hijas baja a ellas;
# una compañía sin hijas baja a sus locales; un local baja a sus vendedores.
SUBJECT_LEVELS = ['company', 'warehouse', 'employee']


class PrimateTargetDefinition(models.Model):
    _name = 'primate.target.definition'
    _description = 'Definición de objetivo'
    _order = 'sequence, name'

    name = fields.Char(string='Nombre', required=True, translate=True)
    code = fields.Char(string='Código', required=True, index=True, copy=False)
    sequence = fields.Integer(string='Secuencia', default=10)
    active = fields.Boolean(string='Activo', default=True)
    description = fields.Text(string='Descripción')
    company_id = fields.Many2one(
        'res.company', string='Compañía', ondelete='cascade', index=True,
        help='Vacío = aplica a todas las compañías.')

    metric_id = fields.Many2one(
        'primate.metric', string='Métrica', required=True, ondelete='restrict',
        help='Métrica cuyo valor se persigue. El avance se lee del motor, no se '
             'recalcula por separado.')
    metric_version_id = fields.Many2one(
        'primate.metric.version', string='Versión fija', ondelete='restrict',
        help='Fija una versión concreta de la métrica. Vacío = se sigue la versión '
             'vigente de la compañía, igual que en los dashboards.')
    period_type_id = fields.Many2one(
        'primate.period.type', string='Grano del objetivo', required=True,
        ondelete='restrict',
        help='Período que cubre cada objetivo: uno por día, por semana, por mes…')
    subject_type = fields.Selection(
        SUBJECT_TYPES, string='Tipo de sujeto', required=True, default='employee')
    allocation_mode = fields.Selection(
        [('distribute', 'Se reparte entre los hijos'),
         ('inherit', 'Baja igual a cada hijo')],
        string='Modo de reparto', default='distribute', required=True,
        help='Se reparte: el objetivo del padre se divide entre sus hijos y la suma de '
             'los hijos tiene que dar el total del padre. Es lo que corresponde a las '
             'métricas que se suman (ventas, unidades, boletas).\n'
             'Baja igual: cada hijo recibe el mismo valor que el padre. Es lo que '
             'corresponde a los promedios y ratios: el ticket promedio de una sucursal '
             'no es la suma de los tickets de sus vendedores, así que repartirlo por '
             'división daría metas sin sentido.')
    direction = fields.Selection(
        [('above', 'Alcanzar o superar'), ('below', 'No superar')],
        string='Sentido', default='above', required=True,
        help='Alcanzar o superar: el objetivo se cumple cuando el valor llega al '
             'target. No superar: se cumple mientras el valor se mantenga por debajo, '
             'que es lo que corresponde a métricas donde menos es mejor.')

    @api.onchange('metric_id')
    def _onchange_metric_id(self):
        """Propone el modo de reparto según el tipo de métrica.

        Un ratio nunca se reparte por división, así que se propone heredar. Queda
        editable porque el criterio final es de negocio.
        """
        for definition in self:
            version = definition.metric_version_id or definition.metric_id.version_ids[:1]
            if version and version.calc_type == 'ratio':
                definition.allocation_mode = 'inherit'
            elif definition.metric_id:
                definition.allocation_mode = 'distribute'

    unit_type = fields.Selection(related='metric_id.unit_type', readonly=True)
    digits = fields.Integer(related='metric_id.digits', readonly=True)
    target_count = fields.Integer(
        string='Objetivos', compute='_compute_target_count')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Ya existe una definición de objetivo con ese código.'),
    ]

    @api.constrains('metric_version_id', 'metric_id')
    def _check_version(self):
        """La versión fija tiene que pertenecer a la métrica elegida."""
        for definition in self:
            version = definition.metric_version_id
            if version and version.metric_id != definition.metric_id:
                raise ValidationError(_(
                    'La versión fija de "%s" pertenece a otra métrica.') % definition.name)

    def _compute_target_count(self):
        data = self.env['primate.target']._read_group(
            [('definition_id', 'in', self.ids)], ['definition_id'], ['__count'])
        mapped = {definition.id: count for definition, count in data}
        for definition in self:
            definition.target_count = mapped.get(definition.id, 0)

    def get_version(self):
        """Resuelve la versión de métrica que usa la definición.

        Igual criterio que los componentes de dashboard: la versión fija manda, y si
        no hay se sigue la vigente de la compañía.
        """
        self.ensure_one()
        if self.metric_version_id:
            return self.metric_version_id
        company = self.company_id or self.env.company
        return self.metric_id.get_version(company)

    def action_view_targets(self):
        """Abre los objetivos generados a partir de esta definición."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Objetivos'),
            'res_model': 'primate.target',
            'view_mode': 'tree,form',
            'domain': [('definition_id', '=', self.id)],
            'context': {'default_definition_id': self.id},
        }
