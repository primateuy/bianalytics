from odoo import http
from odoo.http import request
import json
import math
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)


class ApiQueryController(http.Controller):



    def validate_sql(self, cr, sql, values=None):
        """
        Valida SQL sin ejecutarlo realmente.
        Usa EXPLAIN para detectar errores de sintaxis o columnas inexistentes.
        """
        try:
            explain_sql = f"EXPLAIN {sql}"

            cr.execute(explain_sql, values or [])

            return True, None

        except Exception as e:
            return False, str(e)



    @http.route('/api/v1/query/execute', auth='public', methods=['POST'], csrf=False, type='http')
    def execute_query(self, **kwargs):

        # -------------------------
        # PARSE JSON
        # -------------------------
        try:
            body = json.loads(request.httprequest.data.decode())
        except Exception:
            return request.make_response(
                json.dumps({"error": "Invalid JSON"}),
                headers=[('Content-Type', 'application/json')],
                status=400
            )

        start_time = datetime.now()

        # -------------------------
        # API KEY
        # -------------------------
        api_key = (request.httprequest.headers.get('X-API-Key') or '').strip()
        system_key = request.env['ir.config_parameter'].sudo().get_param('api_query.api_key') or ''

        if not api_key or api_key != system_key:
            _logger.warning("Unauthorized API access attempt: %s", api_key)
            return request.make_response(
                json.dumps({"error": "Unauthorized"}),
                headers=[('Content-Type', 'application/json')],
                status=401
            )

        # -------------------------
        # PARAMS
        # -------------------------
        query_key = body.get("query_key")
        page_size = int(body.get("page_size", 10))
        page_number = int(body.get("page_number", 1))
        params = body.get("params") or {}

        if not isinstance(params, dict):
            params = {}

        max_page_size = int(
            request.env['ir.config_parameter'].sudo().get_param('api_query.max_page_size', 100)
        )
        page_size = min(page_size, max_page_size)

        _logger.info("API START | query_key=%s | params=%s", query_key, params)

        # -------------------------
        # QUERY DEF
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

        allowed_ops = ["<=", ">=", "!=", "=", ">", "<"]

        for key, value in params.items():
            key = key.strip()

            field = None
            op = None

            for candidate_op in allowed_ops:
                if key.endswith(candidate_op):
                    field = key[: -len(candidate_op)].strip()
                    op = candidate_op
                    break

            if not field:
                field = key
                op = "="

            if not field or " " in field:
                raise ValueError(f"Campo inválido en filtro: '{key}'")

            filters.append(f"{field} {op} %s")
            values.append(value)

        if filters:
            if "where" in base_sql.lower():
                base_sql += " AND " + " AND ".join(filters)
            else:
                base_sql += " WHERE " + " AND ".join(filters)

        # -------------------------
        # PAGINACIÓN
        # -------------------------
        offset = max((page_number - 1), 0) * page_size
        paginated_sql = f"{base_sql} LIMIT {int(page_size)} OFFSET {int(offset)}"
        values_paginated = values

        _logger.info("SQL: %s", base_sql)
        _logger.info("VALUES: %s", values)

        # -------------------------
        # DATA
        
        # -------------------------

        try:
            
            
            request.env.cr.execute(paginated_sql, values_paginated)



            if not request.env.cr.description:
                raise Exception("SQL inválido: no devolvió metadata")


            description = request.env.cr.description

            if not description or not isinstance(description, (list, tuple)):
                raise Exception("SQL inválido: sin metadata")

            try:
                columns = [desc[0] for desc in description]
            except Exception:
                _logger.error("DESCRIPTION CORRUPTO: %s", description)
                raise Exception("Error leyendo columnas del cursor")

            rows = request.env.cr.fetchall() or []

            # Validar consistencia columnas vs filas
            data = []
            for row in rows:
                record = {}
                if len(row) != len(columns):
                    _logger.error("Mismatch columnas/filas: %s vs %s", len(columns), len(row))
                    raise Exception("Inconsistencia en resultado SQL")
                for col, val in zip(columns, row):

                    # convertir datetime
                    if hasattr(val, "isoformat"):
                        record[col] = val.isoformat()

                    # otros tipos raros
                    elif isinstance(val, bytes):
                        record[col] = val.decode()

                    else:
                        record[col] = val

                data.append(record)

        except Exception as e:
            _logger.exception("SQL ERROR")

            return request.make_response(
                json.dumps({
                    "error": "Error ejecutando la consulta",
                    "detail": str(e)
                }),
                headers=[('Content-Type', 'application/json')],
                status=500
            )

        # -------------------------
        # COUNT
        # -------------------------
        total_records = 0

        try:
            count_sql = f"SELECT COUNT(*) FROM ({base_sql}) as count_query"

            _logger.info("COUNT SQL: %s", count_sql)

            request.env.cr.execute(count_sql, values)

            row = request.env.cr.fetchone()
            total_records = row[0] if row else 0

        except Exception:
            _logger.exception("COUNT ERROR")
            total_records = len(data)

        # -------------------------
        # METADATA
        # -------------------------
        total_pages = math.ceil(total_records / page_size) if page_size else 1

        end_time = datetime.now()
        execution_time = (end_time - start_time).total_seconds()

        _logger.info(
            "API END | query_key=%s | records=%s | total=%s | time=%.3fs",
            query_key,
            len(data),
            total_records,
            execution_time
        )

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