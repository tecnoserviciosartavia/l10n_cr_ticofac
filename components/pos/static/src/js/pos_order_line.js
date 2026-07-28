/** @odoo-module **/
/**
 * POS OrderLine Extension for Discount Codes (Costa Rica FE)
 * 
 * This module extends PosOrderline to support discount codes required by
 * Costa Rica's electronic invoicing (FE) regulations.
 */

import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { patch } from "@web/core/utils/patch";

patch(PosOrderline.prototype, {
    setup(vals) {
        super.setup(...arguments);
        
        // Initialize discountCodeId from vals (backend sends as discount_code_id)
        this.discountCodeId = vals?.discount_code_id || null;
        
        // For refund lines: Copy from the original line
        if (!this.discountCodeId && vals?.refunded_orderline_id) {
            const originalLine = vals.refunded_orderline_id;
            if (originalLine && originalLine.discountCodeId) {
                this.discountCodeId = originalLine.discountCodeId;
                console.log("✅ Refund line: Copied discountCodeId from original:", this.discountCodeId);
            }
        }
    },

    /**
     * Set discount code for this orderline
     * @param {Object|null} discountCode - The discount.code record or null
     */
    setDiscountCode(discountCode) {
        this.discountCodeId = discountCode ? discountCode.id : null;
        // Call setDirty() to trigger OWL reactivity and UI refresh
        this.setDirty();
    },

    /**
     * Get the current discount code ID
     * @returns {number|null}
     */
    getDiscountCodeId() {
        return this.discountCodeId || null;
    },

    /**
     * Get the current discount code record
     * @returns {Object|null}
     */
    getDiscountCode() {
        const codeId = this.discountCodeId;
        if (codeId && this.models?.["discount.code"]) {
            return this.models["discount.code"].get(codeId);
        }
        return null;
    },

    /**
     * Get discount code display name
     * @returns {string}
     */
    getDiscountCodeDisplay() {
        const val = this.discountCodeId;
        if (!val) {
            return "";
        }

        // Try to resolve from models
        if (this.models && this.models["discount.code"]) {
            const record = this.models["discount.code"].get(val);
            if (record) {
                return `${record.code} - ${record.name}`;
            }
        }

        // Try via pos
        const pos = this.pos || (this.order && this.order.pos);
        if (pos && pos.models && pos.models["discount.code"]) {
            const record = pos.models["discount.code"].get(val);
            if (record) {
                return `${record.code} - ${record.name}`;
            }
        }

        return `Código: ${val}`;
    },

    /**
     * Check if this line needs a discount code (has discount but no code)
     * @returns {boolean}
     */
    needsDiscountCode() {
        return this.discount > 0 && !this.discountCodeId;
    },

    // Include discount_code_id when serializing for backend sync
    serialize(options) {
        const json = super.serialize(...arguments);
        if (json) {
            json.discount_code_id = this.discountCodeId || null;
        }
        return json;
    },

    // Load discount_code_id when initializing from JSON
    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        if (json?.discount_code_id) {
            this.discountCodeId = json.discount_code_id;
        }
    },
});

console.log("✅ POS Discount Code - OrderLine extension loaded");
