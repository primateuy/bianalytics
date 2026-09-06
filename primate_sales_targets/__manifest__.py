# -*- coding: utf-8 -*-
{
    'name': 'Sales Targets — PrimateUY',
    'version': '17.0.1.0.0',
    'author': 'PrimateUY',
    'website': 'https://primate.uy',
    'category': 'Productivity/Dashboards',
    'license': 'AGPL-3',
    'summary': """Objetivos configurables por empleado, usuario o local sobre las métricas
        de Advanced Dashboards, con asignación periódica y seguimiento de avance.""",
    'description': """
        Fase 2 de la solución de analítica de Primate.

        Sigue el patrón del módulo de gamificación de Odoo — definición de lo que se
        persigue, asignación periódica a un conjunto de sujetos, y seguimiento del
        avance — pero lee el avance del motor de métricas ya precalculado, en lugar de
        recorrer de nuevo los modelos transaccionales. Eso garantiza que el número del
        objetivo y el número del dashboard sean el mismo.

        - primate.target.definition: qué métrica se persigue, con qué grano de período
          y sobre qué tipo de sujeto.
        - primate.target: el objetivo concreto de un sujeto en un período, con su valor
          a alcanzar, su valor actual y su porcentaje de avance.
        - primate.target.plan: asignación masiva, que genera un objetivo por sujeto y
          por período dentro de un rango.
        - Componente de dashboard "Avance de objetivos".

        El sujeto puede ser un empleado, un usuario o un local, porque el catálogo pide
        metas por vendedor (R05) y por local (R07).
    """,
    'depends': [
        'primate_advanced_dashboard',
        'hr',
        'stock',
    ],
    'data': [
        'security/primate_target_groups.xml',
        'security/ir.model.access.csv',
        'views/hr_employee_views.xml',
        'views/stock_warehouse_views.xml',
        'views/primate_target_definition_views.xml',
        'views/primate_target_views.xml',
        'views/primate_target_plan_views.xml',
        'views/primate_target_menus.xml',
        'data/ir_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'primate_sales_targets/static/src/scss/primate_targets.scss',
            'primate_sales_targets/static/src/js/**/*.js',
            'primate_sales_targets/static/src/xml/**/*.xml',
        ],
    },
    'installable': True,
    'application': False,
}
