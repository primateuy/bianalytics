# -*- coding: utf-8 -*-
{
    'name': 'Costo de Gestión — PrimateUY',
    'version': '17.0.1.0.0',
    'author': 'PrimateUY',
    'website': 'https://primate.uy',
    'category': 'Inventory/Inventory',
    'license': 'AGPL-3',
    'summary': """Costo del producto en moneda de reportería llevado a pesos con el tipo
        de cambio de gestión que fija la empresa, y existencia valorizada a ese costo.""",
    'description': """
        FORUM razona el costo de dos maneras a la vez. El costo real es el de la última
        compra, que puede haber sido en cualquier moneda y que tchistorico deja expresado
        en la moneda de reportería (UCMR). Pero para decidir, lo llevan a pesos con un
        tipo de cambio propio, fijado a mano y sostenido en el tiempo, que no es el del
        mercado: es una cobertura. Si algo costó USD 10 y el tipo de cambio de gestión es
        45, para ellos ese producto cuesta 450, aunque el dólar del día esté en otro lado.

        Ese tipo de cambio ya vive en Odoo como las cotizaciones de la moneda USG
        ("USD - Gestión"), que la empresa carga a mano: 43 desde noviembre de 2024, 45
        desde noviembre de 2025. Este módulo no inventa nada de eso, solo lo convierte en
        un costo utilizable:

        - product.management_cost: el costo de gestión unitario del producto.
        - Dos columnas en el reporte de existencias: el costo de gestión unitario y la
          existencia valorizada a ese costo, que totaliza en las agrupaciones.
    """,
    'depends': [
        'stock',
        'tchistorico',
    ],
    'data': [
        'views/res_company_views.xml',
        'views/product_views.xml',
        'views/stock_quant_product_location_report_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
