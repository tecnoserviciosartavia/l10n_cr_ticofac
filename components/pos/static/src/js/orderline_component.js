/** @odoo-module **/
/**
 * Orderline UI extension for Discount Codes (Costa Rica FE)
 *
 * We extend the inline screen values to include discount code display + missing-code flag.
 */

import { patch } from "@web/core/utils/patch";
import { Orderline } from "@point_of_sale/app/components/orderline/orderline";

const desc = Object.getOwnPropertyDescriptor(Orderline.prototype, "lineScreenValues");
const originalGet = desc?.get;

patch(Orderline.prototype, {
    get lineScreenValues() {
        const values = originalGet ? originalGet.call(this) : {};
        // During early component linking the original getter can return an empty object
        if (!values || !Object.keys(values).length) {
            return values;
        }

        const line = this.line;
        const hasDiscount = (line?.discount || 0) > 0;
        if (!hasDiscount) {
            values.discountCodeDisplay = "";
            values.missingDiscountCode = false;
            return values;
        }

        // Use discountCodeId (camelCase) or getDiscountCodeId() method
        const codeId = line?.discountCodeId || (line?.getDiscountCodeId ? line.getDiscountCodeId() : null);
        if (!codeId) {
            values.discountCodeDisplay = "";
            values.missingDiscountCode = true;
            return values;
        }

        const code = line.getDiscountCode ? line.getDiscountCode() : null;
        values.discountCodeDisplay = code ? `${code.code} - ${code.name}` : `Código: ${codeId}`;
        values.missingDiscountCode = false;
        return values;
    },
});

console.log("✅ POS Discount Code - Orderline UI extension loaded");
