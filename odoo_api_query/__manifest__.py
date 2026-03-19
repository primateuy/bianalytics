{
    'name': 'Odoo API Query',
    'version': '1.0',
    'summary': 'Execute predefined SQL queries via API with pagination',
    'license': 'LGPL-3',
    'author': 'Custom',
    'depends': ['base'],
    'data': [
        'security/ir.model.access.csv',
        'views/query_definition_views.xml',
        'data/config.xml',
    ],
    'installable': True,
    'application': True,
}
