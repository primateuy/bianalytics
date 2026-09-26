# -*- coding: utf-8 -*-
"""Siembra de movimientos de stock sintéticos para probar las métricas de inventario.

La base local tiene 33 quants y 29 movimientos, todos de la última semana: el demo de
POS que sembró seed_demo_pos_data.py generó órdenes pero NO movimientos de stock, así
que no hay con qué validar días de stock, cobertura ni la reconstrucción del saldo a
una fecha pasada.

Este script genera movimientos reales (entradas desde proveedor y salidas a cliente)
repartidos quincenalmente sobre 14 meses, de modo que:

  - los quants queden con un saldo actual coherente,
  - stock.move.line tenga historia con fechas pasadas, que es lo que necesita la
    reconstrucción "saldo de hoy menos los movimientos posteriores a la fecha",
  - el saldo de cada producto por local evolucione sin pasar nunca a negativo.

Odoo pisa la fecha del movimiento al validarlo, así que la fecha histórica se escribe
DESPUÉS del _action_done(), tanto en el movimiento como en sus líneas.

NO es data del módulo: es una herramienta de desarrollo. Se revierte con
borrar_demo_stock_data.py.

Uso:
    .venv/bin/python _shared/community/odoo-bin shell -c forum.conf -d o17_forum \
        --no-http < forum/advanced_dashboard_forum_data/scripts/seed_demo_stock_data.py
"""
import logging
import random
from datetime import datetime, timedelta

_logger = logging.getLogger('seed_demo_stock')

# Marca que permite identificar y borrar después todo lo generado acá.
DEMO_TAG = 'PAD-DEMO-STOCK'
MONTHS_BACK = 14
WAREHOUSE_COUNT = 8
PRODUCT_COUNT = 45
# Probabilidad de que una combinación producto x local se mueva en una quincena dada:
# no todo rota todo el tiempo, y así el saldo tiene mesetas además de escalones.
MOVE_PROBABILITY = 0.55
INITIAL_STOCK = (80, 250)
INBOUND_QTY = (20, 90)
OUTBOUND_RATIO = (0.10, 0.45)

random.seed(20260905)


def _fortnights(months_back):
    """Fechas quincenales desde hace months_back meses hasta hoy."""
    today = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=months_back * 30)
    dates = []
    cursor = start
    while cursor <= today:
        dates.append(cursor)
        cursor += timedelta(days=15)
    return dates


def _build_move(product, warehouse, qty, date, outbound, supplier_loc, customer_loc):
    """Arma los valores de un movimiento de entrada o de salida."""
    stock_loc = warehouse.lot_stock_id
    if outbound:
        source, dest, label = stock_loc, customer_loc, 'Salida'
    else:
        source, dest, label = supplier_loc, stock_loc, 'Entrada'
    return {
        'name': '%s %s %s' % (DEMO_TAG, label, product.display_name[:40]),
        'reference': '%s/%s' % (DEMO_TAG, warehouse.code),
        'origin': DEMO_TAG,
        'product_id': product.id,
        'product_uom': product.uom_id.id,
        'product_uom_qty': qty,
        'location_id': source.id,
        'location_dest_id': dest.id,
        'company_id': warehouse.company_id.id,
        'date': date,
    }


def seed(env):
    """Genera los movimientos y devuelve cuántos creó."""
    warehouses = env['stock.warehouse'].search([]).filtered(
        lambda w: w.code and w.code.isdigit() and w.lot_stock_id)[:WAREHOUSE_COUNT]
    products = env['product.product'].search(
        [('type', '=', 'product'), ('list_price', '>', 0)], limit=PRODUCT_COUNT)
    supplier_loc = env['stock.location'].search([('usage', '=', 'supplier')], limit=1)
    customer_loc = env['stock.location'].search([('usage', '=', 'customer')], limit=1)
    if not (warehouses and products and supplier_loc and customer_loc):
        _logger.error('Faltan almacenes, productos o ubicaciones para sembrar')
        return 0

    dates = _fortnights(MONTHS_BACK)
    _logger.info('Sembrando %s locales x %s productos sobre %s quincenas',
                 len(warehouses), len(products), len(dates))

    # Saldo simulado por (local, producto): es lo que evita que una salida deje el
    # quant en negativo, que ensuciaría cualquier lectura de cobertura.
    balances = {}
    total = 0

    for index, date in enumerate(dates):
        values_list = []
        planned = []
        for warehouse in warehouses:
            for product in products:
                key = (warehouse.id, product.id)
                balance = balances.get(key, 0.0)
                if index == 0:
                    # Carga inicial: todo el mundo arranca con existencia.
                    qty = float(random.randint(*INITIAL_STOCK))
                    outbound = False
                else:
                    if random.random() > MOVE_PROBABILITY:
                        continue
                    # Se repone cuando queda poco; si no, se vende una parte.
                    if balance < 30:
                        qty = float(random.randint(*INBOUND_QTY))
                        outbound = False
                    else:
                        ratio = random.uniform(*OUTBOUND_RATIO)
                        qty = float(max(1, int(balance * ratio)))
                        outbound = True
                if qty <= 0:
                    continue
                values_list.append(_build_move(
                    product, warehouse, qty, date, outbound, supplier_loc, customer_loc))
                planned.append((key, qty, outbound))

        if not values_list:
            continue

        moves = env['stock.move'].create(values_list)
        moves._action_confirm()
        moves._action_assign()
        for move in moves:
            move.quantity = move.product_uom_qty
            move.picked = True
        moves._action_done()
        # La fecha real se fuerza acá: _action_done() la pisa con el momento actual.
        moves.write({'date': date})
        moves.move_line_ids.write({'date': date})

        for key, qty, outbound in planned:
            balances[key] = balances.get(key, 0.0) + (-qty if outbound else qty)
        total += len(moves)
        env.cr.commit()
        _logger.info('Quincena %s/%s (%s): %s movimientos',
                     index + 1, len(dates), date.date(), len(moves))

    return total


count = seed(env)  # noqa: F821 — env lo inyecta odoo-bin shell
env.cr.commit()    # noqa: F821
_logger.info('Sembrados %s movimientos marcados como %s', count, DEMO_TAG)
print('Movimientos creados: %s' % count)
