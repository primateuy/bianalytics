# -*- coding: utf-8 -*-
"""La moneda que lleva el tipo de cambio de gestión y su resolución a una fecha."""
import logging

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

# Moneda con la que sale configurado el tipo de cambio de gestión si existe en la base.
DEFAULT_MANAGEMENT_CURRENCY = 'USG'


class ResCompany(models.Model):
    _inherit = 'res.company'

    management_currency_id = fields.Many2one(
        'res.currency', string='Moneda de gestión', ondelete='restrict',
        help='Moneda cuyas cotizaciones lleva el tipo de cambio de gestión, el que fija '
             'la empresa a mano y sostiene en el tiempo. No es la cotización del '
             'mercado: es la que usan para razonar el costo.')

    def _get_management_rate(self, date=None):
        """Unidades de moneda de la compañía por una unidad de moneda de gestión.

        Es el número con el que la empresa piensa: 45 pesos por dólar de gestión. Sale
        de la última cotización vigente a la fecha, así que una venta vieja se convierte
        con el tipo de cambio que estaba en pie ese día y no con el de hoy.

        Devuelve 0.0 cuando no hay moneda de gestión o no hay cotización, para que quien
        llama decida qué hacer en lugar de recibir un número inventado.
        """
        self.ensure_one()
        if not self.management_currency_id:
            return 0.0
        date = date or fields.Date.context_today(self)
        rate = self.env['res.currency.rate'].sudo().search([
            ('currency_id', '=', self.management_currency_id.id),
            ('name', '<=', date),
            '|', ('company_id', '=', self.id), ('company_id', '=', False),
        ], order='name desc, company_id', limit=1)
        if not rate or not rate.rate:
            return 0.0
        # La cotización se guarda como unidades de la moneda por unidad de la moneda de
        # la compañía; acá interesa el camino inverso.
        return 1.0 / rate.rate

    def _convert_report_to_management(self, amount, date=None):
        """Lleva un importe en moneda de reportería a pesos al cambio de gestión."""
        self.ensure_one()
        if not amount:
            return 0.0
        return amount * self._get_management_rate(date)


def post_init_hook(env):
    """Deja apuntada la moneda de gestión a USG en las compañías que aún no la tienen.

    Se resuelve por nombre una sola vez, en la instalación: de ahí en adelante es un
    campo que se configura, no una convención escondida en el código.
    """
    currency = env['res.currency'].with_context(active_test=False).search(
        [('name', '=', DEFAULT_MANAGEMENT_CURRENCY)], limit=1)
    if not currency:
        _logger.warning(
            'No existe la moneda %s: la moneda de gestión queda sin configurar.',
            DEFAULT_MANAGEMENT_CURRENCY)
        return
    companies = env['res.company'].search([('management_currency_id', '=', False)])
    companies.management_currency_id = currency
    _logger.info(
        'Moneda de gestión %s asignada a %s compañías.', currency.name, len(companies))
