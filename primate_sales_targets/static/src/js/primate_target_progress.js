/** @odoo-module **/

import { Component } from "@odoo/owl";
import {
    componentRegistry,
    formatValue,
} from "@primate_advanced_dashboard/js/primate_dashboard";

/**
 * Avance de objetivos: una fila por sujeto, con su valor actual contra el objetivo.
 * Como todos los componentes del tablero, solo pinta lo que ya calculo el motor.
 */
export class TargetProgress extends Component {
    static template = "primate_sales_targets.TargetProgress";
    static props = { component: Object };

    get rows() {
        return this.props.component.rows || [];
    }

    formatValue(value) {
        const cmp = this.props.component;
        return formatValue(value, cmp.unit_type, cmp.digits);
    }

    /** El ancho de la barra se recorta al 100 % aunque el objetivo se haya superado. */
    barWidth(progress) {
        const bounded = Math.max(0, Math.min(progress || 0, 100));
        return `width: ${bounded.toFixed(2)}%;`;
    }

    formatProgress(progress) {
        if (progress === null || progress === undefined) {
            return "N/D";
        }
        return `${progress.toFixed(1)} %`;
    }

    rowClass(row) {
        if (row.state === "reached") {
            return "pst_reached";
        }
        if (row.state === "missed") {
            return "pst_missed";
        }
        return "pst_open";
    }
}

componentRegistry.add("target_progress", TargetProgress);
