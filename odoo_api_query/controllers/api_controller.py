from odoo import http
from odoo.http import request
import json
import math
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)


class ApiQueryController(http.Controller):

    # -------------------------
    # VALIDADOR SQL
    # -------------------------
    def validate_sql(self, cr, sql, values=None):
        try:
            cr.execute("SAVEPOINT validate_sql")
            cr.execute(f"EXPLAIN {sql}", values or [])
            cr.execute("RELEASE SAVEPOINT validate_sql")
            return True, None
        except Exception as e:
            cr.execute("ROLLBACK TO SAVEPOINT validate_sql")
            return False, str(e)

    # -------------------------
    # ENDPOINT
    # -------------------------
    @http.route('/api/v1/query/execute', auth='public', methods=['POST'], csrf=False, type='http')
    def execute_query(self, **kwargs):

        log = None
        start_time = datetime.now()

        try:
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

            query_key = body.get("query_key")
            params = body.get("params") or {}

            # -------------------------
            # CREAR LOG (SIEMPRE)
            # -------------------------
            log = request.env['api.query.log'].sudo().create({
                "start_datetime": start_time,
                "query_key": query_key,
                "params_text": json.dumps(params),
            })

            # -------------------------
            # API KEY
            # -------------------------
            api_key = (request.httprequest.headers.get('X-API-Key') or '').strip()
            system_key = request.env['ir.config_parameter'].sudo().get_param('api_query.api_key') or ''

            if not api_key or api_key != system_key:
                raise Exception("Unauthorized")

            # -------------------------
            # PAGINACIÓN PARAMS
            # -------------------------
            page_size = int(body.get("page_size", 10))
            page_number = int(body.get("page_number", 1))

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
                raise Exception("query_key not found")

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
                    raise Exception(f"Campo inválido en filtro: '{key}'")

                filters.append(f"{field} {op} %s")
                values.append(value)

            if filters:
                if "where" in base_sql.lower():
                    base_sql += " AND " + " AND ".join(filters)
                else:
                    base_sql += " WHERE " + " AND ".join(filters)

            # -------------------------
            # PAGINACIÓN SQL
            # -------------------------
            offset = max((page_number - 1), 0) * page_size
            paginated_sql = f"{base_sql} LIMIT %s OFFSET %s"
            values_paginated = values + [page_size, offset]

            # -------------------------
            # VALIDAR SQL
            # -------------------------
            is_valid, error = self.validate_sql(request.env.cr, paginated_sql, values_paginated)

            if not is_valid:
                raise Exception(f"SQL inválido: {error}")

            # -------------------------
            # GUARDAR SQL EN LOG
            # -------------------------
            if log:
                log.write({
                    "sql_text": paginated_sql,
                    "params_text": json.dumps(values_paginated),
                })

            _logger.info("SQL: %s", paginated_sql)
            _logger.info("VALUES: %s", values_paginated)

            # -------------------------
            # EJECUCIÓN
            # -------------------------
            request.env.cr.execute(paginated_sql, values_paginated)

            description = request.env.cr.description

            if not description:
                raise Exception("SQL inválido: sin metadata")

            columns = [desc[0] for desc in description]
            rows = request.env.cr.fetchall() or []

            data = []
            for row in rows:
                if len(row) != len(columns):
                    raise Exception("Inconsistencia en resultado SQL")

                record = {}
                for col, val in zip(columns, row):
                    if hasattr(val, "isoformat"):
                        record[col] = val.isoformat()
                    elif isinstance(val, bytes):
                        record[col] = val.decode()
                    else:
                        record[col] = val

                data.append(record)

            # -------------------------
            # COUNT
            # -------------------------
            try:
                count_sql = f"SELECT COUNT(*) FROM ({base_sql}) as count_query"
                request.env.cr.execute(count_sql, values)
                row = request.env.cr.fetchone()
                total_records = row[0] if row else 0
            except Exception:
                _logger.exception("COUNT ERROR")
                total_records = len(data)

            # -------------------------
            # FINALIZAR LOG (SUCCESS)
            # -------------------------
            end_time = datetime.now()

            if log:
                log.write({
                    "end_datetime": end_time,
                    "status": "success",
                    "total_records": total_records,
                    "page_records": len(data),
                })

            # -------------------------
            # RESPONSE
            # -------------------------
            total_pages = math.ceil(total_records / page_size) if page_size else 1

            return request.make_response(
                json.dumps({
                    "metadata": {
                        "total_records": total_records,
                        "total_pages": total_pages,
                        "current_page": page_number,
                        "page_size": page_size,
                        "has_next": page_number < total_pages
                    },
                    "data": data
                }),
                headers=[('Content-Type', 'application/json')],
                status=200
            )

        # -------------------------
        # ERROR GLOBAL
        # -------------------------
        except Exception as e:

            _logger.exception("API ERROR GLOBAL")

            if log:
                log.write({
                    "end_datetime": datetime.now(),
                    "status": "error",
                    "error_message": str(e),
                })

            return request.make_response(
                json.dumps({
                    "error": "Error interno",
                    "detail": str(e)
                }),
                headers=[('Content-Type', 'application/json')],
                status=500
            )