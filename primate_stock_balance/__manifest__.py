# -*- coding: utf-8 -*-
{
    'name': 'Stock Balance — PrimateUY',
    'version': '17.0.1.0.0',
    'author': 'PrimateUY',
    'website': 'https://primate.uy',
    'category': 'Productivity/Dashboards',
    'license': 'AGPL-3',
    'summary': """Tabla de saldos de stock por fecha de corte, reconstruida desde los
        movimientos, para que las métricas de inventario tengan serie histórica real.""",
    'description': """
        El stock es un saldo, no un flujo, y stock.quant guarda solo el saldo de hoy:
        su write_date dice cuándo se tocó el registro por última vez, no a qué fecha
        corresponde la existencia. Una métrica que lea el quant por write_date produce
        una serie plana con un pico en el día de la última escritura.

        Este módulo mantiene primate.stock.balance: una fila por fecha de corte,
        variante y almacén, reconstruida hacia atrás desde el saldo actual restando los
        movimientos posteriores — el mismo mecanismo que usa el core para el parámetro
        to_date de qty_available.

        La métrica de inventario pasa a leer de acá, declarada como medida de saldo
        para que el motor no la sume a lo largo del tiempo.
    """,
    'depends': [
        'primate_advanced_dashboard',
        'stock',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/primate_stock_balance_views.xml',
        'wizard/primate_stock_balance_backfill_views.xml',
        'data/ir_config_parameter.xml',
        'data/ir_cron.xml',
    ],
    'installable': True,
    'application': False,
}
