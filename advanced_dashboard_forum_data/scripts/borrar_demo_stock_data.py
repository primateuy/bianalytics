# -*- coding: utf-8 -*-
"""Borra todo lo que generó seed_demo_stock_data.py.

Un movimiento validado no se puede borrar directamente: hay que devolverlo a borrador,
lo que además revierte su efecto sobre los quants. Las líneas se borran con el
movimiento por la cascada de la clave foránea.

Los quants que queden en cero después de revertir se dejan como están: son registros
inocuos y borrarlos a mano puede tocar existencias que no vinieron de la siembra.

Uso:
    .venv/bin/python _shared/community/odoo-bin shell -c forum.conf -d o17_forum \
        --no-http < forum/advanced_dashboard_forum_data/scripts/borrar_demo_stock_data.py
"""
DEMO_TAG = 'PAD-DEMO-STOCK'

moves = env['stock.move'].search([('origin', '=', DEMO_TAG)])  # noqa: F821
print('Movimientos a borrar: %s' % len(moves))

if moves:
    # De a tandas: revertir seis mil movimientos de una sola vez es pesado y, si algo
    # falla en el medio, conviene no perder lo ya revertido.
    batch_size = 500
    for index in range(0, len(moves), batch_size):
        batch = moves[index:index + batch_size]
        batch._action_cancel()
        batch.write({'state': 'draft'})
        batch.unlink()
        env.cr.commit()  # noqa: F821
        print('  revertidos %s de %s' % (min(index + batch_size, len(moves)), len(moves)))
    print('Movimientos borrados.')

# Los hechos de stock quedan desactualizados: se rehacen con el wizard de recálculo.
facts = env['primate.metric.fact'].search([  # noqa: F821
    ('metric_version_id.metric_id.code', '=', 'forum_stock_disponible')])
print('Hechos de stock a borrar: %s' % len(facts))
facts.unlink()

env.cr.commit()  # noqa: F821
print('Listo.')
