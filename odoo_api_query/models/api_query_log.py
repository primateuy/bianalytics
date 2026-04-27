from odoo import models, fields


class ApiQueryLog(models.Model):
    _name = 'api.query.log'
    _description = 'API Query Log'
    _order = 'start_datetime desc'

    start_datetime = fields.Datetime(string="Start Time", required=True)
    end_datetime = fields.Datetime(string="End Time")

    query_key = fields.Char(string="Query Key")

    sql_text = fields.Text(string="SQL Ejecutado")
    params_text = fields.Text(string="Parámetros")

    total_records = fields.Integer(string="Total Records")
    page_records = fields.Integer(string="Records (Página)")

    status = fields.Selection([
        ('success', 'Success'),
        ('error', 'Error'),
    ], default='success')

    error_message = fields.Text(string="Error")