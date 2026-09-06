/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

/**
 * Formatea un valor segun la unidad de medida de la metrica.
 * La capa visual no calcula: solo presenta lo que devolvio el motor.
 */
export function formatValue(value, unitType, digits) {
    if (value === null || value === undefined) {
        return "N/D";
    }
    const decimals = unitType === "count" ? 0 : (digits === undefined ? 2 : digits);
    const formatted = new Intl.NumberFormat("es-UY", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    }).format(value);
    if (unitType === "money") {
        return `$ ${formatted}`;
    }
    if (unitType === "percent") {
        return `${formatted} %`;
    }
    return formatted;
}

/** Formatea una variacion porcentual, distinguiendo el comparable en cero. */
export function formatPercent(percent) {
    if (percent === null || percent === undefined) {
        return "N/D";
    }
    const sign = percent > 0 ? "+" : "";
    return `${sign}${percent.toFixed(2)} %`;
}

export class KpiCard extends Component {
    static template = "primate_advanced_dashboard.KpiCard";
    static props = { component: Object };

    get value() {
        const rows = this.props.component.rows || [];
        return rows.length ? rows[0].value : 0;
    }

    get formatted() {
        const cmp = this.props.component;
        return formatValue(this.value, cmp.unit_type, cmp.digits);
    }

    get variation() {
        const rows = this.props.component.rows || [];
        return rows.length ? rows[0].variation_percent : null;
    }

    get variationClass() {
        const variation = this.variation;
        if (variation === null || variation === undefined) {
            return "pad_neutral";
        }
        return variation >= 0 ? "pad_positive" : "pad_negative";
    }

    formatPercent(percent) {
        return formatPercent(percent);
    }
}

export class KpiComparative extends KpiCard {
    static template = "primate_advanced_dashboard.KpiComparative";

    get row() {
        const rows = this.props.component.rows || [];
        return rows.length ? rows[0] : {};
    }

    formatValue(value) {
        const cmp = this.props.component;
        return formatValue(value, cmp.unit_type, cmp.digits);
    }
}

export class Ranking extends Component {
    static template = "primate_advanced_dashboard.Ranking";
    static props = { component: Object };

    get rows() {
        return this.props.component.rows || [];
    }

    formatValue(value) {
        const cmp = this.props.component;
        return formatValue(value, cmp.unit_type, cmp.digits);
    }

    formatPercent(percent) {
        return formatPercent(percent);
    }
}

export class DataTable extends Ranking {
    static template = "primate_advanced_dashboard.DataTable";
}

export class Indicator extends KpiCard {
    static template = "primate_advanced_dashboard.Indicator";

    get stateClass() {
        const threshold = this.props.component.threshold || {};
        return threshold.state ? `pad_state_${threshold.state}` : "pad_state_none";
    }
}

/**
 * Heatmap de dos dimensiones (dia x franja horaria).
 * Adicion al catalogo de la seccion 9, requerida por el reporte R03.
 */
export class Heatmap extends Component {
    static template = "primate_advanced_dashboard.Heatmap";
    static props = { component: Object };

    get matrix() {
        const cells = this.props.component.cells || [];
        const rowKeys = [];
        const columnKeys = [];
        const byKey = {};
        let maxValue = 0;
        for (const cell of cells) {
            const rowKey = String(cell.row);
            const columnKey = String(cell.column);
            if (!rowKeys.some((row) => row.key === rowKey)) {
                rowKeys.push({ key: rowKey, label: cell.row_label, sort: cell.row });
            }
            if (!columnKeys.some((col) => col.key === columnKey)) {
                columnKeys.push({ key: columnKey, label: cell.column_label, sort: cell.column });
            }
            byKey[`${rowKey}|${columnKey}`] = cell.value;
            maxValue = Math.max(maxValue, cell.value);
        }
        const bySort = (a, b) => (a.sort > b.sort ? 1 : a.sort < b.sort ? -1 : 0);
        rowKeys.sort(bySort);
        columnKeys.sort(bySort);
        const rows = rowKeys.map((row) => ({
            label: row.label,
            cells: columnKeys.map((column) => {
                const value = byKey[`${row.key}|${column.key}`] || 0;
                return {
                    value,
                    formatted: formatValue(
                        value,
                        this.props.component.unit_type,
                        this.props.component.digits
                    ),
                    intensity: maxValue ? value / maxValue : 0,
                };
            }),
        }));
        return { columns: columnKeys, rows };
    }

    cellStyle(intensity) {
        // Escala de opacidad sobre un solo tono: legible en claro y en oscuro.
        const alpha = 0.08 + intensity * 0.72;
        return `background-color: rgba(1, 126, 132, ${alpha.toFixed(3)});`;
    }
}

// Registro extensible de componentes: un módulo que agregue un tipo nuevo de
// componente lo registra acá y el contenedor lo pinta sin tocar este archivo.
export const componentRegistry = registry.category("primate_dashboard_components");
componentRegistry.add("kpi_card", KpiCard);
componentRegistry.add("kpi_comparative", KpiComparative);
componentRegistry.add("ranking", Ranking);
componentRegistry.add("table", DataTable);
componentRegistry.add("indicator", Indicator);
componentRegistry.add("heatmap", Heatmap);

/** Contenedor del dashboard: pide el payload al motor y reparte los componentes. */
export class PrimateDashboardView extends Component {
    static template = "primate_advanced_dashboard.DashboardView";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            dashboard: null,
            error: null,
            periodTypeId: null,
            periodOffset: 0,
            comparisonId: null,
            dateFrom: null,
            dateTo: null,
            // Hasta que el usuario toque el selector no se manda comparison_id, para
            // que cada componente conserve el comparativo con el que fue configurado.
            comparisonTouched: false,
        });
        onWillStart(async () => {
            await this.loadDashboard();
        });
    }

    get dashboardId() {
        const params = this.props.action.params || this.props.action.context || {};
        return params.dashboard_id || false;
    }

    /** Primera carga: todavía no hay nada que pintar. */
    get isFirstLoad() {
        return this.state.loading && !this.state.dashboard;
    }

    /** El rango libre se maneja con dos fechas, no con navegación de períodos. */
    get isCustomPeriod() {
        return this.state.dashboard ? this.state.dashboard.period_code === "custom" : false;
    }

    /** No se navega hacia adelante más allá del período en curso. */
    get canGoForward() {
        return this.state.periodOffset < 0;
    }

    /** Traduce el estado de la barra a lo que espera el motor. */
    get filterValues() {
        const values = {};
        if (this.state.periodTypeId) {
            values.period_type_id = this.state.periodTypeId;
        }
        if (this.isCustomPeriod) {
            if (this.state.dateFrom && this.state.dateTo) {
                values.date_from = this.state.dateFrom;
                values.date_to = this.state.dateTo;
            }
        } else {
            values.period_offset = this.state.periodOffset;
        }
        if (this.state.comparisonTouched) {
            values.comparison_id = this.state.comparisonId || false;
        }
        return values;
    }

    async loadDashboard() {
        const dashboardId = this.dashboardId;
        if (!dashboardId) {
            this.state.loading = false;
            this.state.error = "No se indico que dashboard abrir.";
            return;
        }
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "primate.dashboard",
                "get_dashboard_data",
                [[dashboardId]],
                { filter_values: this.filterValues }
            );
            this.state.dashboard = data;
            this.state.error = null;
            // El motor es quien resuelve el período efectivo: la barra se sincroniza
            // con lo que devolvio, no al reves.
            this.state.periodTypeId = data.period_type_id;
            if (!this.state.dateFrom) {
                this.state.dateFrom = data.date_from;
            }
            if (!this.state.dateTo) {
                this.state.dateTo = data.date_to;
            }
            if (!this.state.comparisonTouched) {
                this.state.comparisonId = data.comparison_id;
            }
        } catch (error) {
            this.state.error = error.message ? error.message.data.message : String(error);
        } finally {
            this.state.loading = false;
        }
    }

    async onPeriodTypeChange(ev) {
        this.state.periodTypeId = parseInt(ev.target.value, 10);
        // Cambiar el grano reinicia la navegación: el offset de un mes no significa
        // lo mismo contado en semanas.
        this.state.periodOffset = 0;
        await this.loadDashboard();
    }

    async shiftPeriod(direction) {
        this.state.periodOffset += direction;
        await this.loadDashboard();
    }

    async onComparisonChange(ev) {
        const value = ev.target.value;
        this.state.comparisonTouched = true;
        this.state.comparisonId = value ? parseInt(value, 10) : false;
        await this.loadDashboard();
    }

    async onDateChange(key, ev) {
        this.state[key] = ev.target.value;
        if (this.state.dateFrom && this.state.dateTo) {
            await this.loadDashboard();
        }
    }

    componentClass(component) {
        const type = component.component_type;
        return componentRegistry.contains(type) ? componentRegistry.get(type) : null;
    }
}

registry.category("actions").add("primate_dashboard.view", PrimateDashboardView);
