# -*- coding: utf-8 -*-
{
    'name': 'Advanced Dashboards — PrimateUY',
    'version': '17.0.1.0.0',
    'author': 'PrimateUY',
    'website': 'https://primate.uy',
    'category': 'Productivity/Dashboards',
    'license': 'AGPL-3',
    'summary': """Motor de métricas reutilizables y versionadas, precálculo en tabla de hechos,
        comparativos dinámicos de período, filtros globales y componentes visuales de dashboard.""",
    'description': """
        Fase 1 de la solución de analítica de Primate (Advanced Dashboards).

        - Motor de métricas: definición base compartida + override por compañía, versionado
          inmutable y modo de cálculo configurable para métricas de tipo ratio.
        - Motor de precálculo: agregación diaria por métrica x dimensión en tabla de hechos,
          vía cron incremental, con wizard de recálculo (backfill) y auditoría de corridas.
        - Motor de comparativos: tipos de período (día, semana ISO, mes, trimestre, año, rango)
          y reglas de comparación (período anterior, mismo período año anterior, MTD, YTD).
        - Filtros globales de dashboard y componentes visuales: KPI Card, KPI comparativo,
          Ranking, Tabla, Indicador con umbrales y Heatmap (día x franja horaria).

        Toda la lógica de negocio vive en modelos y métodos Python. La capa visual es
        reconstruible sin tocar el motor (ver sección 3.1 de la especificación).

        Fuera de alcance de esta fase: Sales Targets, API de acciones para agentes y
        Sagui Dashboards.
    """,
    'depends': [
        'base',
        'mail',
        'web',
        'product',
        'stock',
        'hr',
        'sales_team',
    ],
    'data': [
        'security/primate_dashboard_groups.xml',
        'security/ir.model.access.csv',
        'security/primate_dashboard_rules.xml',
        'data/primate_period_type.xml',
        'data/primate_comparison.xml',
        'data/ir_cron.xml',
        'views/primate_metric_dimension_views.xml',
        'views/primate_metric_views.xml',
        'views/primate_metric_fact_views.xml',
        'views/primate_dashboard_views.xml',
        'wizard/primate_metric_backfill_views.xml',
        'views/primate_dashboard_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'primate_advanced_dashboard/static/src/scss/primate_dashboard.scss',
            'primate_advanced_dashboard/static/src/js/**/*.js',
            'primate_advanced_dashboard/static/src/xml/**/*.xml',
        ],
    },
    'installable': True,
    'application': True,
}
