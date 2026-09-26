# -*- coding: utf-8 -*-
"""Costo de gestión y existencia valorizada en el reporte de existencias.

El reporte de tchistorico es una vista SQL, así que las columnas nuevas se suman en las
agrupaciones sin que haya que hacer nada: el agrupado lo resuelve Postgres. Por eso se
agregan al SELECT y no como campos calculados, que no totalizarían.
"""
import logging

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class StockQuantProductLocationReport(models.Model):
    _inherit = 'stock.quant.product.location.report'

    management_rate = fields.Float(
        string='TC de gestión', digits=(12, 6), readonly=True, group_operator=False,
        help='Tipo de cambio de gestión vigente, el que fija la empresa a mano.')
    management_cost = fields.Float(
        string='Costo de gestión', digits='Product Price', readonly=True,
        group_operator=False,
        help='Costo unitario del producto en pesos al cambio de gestión. No se totaliza: '
             'sumar costos unitarios de productos distintos no significa nada.')
    management_value = fields.Float(
        string='Existencia a costo de gestión', digits='Product Price', readonly=True,
        help='Cantidad disponible por el costo de gestión unitario. Esta sí totaliza, y '
             'es la que responde cuánto vale el stock con el criterio de la empresa.')

    def _select(self):
        """Suma el costo de gestión y la existencia valorizada a ese costo."""
        return super()._select() + """
                ,
                mgr.management_rate AS management_rate,
                (pp.ultimo_costo_mr * COALESCE(mgr.management_rate, 0.0))
                    AS management_cost,
                SUM(sq.quantity) * pp.ultimo_costo_mr
                    * COALESCE(mgr.management_rate, 0.0) AS management_value
        """

    def _from(self):
        """Trae el tipo de cambio de gestión vigente hoy para la compañía de cada quant.

        Se resuelve por compañía porque cada una puede tener su moneda de gestión, y se
        toma la última cotización anterior a hoy: es la que la empresa dejó en pie.
        """
        return super()._from() + """
            LEFT JOIN res_company rc ON rc.id = sq.company_id
            LEFT JOIN LATERAL (
                SELECT 1.0 / NULLIF(rate.rate, 0.0) AS management_rate
                FROM res_currency_rate rate
                WHERE rate.currency_id = rc.management_currency_id
                  AND rate.name <= CURRENT_DATE
                  AND (rate.company_id IS NULL OR rate.company_id = rc.id)
                ORDER BY rate.name DESC, rate.company_id NULLS LAST
                LIMIT 1
            ) mgr ON TRUE
        """

    def _group_by(self):
        """El costo unitario y el tipo de cambio son constantes dentro del grupo."""
        return super()._group_by() + """
                ,
                pp.ultimo_costo_mr,
                mgr.management_rate
        """
