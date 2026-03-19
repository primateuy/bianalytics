from odoo import models, fields

class ApiQueryDefinition(models.Model):
    _name = 'api.query.definition'
    _description = 'API Query Definition'

    name = fields.Char(required=True)
    query_key = fields.Char(required=True)
    sql_query = fields.Text(required=True)
    active = fields.Boolean(default=True)
