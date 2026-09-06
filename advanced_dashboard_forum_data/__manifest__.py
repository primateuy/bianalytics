# -*- coding: utf-8 -*-
{
    'name': 'Advanced Dashboards — Datos FORUM',
    'version': '17.0.1.0.0',
    'author': 'PrimateUY',
    'website': 'https://primate.uy',
    'category': 'Productivity/Dashboards',
    'license': 'AGPL-3',
    'summary': """Catálogo de métricas y dashboards relevados para FORUM, cargados como datos
        del cliente sobre el motor de primate_advanced_dashboard.""",
    'description': """
        Datos de FORUM para Advanced Dashboards. No agrega capacidades al motor: solo
        declara las dimensiones reales de FORUM y carga el catálogo de métricas relevado.

        - Mapeo del concepto "Local" a stock.warehouse, resolviendo el origen POS por
          usuario de sucursal y el origen contable por diario de venta. Reemplaza el campo
          de Studio que había dejado el proveedor de BI anterior, que era redundante.
        - Dimensiones de FORUM: local, vendedor, equipo comercial, familia, subfamilia,
          producto base, variante, franja horaria y día de la semana.
        - Métricas de los reportes R01 a R11 del catálogo, con las provisorias marcadas
          como borrador y vinculadas a su Gap ID.
        - Los cuatro dashboards del catálogo. El de Metas queda maquetado con lo que no
          depende de Sales Targets, que es Fase 2.
    """,
    'depends': [
        'primate_advanced_dashboard',
        'primate_sales_targets',
        'account',
        'sale',
        'point_of_sale',
        'pos_hr',
        'stock',
        'stock_account',
        'sales_team',
    ],
    'data': [
        'data/ir_config_parameter.xml',
        'data/primate_metric_dimension.xml',
        'data/primate_metric.xml',
        'data/primate_metric_version.xml',
        'data/primate_metric_vendedor.xml',
        'data/primate_dashboard.xml',
        'data/primate_dashboard_ventas.xml',
        'data/primate_target_definition.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': False,
}
