{
    'name': 'Odoo API Query',
    'version': '1.1',
    'summary': 'Execute predefined SQL queries via API with pagination',
    'license': 'LGPL-3',
    'author': 'Custom',
    'depends': ['base'],
    'data': [
        'security/ir.model.access.csv',
        'views/query_definition_views.xml',
        'views/api_query_log_views.xml',
        'data/config.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
}
