# -*- coding: utf-8 -*-
"""Borra todo lo que generó seed_demo_pos_data.py.

Una pos.order solo se puede borrar en estado borrador o cancelada, así que primero
hay que devolverlas a borrador. Las sesiones se borran después de las órdenes, porque
hay una clave foránea de pos_order a pos_session.

Uso:
    .venv/bin/python _shared/community/odoo-bin shell -c forum.conf -d o17_forum \
        --no-http < forum/advanced_dashboard_forum_data/scripts/borrar_demo_pos_data.py
"""
DEMO_TAG = 'PAD-DEMO'

orders = env['pos.order'].with_context(active_test=False).search(  # noqa: F821
    [('name', 'like', DEMO_TAG)])
sessions = orders.mapped('session_id')
print('Órdenes a borrar: %s (en %s sesiones)' % (len(orders), len(sessions)))
if orders:
    orders.write({'state': 'draft'})
    orders.unlink()
    print('Órdenes borradas.')

if sessions:
    sessions.write({'state': 'opened'})
    sessions.unlink()
    print('Sesiones borradas: %s' % len(sessions))

facts = env['primate.metric.fact'].search([])  # noqa: F821
print('Hechos precalculados a borrar: %s' % len(facts))
facts.unlink()

runs = env['primate.metric.fact.run'].search([])  # noqa: F821
runs.unlink()

env.cr.commit()  # noqa: F821
print('Listo.')
