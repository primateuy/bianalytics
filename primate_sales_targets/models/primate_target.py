# -*- coding: utf-8 -*-
"""Objetivo concreto de un sujeto en un período."""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

from .primate_target_definition import SUBJECT_TYPES, SUBJECT_LEVELS

# Campo que guarda el sujeto de cada tipo.
SUBJECT_FIELDS = {
    'company': 'subject_company_id',
    'warehouse': 'warehouse_id',
    'employee': 'employee_id',
    'user': 'user_id',
}

_logger = logging.getLogger(__name__)


class PrimateTarget(models.Model):
    _name = 'primate.target'
    _description = 'Objetivo'
    _inherit = ['mail.thread']
    _order = 'date_from desc, id desc'
    _rec_name = 'display_name'

    definition_id = fields.Many2one(
        'primate.target.definition', string='Definición', required=True,
        ondelete='cascade', index=True)
    plan_id = fields.Many2one(
        'primate.target.plan', string='Plan', ondelete='set null', index=True,
        help='Plan que generó este objetivo. Vacío si se cargó a mano.')
    company_id = fields.Many2one(
        'res.company', string='Compañía', ondelete='cascade', index=True,
        default=lambda self: self.env.company)

    subject_type = fields.Selection(
        SUBJECT_TYPES, string='Nivel', compute='_compute_subject_type', store=True,
        readonly=True,
        help='Se deduce del sujeto que tenga cargado. La definición fija el nivel de '
             'arranque, pero al desagregar cada hijo baja un escalón.')
    subject_company_id = fields.Many2one(
        'res.company', string='Compañía objetivo', ondelete='cascade', index=True,
        help='Sujeto del objetivo cuando el nivel es compañía. No confundir con la '
             'compañía dueña del registro.')
    employee_id = fields.Many2one(
        'hr.employee', string='Empleado', ondelete='cascade', index=True)
    user_id = fields.Many2one(
        'res.users', string='Usuario', ondelete='cascade', index=True)
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Local', ondelete='cascade', index=True)

    # --- Árbol -----------------------------------------------------------------
    parent_id = fields.Many2one(
        'primate.target', string='Objetivo padre', ondelete='cascade', index=True,
        help='Objetivo del nivel superior del que se desagregó este.')
    child_ids = fields.One2many('primate.target', 'parent_id', string='Objetivos hijos')
    child_count = fields.Integer(
        string='Hijos', compute='_compute_allocation', store=True)
    child_target_total = fields.Float(
        string='Suma de los hijos', compute='_compute_allocation', store=True,
        help='Total de los objetivos del nivel inferior.')
    allocation_diff = fields.Float(
        string='Descuadre', compute='_compute_allocation', store=True,
        help='Diferencia entre el objetivo y la suma de sus hijos. Solo tiene sentido '
             'cuando la métrica se reparte: en las que bajan igual, cada hijo repite el '
             'valor del padre y sumarlos no significa nada.')
    allocation_mode = fields.Selection(
        related='definition_id.allocation_mode', store=True, readonly=True)

    date_from = fields.Date(string='Desde', required=True, index=True)
    date_to = fields.Date(string='Hasta', required=True, index=True)
    period_label = fields.Char(string='Período', compute='_compute_period_label')

    target_value = fields.Float(string='A alcanzar', required=True)
    current_value = fields.Float(
        string='Valor actual', readonly=True, copy=False,
        help='Último valor leído del motor de métricas. Se refresca con el cron o '
             'con el botón de actualizar.')
    progress = fields.Float(
        string='Avance (%)', compute='_compute_progress', store=True,
        help='Porcentaje del objetivo alcanzado. Vacío cuando el objetivo es cero, '
             'porque no hay avance definible contra un target nulo.')
    last_refresh = fields.Datetime(string='Último refresco', readonly=True, copy=False)
    state = fields.Selection(
        [('draft', 'Borrador'),
         ('open', 'En curso'),
         ('reached', 'Alcanzado'),
         ('missed', 'No alcanzado')],
        string='Estado', default='draft', required=True, tracking=True, copy=False)

    unit_type = fields.Selection(related='definition_id.unit_type', readonly=True)
    digits = fields.Integer(related='definition_id.digits', readonly=True)

    _sql_constraints = [
        ('target_uniq',
         'unique(definition_id, subject_company_id, employee_id, user_id, warehouse_id, '
         'date_from, date_to)',
         'Ya existe un objetivo para ese sujeto y ese período.'),
    ]

    # ------------------------------------------------------------------
    # Sujeto
    # ------------------------------------------------------------------
    @api.depends('subject_company_id', 'warehouse_id', 'employee_id', 'user_id',
                 'definition_id.subject_type')
    def _compute_subject_type(self):
        """Deduce el nivel del objetivo a partir del sujeto que tiene cargado."""
        for target in self:
            for subject_type, field_name in SUBJECT_FIELDS.items():
                if target[field_name]:
                    target.subject_type = subject_type
                    break
            else:
                target.subject_type = target.definition_id.subject_type

    @api.constrains('subject_company_id', 'employee_id', 'user_id', 'warehouse_id')
    def _check_subject(self):
        """Un objetivo apunta a exactamente un sujeto."""
        for target in self:
            filled = [name for name in SUBJECT_FIELDS.values() if target[name]]
            if not filled:
                raise UserError(_(
                    'El objetivo necesita un sujeto: una compañía, un local, un '
                    'empleado o un usuario.'))
            if len(filled) > 1:
                raise UserError(_(
                    'El objetivo tiene más de un sujeto cargado y no se sabe a cuál '
                    'de ellos mide.'))

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for target in self:
            if target.date_from > target.date_to:
                raise ValidationError(_('La fecha de inicio es posterior a la de fin.'))

    def _get_subject(self):
        """Devuelve el registro del sujeto, sea del tipo que sea."""
        self.ensure_one()
        return {
            'company': self.subject_company_id,
            'employee': self.employee_id,
            'user': self.user_id,
            'warehouse': self.warehouse_id,
        }.get(self.subject_type, self.env['hr.employee'])

    @api.depends('employee_id', 'user_id', 'warehouse_id', 'subject_company_id',
                 'definition_id.name',
                 'date_from', 'date_to')
    def _compute_display_name(self):
        for target in self:
            subject = target._get_subject()
            target.display_name = '%s · %s · %s' % (
                target.definition_id.name or '',
                subject.display_name if subject else _('sin sujeto'),
                target.date_from or '')

    @api.depends('date_from', 'date_to', 'definition_id.period_type_id')
    def _compute_period_label(self):
        """Reusa la etiqueta de período del dashboard para no tener dos formatos."""
        dashboard_model = self.env['primate.dashboard']
        for target in self:
            target.period_label = dashboard_model._period_label(
                target.definition_id.period_type_id, target.date_from, target.date_to)

    # ------------------------------------------------------------------
    # Avance
    # ------------------------------------------------------------------
    @api.depends('current_value', 'target_value', 'definition_id.direction')
    def _compute_progress(self):
        """Porcentaje de avance, con el sentido que declara la definición.

        En los objetivos de "no superar" el avance se lee al revés: estar en cero es
        cumplir al 100 % y pasarse del target lo lleva por debajo de cero.
        """
        for target in self:
            if not target.target_value:
                target.progress = 0.0
                continue
            if target.definition_id.direction == 'below':
                remaining = target.target_value - target.current_value
                target.progress = remaining / target.target_value * 100.0
            else:
                target.progress = target.current_value / target.target_value * 100.0

    def _build_filters(self):
        """Traduce el sujeto del objetivo a un filtro del motor de métricas.

        El usuario se resuelve por su empleado, que es la relación estándar de Odoo:
        el motor corta por empleado, no por usuario, porque es ahí donde vive el dato
        del vendedor.

        Deliberadamente NO se filtra por compañía: el sujeto ya define el corte, y en
        una instalación multiempresa un mismo local puede pertenecer a una compañía
        pero registrar sus ventas bajo otra. Filtrar por la compañía del objetivo
        dejaría ese local en cero.
        """
        self.ensure_one()
        empty = {key: [] for key in (
            'company_ids', 'warehouse_ids', 'employee_ids', 'team_ids',
            'categ_ids', 'product_tmpl_ids', 'product_ids')}
        if self.subject_type == 'company':
            # Una compañía con hijas representa al grupo: incluye a toda su rama.
            empty['company_ids'] = self._company_branch().ids
        elif self.subject_type == 'employee':
            empty['employee_ids'] = self.employee_id.ids
        elif self.subject_type == 'warehouse':
            empty['warehouse_ids'] = self.warehouse_id.ids
        elif self.subject_type == 'user':
            employee = self.env['hr.employee'].search(
                [('user_id', '=', self.user_id.id)], limit=1)
            if not employee:
                raise UserError(_(
                    'El usuario "%s" no tiene un empleado asociado, así que no se '
                    'puede leer su avance: el motor corta por empleado.'
                ) % self.user_id.display_name)
            empty['employee_ids'] = employee.ids
        return empty

    # ------------------------------------------------------------------
    # Árbol: desagregación hacia el nivel inferior
    # ------------------------------------------------------------------
    @api.depends('child_ids.target_value', 'target_value', 'allocation_mode')
    def _compute_allocation(self):
        """Calcula el cuadre entre el objetivo y la suma de sus hijos."""
        for target in self:
            children = target.child_ids
            target.child_count = len(children)
            total = sum(children.mapped('target_value'))
            target.child_target_total = total
            # En el modo "baja igual" los hijos repiten el valor del padre, así que
            # sumarlos no significa nada y no hay descuadre que informar.
            target.allocation_diff = (
                target.target_value - total
                if children and target.allocation_mode == 'distribute' else 0.0)

    def _company_branch(self):
        """Compañías que representa el objetivo: la propia y toda su descendencia."""
        self.ensure_one()
        company = self.subject_company_id
        if not company:
            return self.env['res.company']
        return company + self.env['res.company'].search(
            [('id', 'child_of', company.id), ('id', '!=', company.id)])

    def _next_level_subjects(self):
        """Devuelve los grupos (tipo de sujeto, registros) del nivel inferior.

        Devuelve una lista porque una compañía puede ser las dos cosas a la vez: cabeza
        de grupo y empresa que opera. FORUM es el caso: tiene cinco compañías hijas y
        además cuarenta y un locales propios. Si bajara solo a las hijas, esos locales
        quedarían fuera del árbol y la suma nunca cerraría.

        Un local baja a los empleados que lo declaran como sucursal de objetivos. Un
        empleado es hoja.
        """
        self.ensure_one()
        if self.subject_type == 'company':
            company = self.subject_company_id
            groups = []
            children = self.env['res.company'].search([('parent_id', '=', company.id)])
            if children:
                groups.append(('company', children))
            # Por compañía COMERCIAL, no por dueña del almacén: en el esquema de
            # franquicias el local es de la casa central pero lo factura el
            # franquiciado, y colgarlo del dueño del stock duplicaría sus ventas.
            own = self.env['stock.warehouse'].search(
                [('target_company_id', '=', company.id)])
            if own:
                groups.append(('warehouse', own))
            return groups
        if self.subject_type == 'warehouse':
            employees = self.env['hr.employee'].search(
                [('target_warehouse_id', '=', self.warehouse_id.id)])
            return [('employee', employees)] if employees else []
        return []

    def _history_weights(self, subject_type, subjects):
        """Pesos de reparto según lo que aportó cada sujeto el año anterior.

        Se lee del motor con la misma versión de métrica del objetivo, sobre el mismo
        período del año pasado. Si no hay histórico —un local nuevo, un catálogo recién
        cargado— se reparte en partes iguales, que es lo único defendible sin datos.
        """
        self.ensure_one()
        period_type = self.definition_id.period_type_id
        date_from, date_to = period_type.shift_year(self.date_from, self.date_to, 1)
        version = self.definition_id.get_version()
        engine = self.env['primate.metric.engine']
        weights = {}
        for subject in subjects:
            probe = self.new({
                'definition_id': self.definition_id.id,
                'company_id': self.company_id.id,
                SUBJECT_FIELDS[subject_type]: subject.id,
                'date_from': date_from, 'date_to': date_to,
                'target_value': 1.0,
            })
            probe.subject_type = subject_type
            try:
                rows = engine.compute(version, date_from, date_to,
                                      filters=probe._build_filters())
                weights[subject.id] = max(rows[0]['value'], 0.0) if rows else 0.0
            except UserError:
                weights[subject.id] = 0.0
        if not sum(weights.values()):
            weights = {subject.id: 1.0 for subject in subjects}
        return weights

    def action_allocate(self):
        """Crea o actualiza los objetivos del nivel inferior.

        El valor propuesto se precarga —ponderado por histórico si la métrica se
        reparte, o repitiendo el valor del padre si baja igual— y después queda
        editable: el descuadre contra el padre se muestra pero no se impone, porque el
        ajuste fino de una meta es una decisión de negocio.

        Es idempotente: los hijos que ya existen conservan el valor que tengan.
        """
        created = 0
        for target in self:
            groups = target._next_level_subjects()
            if not groups:
                raise UserError(_(
                    'El objetivo "%s" no tiene un nivel inferior al que desagregarse. '
                    'Si es una meta de local, revisá que los empleados tengan cargada '
                    'su sucursal de objetivos.') % target.display_name)

            # El reparto ponderado se calcula sobre TODOS los sujetos del nivel a la vez,
            # aunque sean de tipos distintos: si el grupo baja a cinco empresas más sus
            # propios locales, los seis compiten por la misma bolsa.
            pending_by_type = {}
            for subject_type, subjects in groups:
                field = SUBJECT_FIELDS[subject_type]
                existing = {child[field].id for child in target.child_ids
                            if child.subject_type == subject_type}
                pending = subjects.filtered(lambda s: s.id not in existing)
                if pending:
                    pending_by_type[subject_type] = pending
            if not pending_by_type:
                continue

            if target.definition_id.allocation_mode == 'inherit':
                values = {(t, s.id): target.target_value
                          for t, subs in pending_by_type.items() for s in subs}
            else:
                weights = {}
                for subject_type, subjects in pending_by_type.items():
                    for subject_id, weight in target._history_weights(
                            subject_type, subjects).items():
                        weights[(subject_type, subject_id)] = weight
                total_weight = sum(weights.values()) or 1.0
                values = {key: target.target_value * weight / total_weight
                          for key, weight in weights.items()}

            values_list = []
            for subject_type, subjects in pending_by_type.items():
                for subject in subjects:
                    values_list.append({
                        'definition_id': target.definition_id.id,
                        'plan_id': target.plan_id.id,
                        'parent_id': target.id,
                        'company_id': target.company_id.id,
                        SUBJECT_FIELDS[subject_type]: subject.id,
                        'date_from': target.date_from,
                        'date_to': target.date_to,
                        'target_value': values[(subject_type, subject.id)],
                    })
            self.create(values_list)
            created += len(values_list)
        _logger.info('Desagregación: %s objetivos creados', created)
        return True

    def action_view_children(self):
        """Abre los objetivos que cuelgan de este."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Desagregación de %s') % self.display_name,
            'res_model': 'primate.target',
            'view_mode': 'tree,form',
            'domain': [('parent_id', '=', self.id)],
        }

    def action_refresh(self):
        """Relee el valor actual desde el motor de métricas."""
        engine = self.env['primate.metric.engine']
        now = fields.Datetime.now()
        for target in self:
            version = target.definition_id.get_version()
            if not version:
                raise UserError(_(
                    'La métrica de "%s" no tiene ninguna versión aplicable.'
                ) % target.definition_id.name)
            rows = engine.compute(
                version, target.date_from, target.date_to,
                filters=target._build_filters())
            target.current_value = rows[0]['value'] if rows else 0.0
            target.last_refresh = now
            target._update_state()
        return True

    def _update_state(self):
        """Mueve el estado según el avance y si el período ya cerró.

        Un objetivo en curso no se marca como no alcanzado hasta que el período
        termina: antes de eso todavía puede cumplirse.
        """
        today = fields.Date.context_today(self)
        for target in self:
            if target.state == 'draft':
                continue
            reached = target.progress >= 100.0
            if reached:
                target.state = 'reached'
            elif target.date_to < today:
                target.state = 'missed'
            else:
                target.state = 'open'

    def action_start(self):
        """Pone el objetivo en curso y trae su primer valor."""
        self.write({'state': 'open'})
        self.action_refresh()
        return True

    def action_reset(self):
        self.write({'state': 'draft'})
        return True

    @api.model
    def _cron_refresh_targets(self):
        """Refresca los objetivos vigentes y los que acaban de cerrar.

        Se limita a los que están en curso: los borradores todavía no cuentan y los
        ya resueltos no cambian salvo que se los reabra a mano.
        """
        targets = self.search([('state', '=', 'open')])
        _logger.info('Refrescando %s objetivos en curso', len(targets))
        for target in targets:
            try:
                target.action_refresh()
            except UserError as error:
                _logger.warning('No se pudo refrescar el objetivo %s: %s',
                                target.display_name, error)
        return True
