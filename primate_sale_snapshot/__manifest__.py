# -*- coding: utf-8 -*-
{
    'name': 'Snapshot de Venta — PrimateUY',
    'version': '17.0.1.0.0',
    'author': 'PrimateUY',
    'website': 'https://primate.uy',
    'category': 'Sales/Point of Sale',
    'license': 'AGPL-3',
    'summary': """Congela al vender los datos del producto y del punto de venta, en una
        pestaña propia de la factura, para que la historia no cambie cuando cambia el
        maestro.""",
    'description': """
        Un producto se recategoriza, le cambian las etiquetas, sube el costo. Cuando eso
        pasa, todo reporte que resuelva esos atributos leyendo el producto reescribe el
        pasado: la venta de julio del año pasado empieza a contarse en la familia nueva.
        No es un riesgo teórico — es lo que hace hoy cualquier recálculo.

        La respuesta es congelar al vender. Este módulo guarda, por línea de venta, cómo
        estaba configurado el producto en ese momento:

        - Categoría, familia, etiquetas y precio de referencia.
        - El costo en moneda de reportería y su equivalente al tipo de cambio de gestión
          vigente ese día, con el tipo de cambio guardado al lado para poder rehacer la
          cuenta.
        - Cualquier otro campo del producto que se declare en la configuración, sin
          tocar código.

        Y guarda también lo que el punto de venta sabe y la contabilidad pierde: el
        vendedor de cada línea, la caja, la sesión y la hora real de la venta. Todo eso
        vive en una pestaña propia de la factura.

        Los datos NO se guardan en los apuntes contables. account.move.line es una tabla
        caliente, con validaciones de cuadratura y conciliación y varios módulos de la
        localización escribiendo encima; un satélite se escribe una vez, al publicar, y
        no se toca nunca más.
    """,
    'depends': [
        'account',
        'point_of_sale',
        'stock',
        'primate_management_cost',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/primate_snapshot_field_views.xml',
        'views/primate_sale_snapshot_views.xml',
        'views/account_move_views.xml',
        'views/pos_order_views.xml',
        'wizard/primate_sale_snapshot_rebuild_views.xml',
        'data/primate_snapshot_field.xml',
    ],
    'installable': True,
    'application': False,
}
