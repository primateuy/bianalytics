# -*- coding: utf-8 -*-
"""Siembra de planes de objetivos sintéticos para probar Advanced Dashboards.

Las cuatro definiciones del catálogo de FORUM son por empleado y con grano mensual,
pero la base no trae ningún plan cargado, así que los componentes de objetivo salen
vacíos. Este script arma un plan por definición sobre los vendedores que realmente
tienen ventas en los datos demo, y les fija una meta derivada de su propio histórico.

El valor a alcanzar sale de la tabla de hechos: el promedio mensual del vendedor
multiplicado por un factor aleatorio alrededor de 1. Así el tablero muestra una
mezcla realista de objetivos alcanzados y no alcanzados en vez de todo en verde o
todo en rojo.

Requiere que el precálculo ya esté corrido: sin hechos no hay de dónde derivar las
metas y el script aborta.

NO es data del módulo: es una herramienta de desarrollo. Se corre a mano y se puede
revertir con borrar_demo_targets.py.

Uso:
    .venv/bin/python _shared/community/odoo-bin shell -c forum-solo.conf -d o17_forum \
        --no-http < _shared/bianalytics/advanced_dashboard_forum_data/scripts/seed_demo_targets.py
"""
import logging
import random
from datetime import date

_logger = logging.getLogger('seed_demo_targets')

# Marca que permite identificar y borrar después todo lo generado acá.
DEMO_TAG = 'PAD-DEMO'
DATE_START = date(2025, 8, 1)
DATE_END = date(2026, 9, 30)
# Dispersión de la meta respecto del histórico del vendedor: por debajo de 1 el
# objetivo se alcanza, por encima no.
FACTOR_RANGE = (0.85, 1.15)

random.seed(20260916)


def _monthly_average(env, metric_code):
    """Promedio mensual por empleado de una métrica, leído de los hechos.

    Cada registro de origen cae en un único bucket de dimensiones, así que sumar
    todas las filas de un empleado da su total sin duplicar.
    """
    env.cr.execute("""
        SELECT employee_id, SUM(value) / GREATEST(COUNT(DISTINCT date_trunc('month', date)), 1)
          FROM primate_metric_fact f
          JOIN primate_metric_version v ON v.id = f.metric_version_id
          JOIN primate_metric m ON m.id = v.metric_id
         WHERE m.code = %s AND f.employee_id IS NOT NULL
      GROUP BY employee_id
    """, (metric_code,))
    return dict(env.cr.fetchall())


def _ratio_by_employee(env, numerator_code, denominator_code):
    """Ratio por empleado entre dos métricas (ticket promedio, unidades por boleta).

    Las métricas de tipo ratio en modo "agregado y dividir" no guardan hechos
    propios, así que la meta se deriva dividiendo los agregados de sus componentes,
    que es exactamente lo que hace el motor al leerlas.
    """
    numerators = _monthly_average(env, numerator_code)
    denominators = _monthly_average(env, denominator_code)
    return {
        employee: numerators[employee] / denominators[employee]
        for employee in numerators
        if denominators.get(employee)
    }


# Cada definición del catálogo, con la forma de derivar su meta.
PLANS = [
    ('forum_ventas_vendedor', 'Ventas mensuales por vendedor',
     lambda env: _monthly_average(env, 'forum_ventas_totales')),
    ('forum_boletas_vendedor', 'Boletas atendidas por mes',
     lambda env: _monthly_average(env, 'forum_boletas_vendedor')),
    ('forum_ticket_vendedor', 'Ticket promedio por vendedor',
     lambda env: _ratio_by_employee(env, 'forum_ventas_totales', 'forum_boletas_vendedor')),
    ('forum_uxb_vendedor', 'Unidades por boleta por vendedor',
     lambda env: _ratio_by_employee(env, 'forum_unidades', 'forum_boletas_vendedor')),
]


def seed(env):
    """Crea los planes, genera sus objetivos y trae el avance de cada uno."""
    created_plans = 0
    for code, label, resolver in PLANS:
        definition = env['primate.target.definition'].search([('code', '=', code)], limit=1)
        if not definition:
            _logger.warning('No existe la definición %s; se saltea', code)
            continue

        averages = resolver(env)
        if not averages:
            _logger.warning('La definición %s no tiene hechos por empleado; se saltea', code)
            continue

        employees = env['hr.employee'].browse(sorted(averages))
        plan = env['primate.target.plan'].create({
            'name': '%s %s' % (DEMO_TAG, label),
            'definition_id': definition.id,
            'date_start': DATE_START,
            'date_end': DATE_END,
            'default_target': 0.0,
            'employee_ids': [(6, 0, employees.ids)],
            'line_ids': [(0, 0, {
                'employee_id': employee_id,
                'target_value': round(value * random.uniform(*FACTOR_RANGE), 2),
            }) for employee_id, value in sorted(averages.items())],
        })
        plan.action_generate()
        _logger.info('Plan %s: %s vendedores, %s objetivos',
                     code, len(employees), plan.target_count)
        plan.action_start_targets()
        created_plans += 1
        env.cr.commit()
        _logger.info('Plan %s: avance calculado', code)
    return created_plans


count = seed(env)  # noqa: F821 — env lo inyecta odoo-bin shell
env.cr.commit()    # noqa: F821
print('Planes creados: %s' % count)
