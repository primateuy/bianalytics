from odoo import http
from odoo.http import request
import json
import math
import logging

_logger = logging.getLogger(__name__)

class ApiQueryController(http.Controller):

    @http.route('/api/v1/query/execute', auth='public', methods=['POST'], csrf=False, type='http')
    def execute_query(self, **kwargs):
        """
        Endpoint POST JSON REST puro con type='http'
        Header: X-API-Key
        Body: JSON
        """
        try:
            body = json.loads(request.httprequest.data.decode())
        except Exception:
            return request.make_response(
                json.dumps({"error": "Invalid JSON"}),
                headers=[('Content-Type', 'application/json')],
                status=400
            )

        # -------------------------
        # API KEY
        # -------------------------
        api_key = (request.httprequest.headers.get('X-API-Key') or '').strip()
        system_key = request.env['ir.config_parameter'].sudo().get_param('api_query.api_key') or ''

        if not api_key or api_key != system_key:
            return request.make_response(
              json.dumps({"error": "Unauthorized"}),
              headers=[('Content-Type', 'application/json')],
              status=401
            )

        if not api_key or api_key != system_key:
            _logger.warning("Unauthorized API access attempt" + api_key + " system " + system_key)
        # -------------------------
        # PARÁMETROS
        # -------------------------
        query_key = body.get("query_key")
        page_size = int(body.get("page_size", 10))
        page_number = int(body.get("page_number", 1))
        params = body.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        max_page_size = int(request.env['ir.config_parameter'].sudo().get_param('api_query.max_page_size', 100))
        page_size = min(page_size, max_page_size)

        # -------------------------
        # BUSCAR QUERY DEFINITION
        # -------------------------
        query_def = request.env['api.query.definition'].sudo().search([
            ('query_key', '=', query_key),
            ('active', '=', True)
        ], limit=1)
        if not query_def:
            return request.make_response(
                json.dumps({"error": "query_key not found"}),
                headers=[('Content-Type', 'application/json')],
                status=404
            )

        base_sql = query_def.sql_query.strip()

        # -------------------------
        # FILTROS
        # -------------------------
        filters = []
        values = []
        for key, value in params.items():
            filters.append(f"{key} = %s")
            values.append(value)
        if filters:
            base_sql += " WHERE " + " AND ".join(filters)

        # -------------------------
        # PAGINACIÓN
        # -------------------------
        offset = (page_number - 1) * page_size
        paginated_sql = f"{base_sql} LIMIT %s OFFSET %s"
        values_paginated = values + [page_size, offset]

        try:
            request.env.cr.execute(paginated_sql, values_paginated)
            columns = [desc[0] for desc in request.env.cr.description]
            rows = request.env.cr.fetchall()
            data = [dict(zip(columns, row)) for row in rows]
        except Exception:
            _logger.exception("Error ejecutando la consulta SQL")
            return request.make_response(
                json.dumps({"error": "Error ejecutando la consulta"}),
                headers=[('Content-Type', 'application/json')],
                status=500
            )

        # -------------------------
        # TOTAL REGISTROS
        # -------------------------
        count_sql = f"SELECT COUNT(*) FROM ({base_sql}) as count_query"
        try:
            request.env.cr.execute(count_sql, values)
            total_records = request.env.cr.fetchone()[0]
        except Exception:
            total_records = len(data)

        total_pages = math.ceil(total_records / page_size) if page_size else 1

        response = {
            "metadata": {
                "total_records": total_records,
                "total_pages": total_pages,
                "current_page": page_number,
                "page_size": page_size,
                "has_next": page_number < total_pages
            },
            "data": data
        }

        return request.make_response(
            json.dumps(response),
            headers=[('Content-Type', 'application/json')],
            status=200
        )
