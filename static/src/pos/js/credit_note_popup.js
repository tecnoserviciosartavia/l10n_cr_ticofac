/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class CreditNotePopup extends Component {
    static template = "l10n_cr_ticofac.CreditNotePopup";
    static components = { Dialog };
    static props = {
        close: Function,
        getPayload: { type: Function, optional: true },
        originalInvoiceNumber: { type: String, optional: true },
    };

    setup() {
        this.pos = useService("pos");
        this.state = useState({
            reason: _t("Devolución de mercadería"),
            referenceCodeId: "",
        });
        // Set default after pos service is available
        const defaultId = this.getDefaultReferenceCodeId();
        if (defaultId) {
            this.state.referenceCodeId = String(defaultId);
        }
    }

    getDefaultReferenceCodeId() {
        // Default to "01" (Anula Documento de Referencia) or first available
        const codes = this.referenceCodes;
        const defaultCode = codes.find(c => c.code === "01") || codes[0];
        return defaultCode ? defaultCode.id : null;
    }

    get title() {
        return _t("Detalles de Nota de Crédito");
    }

    get referenceCodes() {
        const codes = this.pos.models["reference.code"]?.getAll?.() || [];
        return codes.filter(code => code.active !== false);
    }

    confirm() {
        if (this.props.getPayload) {
            // Convert referenceCodeId to integer since t-model on <select> returns a string
            const refCodeId = this.state.referenceCodeId;
            let parsedRefCodeId = null;
            if (refCodeId && refCodeId !== "") {
                const parsed = parseInt(refCodeId, 10);
                parsedRefCodeId = isNaN(parsed) ? null : parsed;
            }
            
            this.props.getPayload({
                reason: this.state.reason,
                referenceCodeId: parsedRefCodeId,
            });
        }
        this.props.close();
    }

    cancel() {
        this.props.close();
    }
}
