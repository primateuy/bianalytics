# -*- coding: utf-8 -*-
"""Plan de objetivos: asignación masiva por sujeto y por período.

Es el equivalente al "reto" de gamificación: en lugar de cargar un objetivo por
persona y por mes a mano, se declara una vez el conjunto de sujetos, el rango y el
valor a alcanzar, y el plan genera un objetivo por cada combinación.
"""
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

from .primate_target import SUBJECT_FIELDS

_logger = logging.getLogger(__name__)


class PrimateTargetPlan(models.Model):
    _name = 'primate.target.plan'
    _description = 'Plan de objetivos'
    _inherit = ['mail.thread']
    _order = 'date_start desc, id desc'

    name = fields.Char(string='Nombre', required=True, translate=True)
    definition_id = fields.Many2one(
        'primate.target.definition', string='Definición', required=True,
        ondelete='restrict', index=True)
    subject_type = fields.Selection(
        related='definition_id.subject_type', store=True, readonly=True)
    period_type_id = fields.Many2one(
        related='definition_id.period_type_id', readonly=True)
    company_id = fields.Many2one(
        'res.company', string='Compañía', ondelete='cascade', index=True,
        default=lambda self: self.env.company)

    date_start = fields.Date(string='Desde', required=True)
    date_end = fields.Date(string='Hasta', required=True)
    default_target = fields.Float(
        string='Objetivo por defecto',
        help='Valor que se asigna a los sujetos que no tengan una línea propia.')

    company_target_ids = fields.Many2many(
        'res.company', 'primate_target_plan_subject_company_rel',
        string='Compañías objetivo')
    employee_ids = fields.Many2many('hr.employee', string='Empleados')
    user_ids = fields.Many2many('res.users', string='Usuarios')
    warehouse_ids = fields.Many2many('stock.warehouse', string='Locales')
    line_ids = fields.One2many(
        'primate.target.plan.line', 'plan_id', string='Objetivos por sujeto',
        help='Valor propio para un sujeto. Lo que no esté acá usa el objetivo por defecto.')

    target_ids = fields.One2many('primate.target', 'plan_id', string='Objetivos generados')
    target_count = fields.Integer(string='Generados', compute='_compute_target_count')
    state = fields.Selection(
        [('draft', 'Borrador'), ('running', 'Vigente'), ('done', 'Cerrado')],
        string='Estado', default='draft', required=True, tracking=True, copy=False)

    @api.depends('target_ids')
    def _compute_target_count(self):
        for plan in self:
            plan.target_count = len(plan.target_ids)

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for plan in self:
            if plan.date_start > plan.date_end:
                raise ValidationError(_('La fecha de inicio es posterior a la de fin.'))

    def _get_subjects(self):
        """Sujetos alcanzados por el plan, según el tipo que declara la definición."""
        self.ensure_one()
        return {
            'company': self.company_target_ids,
            'employee': self.employee_ids,
            'user': self.user_ids,
            'warehouse': self.warehouse_ids,
        }.get(self.subject_type, self.env['hr.employee'])

    def _iter_periods(self):
        """Recorre los períodos del grano del plan dentro del rango.

        Corta cuando el período generado deja de avanzar, que es lo que evita un
        bucle infinito si un tipo de período no sabe correrse.
        """
        self.ensure_one()
        period_type = self.definition_id.period_type_id
        if period_type.code == 'custom':
            # El rango libre no se subdivide: el plan entero es un solo objetivo.
            yield self.date_start, self.date_end
            return
        date_from, date_to = period_type.get_period(self.date_start)
        while date_from <= self.date_end:
            yield date_from, date_to
            next_from, next_to = period_type.shift(date_from, date_to, 1)
            if next_from <= date_from:
                break
            date_from, date_to = next_from, next_to

    def _target_value_for(self, subject):
        """Valor a alcanzar de un sujeto: su línea propia, o el valor por defecto."""
        self.ensure_one()
        line = self.line_ids.filtered(lambda l: l._get_subject() == subject)
        return line[0].target_value if line else self.default_target

    def action_generate(self):
        """Genera un objetivo por sujeto y por período.

        Es idempotente: los objetivos que ya existen se dejan como están, para no
        pisar un valor ajustado a mano ni perder el avance ya registrado.
        """
        target_model = self.env['primate.target']
        field_by_type = SUBJECT_FIELDS
        created = 0
        for plan in self:
            subjects = plan._get_subjects()
            if not subjects:
                raise UserError(_(
                    'El plan "%s" no tiene ningún sujeto al que asignarle objetivos.'
                ) % plan.name)
            subject_field = field_by_type[plan.subject_type]
            existing = {
                (target[subject_field].id, target.date_from, target.date_to)
                for target in plan.target_ids
            }
            values_list = []
            for date_from, date_to in plan._iter_periods():
                for subject in subjects:
                    if (subject.id, date_from, date_to) in existing:
                        continue
                    values_list.append({
                        'definition_id': plan.definition_id.id,
                        'plan_id': plan.id,
                        'company_id': plan.company_id.id,
                        subject_field: subject.id,
                        'date_from': date_from,
                        'date_to': date_to,
                        'target_value': plan._target_value_for(subject),
                    })
            if values_list:
                target_model.create(values_list)
                created += len(values_list)
            plan.state = 'running'
        _logger.info('Plan de objetivos: %s objetivos creados', created)
        return True

    def action_start_targets(self):
        """Pone en curso todos los objetivos del plan y trae su avance."""
        self.ensure_one()
        self.target_ids.filtered(lambda t: t.state == 'draft').action_start()
        return True

    def action_close(self):
        self.write({'state': 'done'})
        return True

    def action_view_targets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Objetivos del plan'),
            'res_model': 'primate.target',
            'view_mode': 'tree,form',
            'domain': [('plan_id', '=', self.id)],
        }


class PrimateTargetPlanLine(models.Model):
    _name = 'primate.target.plan.line'
    _description = 'Objetivo por sujeto del plan'

    plan_id = fields.Many2one(
        'primate.target.plan', string='Plan', required=True, ondelete='cascade', index=True)
    subject_type = fields.Selection(related='plan_id.subject_type', readonly=True)
    company_target_id = fields.Many2one(
        'res.company', string='Compañía objetivo', ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='Empleado', ondelete='cascade')
    user_id = fields.Many2one('res.users', string='Usuario', ondelete='cascade')
    warehouse_id = fields.Many2one('stock.warehouse', string='Local', ondelete='cascade')
    target_value = fields.Float(string='A alcanzar', required=True)

    def _get_subject(self):
        """Devuelve el registro del sujeto de la línea."""
        self.ensure_one()
        return {
            'company': self.company_target_id,
            'employee': self.employee_id,
            'user': self.user_id,
            'warehouse': self.warehouse_id,
        }.get(self.subject_type, self.env['hr.employee'])
