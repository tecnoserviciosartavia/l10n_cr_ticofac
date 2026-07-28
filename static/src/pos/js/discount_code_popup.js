/** @odoo-module **/
/**
 * Discount Code Selection Popup for POS (Costa Rica FE)
 * 
 * This popup allows cashiers to select a discount code for a POS order line,
 * required when applying discounts for electronic invoicing compliance.
 */

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class DiscountCodePopup extends Component {
    static template = "l10n_cr_ticofac.DiscountCodePopup";
    static components = { Dialog };
    static props = {
        close: Function,
        getPayload: { type: Function, optional: true },
        orderline: { type: Object, optional: true },
    };

    setup() {
        this.pos = useService("pos");
        const currentCode = this.props.orderline?.getDiscountCode?.();
        this.state = useState({
            selectedCode: currentCode || null,
        });
    }

    get title() {
        return _t("Seleccionar Código de Descuento");
    }

    get discountCodes() {
        // Access loaded discount.code records from POS data
        const codes = this.pos.models["discount.code"]?.getAll?.() || [];
        return codes.filter(code => code.active !== false);
    }

    selectCode(code) {
        this.state.selectedCode = code;
    }

    isSelected(code) {
        return this.state.selectedCode?.id === code.id;
    }

    confirm() {
        if (this.props.getPayload) {
            this.props.getPayload(this.state.selectedCode);
        }
        this.props.close();
    }

    cancel() {
        // Just close the popup without changing anything
        // The previous discount code value remains unchanged
        this.props.close();
    }

    clearSelection() {
        this.state.selectedCode = null;
    }
}
