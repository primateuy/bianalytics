# -*- coding: utf-8 -*-
"""Siembra del mapeo de locales de FORUM.

El concepto "Local" no tiene un campo canónico en la base: el maestro es
stock.warehouse (códigos 001 a 046), el POS lo identifica por su usuario de sucursal
y la contabilidad por el diario de venta. Este hook resuelve ese mapeo una sola vez
para no depender de convenciones de nombres en cada consulta.
"""
import csv
import logging
import os
import re
import unicodedata

_logger = logging.getLogger(__name__)

MAPPING_FILE = os.path.join(os.path.dirname(__file__), 'data', 'forum_local_map.csv')

# Cajas cuyo prefijo de nombre no coincide con ningún código de almacén.
# 051 no existe como almacén: "051 - PANDO 2 - CAJA 2" pertenece al local 029.
POS_CONFIG_CODE_FIXES = {
    '051': '029',
}


def _normalize(text):
    """Normaliza un nombre para comparar: sin acentos, sin paréntesis, en mayúsculas."""
    text = unicodedata.normalize('NFKD', text or '')
    text = ''.join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r'\([^)]*\)', ' ', text)
    return re.sub(r'\s+', ' ', text.upper().replace('.', ' ')).strip()


def post_init_hook(env):
    """Asigna el local a los usuarios de POS, a los diarios de venta y a las cajas."""
    _map_users_and_journals(env)
    _map_pos_configs(env)


def _map_users_and_journals(env):
    """Recorre el mapeo declarado y asigna el local por nombre de usuario y código de diario."""
    warehouses = {wh.code: wh for wh in env['stock.warehouse'].search([])}
    users_by_name = {
        _normalize(user.partner_id.name): user
        for user in env['res.users'].with_context(active_test=False).search([])
    }
    journals_by_code = {
        journal.code: journal
        for journal in env['account.journal'].search([('type', '=', 'sale')])
    }

    mapped_users, mapped_journals, missing = 0, 0, []
    with open(MAPPING_FILE, newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            warehouse = warehouses.get(row['warehouse_code'])
            if not warehouse:
                missing.append('almacén %s' % row['warehouse_code'])
                continue
            user = users_by_name.get(_normalize(row['pos_user_name']))
            if user:
                user.pad_local_id = warehouse
                mapped_users += 1
            else:
                missing.append('usuario "%s"' % row['pos_user_name'])
            journal = journals_by_code.get(row['sale_journal_code'])
            if journal:
                journal.pad_local_id = warehouse
                mapped_journals += 1
            else:
                missing.append('diario %s' % row['sale_journal_code'])

    _logger.info(
        'Mapeo de locales FORUM: %s usuarios y %s diarios asignados',
        mapped_users, mapped_journals)
    if missing:
        # No es un error: en una base recortada faltan registros. Queda el aviso para
        # que se vea qué locales todavía no resuelven.
        _logger.warning(
            'Mapeo de locales FORUM: no se encontraron %s registros (%s)',
            len(missing), ', '.join(missing[:15]))


def _map_pos_configs(env):
    """Asigna el local a cada caja usando el prefijo numérico de su nombre."""
    warehouses = {wh.code: wh for wh in env['stock.warehouse'].search([])}
    mapped, unmatched = 0, []
    for config in env['pos.config'].with_context(active_test=False).search([]):
        prefix = (config.name or '').split(' - ')[0].strip()
        code = POS_CONFIG_CODE_FIXES.get(prefix, prefix)
        warehouse = warehouses.get(code)
        if warehouse:
            config.pad_local_id = warehouse
            mapped += 1
        else:
            unmatched.append(config.name)
    _logger.info('Mapeo de locales FORUM: %s cajas de POS asignadas', mapped)
    if unmatched:
        _logger.warning(
            'Mapeo de locales FORUM: %s cajas sin local (%s)',
            len(unmatched), ', '.join(unmatched[:10]))
