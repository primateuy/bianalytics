# -*- coding: utf-8 -*-
"""Tipos de período para comparativos y objetivos (sección 6.1)."""
import logging
from datetime import date, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PrimatePeriodType(models.Model):
    """Tipo de período de análisis.

    El modelo queda abierto a incorporar "zafras" (períodos de duración variable pero
    equivalente entre años) sin rediseñar el motor de comparativos: alcanza con agregar
    un código nuevo y su resolución, porque todo el resto del motor trabaja con el par
    (fecha_desde, fecha_hasta) que devuelve este modelo.
    """
    _name = 'primate.period.type'
    _description = 'Tipo de período'
    _order = 'sequence, id'

    name = fields.Char(string='Nombre', required=True, translate=True)
    code = fields.Selection(
        [('day', 'Día'),
         ('iso_week', 'Semana ISO'),
         ('month', 'Mes'),
         ('quarter', 'Trimestre'),
         ('year', 'Año'),
         ('custom', 'Rango libre')],
        string='Código', required=True, index=True, copy=False)
    sequence = fields.Integer(string='Secuencia', default=10)
    active = fields.Boolean(string='Activo', default=True)
    is_calendar = fields.Boolean(
        string='Calendario puro', default=True,
        help='Sin ajuste por días hábiles, feriados ni calendarios irregulares. '
             'En la Fase 1 todos los tipos de período son de calendario puro.')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Ya existe un tipo de período con ese código.'),
    ]

    def get_period(self, reference_date):
        """Devuelve (desde, hasta) del período que contiene a reference_date.

        Para el tipo 'custom' no hay período derivable de una fecha: el rango lo
        provee quien llama.
        """
        self.ensure_one()
        day = fields.Date.to_date(reference_date)
        if self.code == 'day':
            return day, day
        if self.code == 'iso_week':
            start = day - timedelta(days=day.isoweekday() - 1)
            return start, start + timedelta(days=6)
        if self.code == 'month':
            start = day.replace(day=1)
            return start, self._end_of_month(start)
        if self.code == 'quarter':
            first_month = 3 * ((day.month - 1) // 3) + 1
            start = day.replace(month=first_month, day=1)
            end_month = start.replace(month=first_month + 2)
            return start, self._end_of_month(end_month)
        if self.code == 'year':
            return day.replace(month=1, day=1), day.replace(month=12, day=31)
        raise UserError(_(
            'El tipo de período "%s" no deriva un rango de una fecha; hay que indicar '
            'el rango explícitamente.') % self.name)

    @api.model
    def _end_of_month(self, day):
        """Último día del mes de la fecha dada."""
        if day.month == 12:
            return day.replace(day=31)
        return day.replace(month=day.month + 1, day=1) - timedelta(days=1)

    def shift(self, date_from, date_to, offset):
        """Corre el rango offset períodos hacia atrás (offset negativo) o adelante.

        La semana ISO se corre por semanas completas y el mes/trimestre/año por
        posición de calendario, preservando el día de inicio cuando existe en el
        período destino.
        """
        self.ensure_one()
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        if self.code in ('day', 'custom'):
            span = (date_to - date_from).days + 1
            delta = timedelta(days=span * offset)
            return date_from + delta, date_to + delta
        if self.code == 'iso_week':
            delta = timedelta(weeks=offset)
            return date_from + delta, date_to + delta
        if self.code == 'month':
            start = self._add_months(date_from, offset)
            return start, self._end_of_month(start)
        if self.code == 'quarter':
            start = self._add_months(date_from, 3 * offset)
            return start, self._end_of_month(self._add_months(start, 2))
        if self.code == 'year':
            start = date(date_from.year + offset, date_from.month, 1)
            return start, date(date_from.year + offset, 12, 31)
        return date_from, date_to

    @api.model
    def _add_months(self, day, months):
        """Suma meses a una fecha, recortando el día al último válido del mes destino."""
        total = day.month - 1 + months
        year = day.year + total // 12
        month = total % 12 + 1
        candidate = date(year, month, 1)
        last_day = self._end_of_month(candidate).day
        return date(year, month, min(day.day, last_day))

    def shift_year(self, date_from, date_to, years=1):
        """Devuelve el mismo período del año anterior.

        Para semana ISO usa la semana equivalente del año anterior (no la fecha
        calendario), que es el criterio pedido por la sección 6.1: la semana 22
        contra la semana 22.
        """
        self.ensure_one()
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        if self.code == 'iso_week':
            iso_year, iso_week, _iso_day = date_from.isocalendar()
            target_year = iso_year - years
            start = self._iso_week_start(target_year, iso_week)
            return start, start + timedelta(days=(date_to - date_from).days)
        try:
            start = date(date_from.year - years, date_from.month, date_from.day)
        except ValueError:
            # 29 de febrero contra un año no bisiesto.
            start = date(date_from.year - years, date_from.month, 28)
        span = (date_to - date_from).days
        return start, start + timedelta(days=span)

    @api.model
    def _iso_week_start(self, iso_year, iso_week):
        """Lunes de la semana ISO indicada, acotando semanas 53 inexistentes."""
        try:
            return date.fromisocalendar(iso_year, iso_week, 1)
        except ValueError:
            return date.fromisocalendar(iso_year, 52, 1)
