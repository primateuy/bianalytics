# -*- coding: utf-8 -*-
"""Siembra de datos sintéticos de POS para probar Advanced Dashboards.

La base local tiene los maestros completos (38 locales, 311 empleados, 1.652 productos)
pero prácticamente nada transaccional, así que no alcanza para validar comparativos
año-contra-año ni el heatmap por franja horaria. Este script genera órdenes de POS
sobre los maestros reales, cubriendo 14 meses hacia atrás.

NO es data del módulo: es una herramienta de desarrollo. Se corre a mano y se puede
revertir con borrar_demo_pos_data.py.

Uso:
    .venv/bin/python _shared/community/odoo-bin shell -c forum.conf -d o17_forum \
        --no-http < forum/advanced_dashboard_forum_data/scripts/seed_demo_pos_data.py
"""
import logging
import random
from datetime import datetime, timedelta

import pytz

_logger = logging.getLogger('seed_demo_pos')

# Marca que permite identificar y borrar después todo lo generado acá.
DEMO_TAG = 'PAD-DEMO'
MONTHS_BACK = 14
ORDERS_PER_LOCAL_PER_MONTH = 12
LINES_PER_ORDER = (1, 5)
# Franjas con peso: el comercio abre de 9 a 21 y concentra a la tarde.
HOUR_WEIGHTS = {9: 1, 10: 2, 11: 3, 12: 4, 13: 3, 14: 3,
                15: 4, 16: 5, 17: 6, 18: 6, 19: 5, 20: 3}

random.seed(20260831)


def seed(env):
    """Genera las órdenes y devuelve cuántas creó."""
    warehouses = env['stock.warehouse'].search([('code', 'like', '0')])
    warehouses = warehouses.filtered(lambda w: w.code.isdigit())
    users_by_local = {}
    for user in env['res.users'].with_context(active_test=False).search(
            [('pad_local_id', '!=', False)]):
        users_by_local.setdefault(user.pad_local_id.id, user)
    configs_by_local = {}
    for config in env['pos.config'].with_context(active_test=False).search(
            [('pad_local_id', '!=', False)]):
        configs_by_local.setdefault(config.pad_local_id.id, config)

    products = env['product.product'].search(
        [('type', 'in', ('consu', 'product')), ('list_price', '>', 0)], limit=400)
    employees = env['hr.employee'].search([], limit=120)
    if not (products and employees):
        _logger.error('Faltan productos o empleados para sembrar')
        return 0

    teams = env['crm.team'].search([], limit=4)
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    hours = [hour for hour, weight in HOUR_WEIGHTS.items() for _ in range(weight)]
    timezone = pytz.timezone(env.company.partner_id.tz or 'America/Montevideo')

    created = 0
    for warehouse in warehouses:
        user = users_by_local.get(warehouse.id)
        config = configs_by_local.get(warehouse.id)
        if not (user and config):
            continue
        session = _get_session(env, config, user)
        orders = []
        for month_offset in range(MONTHS_BACK):
            for _ in range(ORDERS_PER_LOCAL_PER_MONTH):
                order_date = _random_datetime(now, month_offset, hours, timezone)
                lines, total = _build_lines(products, employees, random.randint(*LINES_PER_ORDER))
                orders.append({
                    'name': '%s/%s/%s' % (DEMO_TAG, warehouse.code, len(orders)),
                    'pos_reference': '%s %s-%s' % (DEMO_TAG, warehouse.code, len(orders)),
                    'session_id': session.id,
                    'company_id': config.company_id.id,
                    'user_id': user.id,
                    'crm_team_id': (teams and random.choice(teams).id) or False,
                    'date_order': order_date,
                    'state': 'done',
                    'amount_total': total,
                    'amount_paid': total,
                    'amount_tax': round(total * 0.22 / 1.22, 2),
                    'amount_return': 0.0,
                    'lines': lines,
                })
        if orders:
            env['pos.order'].create(orders)
            created += len(orders)
            _logger.info('Local %s (%s): %s órdenes', warehouse.code, warehouse.name, len(orders))
    return created


def _get_session(env, config, user):
    """Reusa la sesión de demo del punto de venta o la crea."""
    session = env['pos.session'].with_context(active_test=False).search(
        [('config_id', '=', config.id), ('name', 'like', DEMO_TAG)], limit=1)
    if session:
        return session
    session = env['pos.session'].create({
        'config_id': config.id,
        'user_id': user.id,
        'name': '%s/%s' % (DEMO_TAG, config.id),
        'state': 'closed',
    })
    return session


def _random_datetime(now, month_offset, hours, timezone):
    """Fecha aleatoria dentro del mes indicado, con hora comercial ponderada.

    La hora se elige en el huso de la compañía y se convierte a UTC antes de
    guardarla, que es como Odoo almacena los datetime. Sin esa conversión los
    horarios de apertura quedarían corridos tres horas en el heatmap.
    """
    reference = now - timedelta(days=30 * month_offset)
    day_offset = random.randint(0, 27)
    moment = reference - timedelta(days=day_offset)
    local = moment.replace(hour=random.choice(hours), minute=random.randint(0, 59))
    return timezone.localize(local).astimezone(pytz.UTC).replace(tzinfo=None)


def _build_lines(products, employees, count):
    """Arma las líneas de una orden y devuelve (comandos, total)."""
    lines, total = [], 0.0
    for _ in range(count):
        product = random.choice(products)
        employee = random.choice(employees)
        qty = random.randint(1, 4)
        price = product.list_price or 100.0
        discount = random.choice([0.0, 0.0, 0.0, 5.0, 10.0, 20.0])
        subtotal_incl = round(price * qty * (1 - discount / 100.0), 2)
        subtotal = round(subtotal_incl / 1.22, 2)
        cost = round(price * 0.55, 2) * qty
        total += subtotal_incl
        lines.append((0, 0, {
            'name': product.display_name,
            'full_product_name': product.display_name,
            'product_id': product.id,
            'user_id': employee.id,
            'qty': qty,
            'price_unit': price,
            'discount': discount,
            'price_subtotal': subtotal,
            'price_subtotal_incl': subtotal_incl,
            'total_cost': cost,
        }))
    return lines, round(total, 2)


count = seed(env)  # noqa: F821 — env lo inyecta odoo-bin shell
env.cr.commit()    # noqa: F821
_logger.info('Sembradas %s órdenes de POS marcadas como %s', count, DEMO_TAG)
print('Órdenes creadas: %s' % count)
