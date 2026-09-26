# -*- coding: utf-8 -*-
"""Borra todo lo que generó seed_demo_targets.py.

Los objetivos tienen ondelete='cascade' desde el plan, pero se borran explícitos para
dejar constancia de cuántos eran. Las definiciones NO se tocan: son data del módulo
advanced_dashboard_forum_data, no del sembrado.

Uso:
    .venv/bin/python _shared/community/odoo-bin shell -c forum-solo.conf -d o17_forum \
        --no-http < _shared/bianalytics/advanced_dashboard_forum_data/scripts/borrar_demo_targets.py
"""
DEMO_TAG = 'PAD-DEMO'

plans = env['primate.target.plan'].search([('name', 'like', DEMO_TAG)])  # noqa: F821
targets = env['primate.target'].search([('plan_id', 'in', plans.ids)])  # noqa: F821
print('Planes a borrar: %s (con %s objetivos)' % (len(plans), len(targets)))

if targets:
    targets.unlink()
    print('Objetivos borrados.')

if plans:
    plans.unlink()
    print('Planes borrados.')

env.cr.commit()  # noqa: F821
print('Listo.')
